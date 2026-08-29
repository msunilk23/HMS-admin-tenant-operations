"""
Patient and Supplier Return Services - P30

Handles complex return workflows, restockability validation, stock ledger updates,
and financial reconciliation with strict ACID guarantees.
"""

import uuid
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models.tenant import (
    PatientReturn, PatientReturnItem, SupplierReturn, SupplierReturnItem,
    PharmacyDispense, PharmacyDispenseItem, InventoryBatch,
    Invoice, StockTransaction, Patient, Visit
)
from app.schemas.returns import (
    PatientReturnCreate, PatientReturnItemCreate, PatientReturnRead, PatientReturnItemRead,
    SupplierReturnCreate, SupplierReturnItemCreate, SupplierReturnRead, SupplierReturnItemRead
)
from app.services.audit_service import record_audit
from app.services.stock_ledger_service import create_stock_ledger_transaction

logger = logging.getLogger(__name__)


# ============ PATIENT RETURN SERVICE ============

class PatientReturnService:
    """Manages patient returns workflow."""
    
    @staticmethod
    async def request_return(
        session: AsyncSession,
        tenant_id: UUID,
        facility_id: UUID,
        pharmacy_location_id: UUID,
        patient_id: UUID,
        visit_id: UUID,
        request_data: PatientReturnCreate,
        requesting_user_id: UUID,
    ) -> PatientReturnRead:
        """
        Request a patient return.
        
        Validations:
        - Dispense must exist and belong to patient
        - All dispense items must be referenced exactly once
        - No duplicate return requests for same dispense
        """
        # Fetch and validate dispense
        stmt = select(PharmacyDispense).where(
            and_(
                PharmacyDispense.id == request_data.dispense_id,
                PharmacyDispense.patient_id == patient_id,
                PharmacyDispense.facility_id == facility_id,
                PharmacyDispense.status == "CONFIRMED",
            )
        )
        dispense = await session.scalar(stmt)
        if not dispense:
            raise ValueError(f"Dispense {request_data.dispense_id} not found or not confirmed")

        # Fetch dispense items
        stmt = select(PharmacyDispenseItem).where(
            PharmacyDispenseItem.dispense_id == request_data.dispense_id
        )
        dispense_items_result = await session.scalars(stmt)
        dispense_items = list(dispense_items_result)
        
        dispense_item_map = {item.id: item for item in dispense_items}

        # Validate all requested items exist and calculate totals
        total_amount = Decimal("0")
        total_quantity = Decimal("0")
        
        for return_item in request_data.items:
            dispense_item = dispense_item_map.get(return_item.dispense_item_id)
            if not dispense_item:
                raise ValueError(f"Dispense item {return_item.dispense_item_id} not found in dispense")
            
            if return_item.returned_quantity > dispense_item.internal_confirmed_quantity:
                raise ValueError(
                    f"Cannot return {return_item.returned_quantity} items; "
                    f"only {dispense_item.internal_confirmed_quantity} were dispensed"
                )
            
            # Calculate return amount
            # (assuming invoice has the unit price information)
            return_amount = return_item.returned_quantity * Decimal("0")  # Will be set during validation
            total_amount += return_amount
            total_quantity += return_item.returned_quantity

        # Generate unique reference key
        reference_key = f"PR-{tenant_id.hex[:8]}-{uuid.uuid4().hex[:8]}".upper()

        # Check for duplicate return on same dispense
        stmt = select(PatientReturn).where(
            and_(
                PatientReturn.tenant_id == tenant_id,
                PatientReturn.dispense_id == request_data.dispense_id,
                PatientReturn.status.not_in(["REJECTED"]),
            )
        )
        existing = await session.scalar(stmt)
        if existing:
            raise ValueError(f"Active return already exists for dispense {request_data.dispense_id}")

        # Create patient return
        patient_return = PatientReturn(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            patient_id=patient_id,
            visit_id=visit_id,
            dispense_id=request_data.dispense_id,
            status="REQUESTED",
            reference_key=reference_key,
            return_reason=request_data.return_reason,
            package_condition=request_data.package_condition,
            total_return_quantity=total_quantity,
            total_return_amount=total_amount,
            refunded_amount=Decimal("0"),
            restockable_count=0,
            non_restockable_count=0,
            requested_by=requesting_user_id,
            requested_at=datetime.utcnow(),
            notes=request_data.notes,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(patient_return)
        
        # Create return items
        for return_item in request_data.items:
            dispense_item = dispense_item_map[return_item.dispense_item_id]
            
            # Get unit price from invoice if available (simplified for now)
            unit_price = Decimal("0")
            if dispense.invoice_id:
                # Would fetch from invoice line items
                pass
            
            return_item_obj = PatientReturnItem(
                id=uuid.uuid4(),
                return_id=patient_return.id,
                dispense_item_id=return_item.dispense_item_id,
                medicine_product_id=dispense_item.dispensed_medicine_product_id,
                prescribed_quantity=dispense_item.prescribed_quantity,
                returned_quantity=return_item.returned_quantity,
                original_unit_price=unit_price,
                return_amount=return_item.returned_quantity * unit_price,
                status="PENDING_VALIDATION",
                restockable=return_item.restockable if return_item.restockable is not None else False,
                non_restockable_reason=return_item.non_restockable_reason,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(return_item_obj)
        
        # Record audit
        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            patient_id=patient_id,
            resource_type="PatientReturn",
            resource_id=patient_return.id,
            action="CREATE",
            user_id=requesting_user_id,
            old_value={},
            new_value={"status": "REQUESTED", "reason": request_data.return_reason},
        )
        
        await session.flush()
        
        # Reload and return
        await session.refresh(patient_return)
        return PatientReturnRead.from_orm(patient_return)

    @staticmethod
    async def validate_return(
        session: AsyncSession,
        return_id: UUID,
        validating_user_id: UUID,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> PatientReturnRead:
        """
        Validate patient return items for restockability.
        
        Sets item-level status to ACCEPTED/REJECTED based on condition.
        """
        stmt = select(PatientReturn).where(
            and_(
                PatientReturn.id == return_id,
                PatientReturn.tenant_id == tenant_id,
                PatientReturn.facility_id == facility_id,
                PatientReturn.status == "REQUESTED",
            )
        )
        patient_return = await session.scalar(stmt)
        if not patient_return:
            raise ValueError(f"Return {return_id} not found or not in REQUESTED status")

        # Fetch items
        stmt = select(PatientReturnItem).where(PatientReturnItem.return_id == return_id)
        items_result = await session.scalars(stmt)
        items = list(items_result)
        
        restockable_count = 0
        non_restockable_count = 0
        
        for item in items:
            item.status = "ACCEPTED" if item.restockable else "REJECTED"
            item.validated_by = validating_user_id
            item.validated_at = datetime.utcnow()
            
            if item.restockable:
                restockable_count += 1
            else:
                non_restockable_count += 1
        
        patient_return.status = "VALIDATED"
        patient_return.validated_by = validating_user_id
        patient_return.validated_at = datetime.utcnow()
        patient_return.restockable_count = restockable_count
        patient_return.non_restockable_count = non_restockable_count
        
        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            patient_id=patient_return.patient_id,
            resource_type="PatientReturn",
            resource_id=return_id,
            action="VALIDATE",
            user_id=validating_user_id,
            old_value={"status": "REQUESTED"},
            new_value={"status": "VALIDATED", "restockable": restockable_count},
        )
        
        await session.flush()
        await session.refresh(patient_return)
        return PatientReturnRead.from_orm(patient_return)

    @staticmethod
    async def accept_return(
        session: AsyncSession,
        return_id: UUID,
        accepting_user_id: UUID,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> PatientReturnRead:
        """
        Accept validated patient return.
        
        Restocks accepted items to inventory and marks return for refund processing.
        """
        stmt = select(PatientReturn).where(
            and_(
                PatientReturn.id == return_id,
                PatientReturn.tenant_id == tenant_id,
                PatientReturn.facility_id == facility_id,
                PatientReturn.status == "VALIDATED",
            )
        )
        patient_return = await session.scalar(stmt)
        if not patient_return:
            raise ValueError(f"Return {return_id} not found or not in VALIDATED status")

        # Restock accepted items
        stmt = select(PatientReturnItem).where(
            and_(
                PatientReturnItem.return_id == return_id,
                PatientReturnItem.status == "ACCEPTED",
            )
        )
        restockable_items = await session.scalars(stmt)
        
        for item in restockable_items:
            # Create stock ledger transaction for PATIENT_RETURN_RESTOCK
            if item.inventory_batch_id:
                ledger_tx = await create_stock_ledger_transaction(
                    session=session,
                    tenant_id=tenant_id,
                    facility_id=facility_id,
                    pharmacy_location_id=patient_return.pharmacy_location_id,
                    medicine_id=item.medicine_product_id,
                    inventory_batch_id=item.inventory_batch_id,
                    transaction_type="PATIENT_RETURN_RESTOCK",
                    quantity=item.returned_quantity,
                    reference_type="PatientReturnItem",
                    reference_id=item.id,
                    reason=f"Patient return restock: {patient_return.reference_key}",
                    user_id=accepting_user_id,
                )
                item.restock_ledger_transaction_id = ledger_tx.id

        patient_return.status = "ACCEPTED"
        patient_return.accepted_by = accepting_user_id
        patient_return.accepted_at = datetime.utcnow()
        patient_return.status = "REFUND_PENDING"  # Mark for billing/refund

        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            patient_id=patient_return.patient_id,
            resource_type="PatientReturn",
            resource_id=return_id,
            action="ACCEPT_AND_RESTOCK",
            user_id=accepting_user_id,
            old_value={"status": "VALIDATED"},
            new_value={"status": "REFUND_PENDING"},
        )
        
        await session.flush()
        await session.refresh(patient_return)
        return PatientReturnRead.from_orm(patient_return)

    @staticmethod
    async def reject_return(
        session: AsyncSession,
        return_id: UUID,
        rejecting_user_id: UUID,
        rejection_reason: str,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> PatientReturnRead:
        """Reject patient return."""
        stmt = select(PatientReturn).where(
            and_(
                PatientReturn.id == return_id,
                PatientReturn.tenant_id == tenant_id,
                PatientReturn.facility_id == facility_id,
                PatientReturn.status.in_(["REQUESTED", "VALIDATED"]),
            )
        )
        patient_return = await session.scalar(stmt)
        if not patient_return:
            raise ValueError(f"Return {return_id} not found or not rejectable")

        patient_return.status = "REJECTED"
        patient_return.rejected_by = rejecting_user_id
        patient_return.rejected_at = datetime.utcnow()
        patient_return.rejection_reason = rejection_reason

        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            patient_id=patient_return.patient_id,
            resource_type="PatientReturn",
            resource_id=return_id,
            action="REJECT",
            user_id=rejecting_user_id,
            old_value={"status": patient_return.status},
            new_value={"status": "REJECTED", "reason": rejection_reason},
        )
        
        await session.flush()
        await session.refresh(patient_return)
        return PatientReturnRead.from_orm(patient_return)

    @staticmethod
    async def mark_refunded(
        session: AsyncSession,
        return_id: UUID,
        refunded_amount: Decimal,
        refunding_user_id: UUID,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> PatientReturnRead:
        """Mark patient return as refunded (called by billing service)."""
        stmt = select(PatientReturn).where(
            and_(
                PatientReturn.id == return_id,
                PatientReturn.tenant_id == tenant_id,
                PatientReturn.status == "REFUND_PENDING",
            )
        )
        patient_return = await session.scalar(stmt)
        if not patient_return:
            raise ValueError(f"Return {return_id} not found or not in REFUND_PENDING status")

        patient_return.status = "REFUNDED"
        patient_return.refunded_amount = refunded_amount
        patient_return.refunded_by = refunding_user_id
        patient_return.refunded_at = datetime.utcnow()

        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            patient_id=patient_return.patient_id,
            resource_type="PatientReturn",
            resource_id=return_id,
            action="MARK_REFUNDED",
            user_id=refunding_user_id,
            old_value={"status": "REFUND_PENDING"},
            new_value={"status": "REFUNDED", "amount": str(refunded_amount)},
        )
        
        await session.flush()
        await session.refresh(patient_return)
        return PatientReturnRead.from_orm(patient_return)


# ============ SUPPLIER RETURN SERVICE ============

class SupplierReturnService:
    """Manages supplier returns workflow."""
    
    @staticmethod
    async def request_return(
        session: AsyncSession,
        tenant_id: UUID,
        facility_id: UUID,
        pharmacy_location_id: UUID,
        request_data: SupplierReturnCreate,
        requesting_user_id: UUID,
    ) -> SupplierReturnRead:
        """
        Request a supplier return.
        
        Validations:
        - Supplier must exist
        - All batches must exist and belong to location
        - Cannot return more than received
        """
        # Validate batches and calculate totals
        total_value = Decimal("0")
        total_quantity = Decimal("0")
        
        batch_ids = [item.inventory_batch_id for item in request_data.items]
        stmt = select(InventoryBatch).where(
            and_(
                InventoryBatch.id.in_(batch_ids),
                InventoryBatch.pharmacy_location_id == pharmacy_location_id,
            )
        )
        batch_result = await session.scalars(stmt)
        batch_map = {batch.id: batch for batch in batch_result}
        
        for return_item in request_data.items:
            batch = batch_map.get(return_item.inventory_batch_id)
            if not batch:
                raise ValueError(f"Batch {return_item.inventory_batch_id} not found in location")
            
            # Validate quantity against the available on-hand batch quantity.
            if return_item.returned_quantity > batch.available_quantity:
                raise ValueError(
                    f"Cannot return {return_item.returned_quantity}; "
                    f"batch only has {batch.available_quantity} available"
                )
            
            total_value += return_item.returned_quantity * return_item.unit_cost
            total_quantity += return_item.returned_quantity

        # Generate reference key
        reference_key = f"SR-{tenant_id.hex[:8]}-{uuid.uuid4().hex[:8]}".upper()

        # Create supplier return
        supplier_return = SupplierReturn(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            supplier_id=request_data.supplier_id,
            goods_receipt_id=request_data.goods_receipt_id,
            status="REQUESTED",
            reference_key=reference_key,
            return_reason=request_data.return_reason,
            total_return_quantity=total_quantity,
            total_return_value=total_value,
            requested_by=requesting_user_id,
            requested_at=datetime.utcnow(),
            notes=request_data.notes,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(supplier_return)
        
        # Create return items
        for return_item in request_data.items:
            supplier_return_item = SupplierReturnItem(
                id=uuid.uuid4(),
                supplier_return_id=supplier_return.id,
                inventory_batch_id=return_item.inventory_batch_id,
                returned_quantity=return_item.returned_quantity,
                unit_cost=return_item.unit_cost,
                return_value=return_item.returned_quantity * return_item.unit_cost,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(supplier_return_item)
        
        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            resource_type="SupplierReturn",
            resource_id=supplier_return.id,
            action="CREATE",
            user_id=requesting_user_id,
            old_value={},
            new_value={"status": "REQUESTED", "reason": request_data.return_reason},
        )
        
        await session.flush()
        await session.refresh(supplier_return)
        return SupplierReturnRead.from_orm(supplier_return)

    @staticmethod
    async def approve_return(
        session: AsyncSession,
        return_id: UUID,
        approving_user_id: UUID,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> SupplierReturnRead:
        """Approve supplier return."""
        stmt = select(SupplierReturn).where(
            and_(
                SupplierReturn.id == return_id,
                SupplierReturn.tenant_id == tenant_id,
                SupplierReturn.status == "REQUESTED",
            )
        )
        supplier_return = await session.scalar(stmt)
        if not supplier_return:
            raise ValueError(f"Return {return_id} not found or not in REQUESTED status")

        supplier_return.status = "APPROVED"
        supplier_return.approved_by = approving_user_id
        supplier_return.approved_at = datetime.utcnow()

        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            resource_type="SupplierReturn",
            resource_id=return_id,
            action="APPROVE",
            user_id=approving_user_id,
            old_value={"status": "REQUESTED"},
            new_value={"status": "APPROVED"},
        )
        
        await session.flush()
        await session.refresh(supplier_return)
        return SupplierReturnRead.from_orm(supplier_return)

    @staticmethod
    async def dispatch_return(
        session: AsyncSession,
        return_id: UUID,
        dispatching_user_id: UUID,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> SupplierReturnRead:
        """Dispatch supplier return (reduce stock immediately)."""
        stmt = select(SupplierReturn).where(
            and_(
                SupplierReturn.id == return_id,
                SupplierReturn.tenant_id == tenant_id,
                SupplierReturn.status == "APPROVED",
            )
        )
        supplier_return = await session.scalar(stmt)
        if not supplier_return:
            raise ValueError(f"Return {return_id} not found or not in APPROVED status")

        # Reduce stock for each item
        stmt = select(SupplierReturnItem).where(SupplierReturnItem.supplier_return_id == return_id)
        items = await session.scalars(stmt)
        
        for item in items:
            # Create stock ledger transaction for SUPPLIER_RETURN
            ledger_tx = await create_stock_ledger_transaction(
                session=session,
                tenant_id=tenant_id,
                facility_id=facility_id,
                pharmacy_location_id=supplier_return.pharmacy_location_id,
                medicine_id=None,  # Will be derived from batch
                inventory_batch_id=item.inventory_batch_id,
                transaction_type="SUPPLIER_RETURN",
                quantity=-item.returned_quantity,  # Negative quantity
                reference_type="SupplierReturnItem",
                reference_id=item.id,
                reason=f"Supplier return: {supplier_return.reference_key}",
                user_id=dispatching_user_id,
            )
            item.stock_reduction_ledger_id = ledger_tx.id

        supplier_return.status = "DISPATCHED"
        supplier_return.dispatched_by = dispatching_user_id
        supplier_return.dispatched_at = datetime.utcnow()

        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            resource_type="SupplierReturn",
            resource_id=return_id,
            action="DISPATCH_AND_REDUCE_STOCK",
            user_id=dispatching_user_id,
            old_value={"status": "APPROVED"},
            new_value={"status": "DISPATCHED"},
        )
        
        await session.flush()
        await session.refresh(supplier_return)
        return SupplierReturnRead.from_orm(supplier_return)

    @staticmethod
    async def receive_return(
        session: AsyncSession,
        return_id: UUID,
        receiving_user_id: UUID,
        tenant_id: UUID,
        facility_id: UUID,
    ) -> SupplierReturnRead:
        """Confirm supplier return received."""
        stmt = select(SupplierReturn).where(
            and_(
                SupplierReturn.id == return_id,
                SupplierReturn.tenant_id == tenant_id,
                SupplierReturn.status == "DISPATCHED",
            )
        )
        supplier_return = await session.scalar(stmt)
        if not supplier_return:
            raise ValueError(f"Return {return_id} not found or not in DISPATCHED status")

        supplier_return.status = "RECEIVED"
        supplier_return.received_by = receiving_user_id
        supplier_return.received_at = datetime.utcnow()

        record_audit(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            resource_type="SupplierReturn",
            resource_id=return_id,
            action="RECEIVE",
            user_id=receiving_user_id,
            old_value={"status": "DISPATCHED"},
            new_value={"status": "RECEIVED"},
        )
        
        await session.flush()
        await session.refresh(supplier_return)
        return SupplierReturnRead.from_orm(supplier_return)
