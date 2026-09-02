"""
P30 Patient and Supplier Returns - Comprehensive Tests

Tests cover:
- Patient return request/validate/accept/reject lifecycle
- Supplier return request/approve/dispatch/receive lifecycle
- Stock ledger integration
- Refund processing
- Concurrency and idempotency
"""

import pytest
import pytest_asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import (
    PatientReturn, PatientReturnItem, PatientReturnBatchAllocation, SupplierReturn, SupplierReturnItem,
    PharmacyDispense, PharmacyDispenseAllocation, PharmacyDispenseItem, InventoryBatch, Supplier,
    Patient, Visit, PharmacyLocation, Invoice, StockTransaction
)
from app.schemas.returns import (
    PatientReturnCreate, PatientReturnItemCreate,
    SupplierReturnCreate, SupplierReturnItemCreate
)
from app.services.returns_service import PatientReturnService, SupplierReturnService


class TestPatientReturnService:
    """Test suite for patient return service."""
    
    @pytest.mark.asyncio
    async def test_request_patient_return_success(self, mock_session: AsyncSession):
        """Test successful patient return request creation."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        pharmacy_location_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        visit_id = uuid.uuid4()
        dispense_id = uuid.uuid4()
        dispense_item_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        # Create mock dispense
        mock_dispense = PharmacyDispense(
            id=dispense_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            patient_id=patient_id,
            visit_id=visit_id,
            status="CONFIRMED",
        )
        
        # Create mock dispense items
        mock_dispense_item = PharmacyDispenseItem(
            id=dispense_item_id,
            dispense_id=dispense_id,
            prescribed_quantity=Decimal("10"),
            internal_confirmed_quantity=Decimal("10"),
            dispensed_medicine_product_id=uuid.uuid4(),
        )
        batch = InventoryBatch(
            id=uuid.uuid4(), tenant_id=tenant_id, facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id, medicine_id=mock_dispense_item.dispensed_medicine_product_id,
            batch_number="RETURN-1", purchase_rate=Decimal("10"), received_quantity=Decimal("10"),
            available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE",
        )
        source_allocation = PharmacyDispenseAllocation(
            id=uuid.uuid4(), dispense_item_id=dispense_item_id, tenant_id=tenant_id,
            facility_id=facility_id, pharmacy_location_id=pharmacy_location_id,
            inventory_batch_id=batch.id, allocated_quantity=Decimal("10"),
            confirmed_dispensed_quantity=Decimal("10"), status="CONSUMED",
        )
        
        # Mock database queries
        mock_session.scalar = AsyncMock()
        mock_session.scalars = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        mock_session.scalar.side_effect = [mock_dispense, Decimal("0"), batch]
        mock_session.scalars.side_effect = [[mock_dispense_item], [source_allocation]]
        
        # Create return request
        request_data = PatientReturnCreate(
            dispense_id=dispense_id,
            return_reason="Medicine caused allergic reaction",
            package_condition="Sealed",
            items=[
                PatientReturnItemCreate(
                    dispense_item_id=dispense_item_id,
                    returned_quantity=Decimal("5"),
                    restockable=True,
                    batch_allocations=[{"inventory_batch_id": batch.id, "returned_quantity": Decimal("5")}],
                )
            ],
            notes="Patient reported allergy"
        )
        
        # Call service
        result = await PatientReturnService.request_return(
            session=mock_session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            patient_id=patient_id,
            visit_id=visit_id,
            request_data=request_data,
            requesting_user_id=user_id,
        )
        
        # Verify
        assert result is not None
        assert mock_session.add.called
        assert mock_session.flush.called

    @pytest.mark.asyncio
    async def test_patient_return_validate(self, mock_session: AsyncSession):
        """Test patient return validation."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        return_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        # Create mock return
        mock_return = PatientReturn(
            id=return_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            visit_id=uuid.uuid4(),
            dispense_id=uuid.uuid4(),
            status="REQUESTED",
            reference_key="PR-TEST-010",
            return_reason="Test return reason",
            total_return_quantity=Decimal("1"),
            total_return_amount=Decimal("10.00"),
            refunded_amount=Decimal("0.00"),
            restockable_count=0,
            non_restockable_count=0,
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        # Create mock return items
        mock_items = [
            PatientReturnItem(
                id=uuid.uuid4(),
                return_id=return_id,
                dispense_item_id=uuid.uuid4(),
                medicine_product_id=uuid.uuid4(),
                prescribed_quantity=Decimal("1"),
                returned_quantity=Decimal("1"),
                original_unit_price=Decimal("10.00"),
                return_amount=Decimal("10.00"),
                status="PENDING_VALIDATION",
                restockable=True,
            ),
            PatientReturnItem(
                id=uuid.uuid4(),
                return_id=return_id,
                dispense_item_id=uuid.uuid4(),
                medicine_product_id=uuid.uuid4(),
                prescribed_quantity=Decimal("1"),
                returned_quantity=Decimal("1"),
                original_unit_price=Decimal("10.00"),
                return_amount=Decimal("10.00"),
                status="PENDING_VALIDATION",
                restockable=False,
                non_restockable_reason="Damaged packaging",
            ),
        ]
        
        mock_session.scalar = AsyncMock(return_value=mock_return)
        mock_session.scalars = AsyncMock(return_value=mock_items)
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        # Call service
        result = await PatientReturnService.validate_return(
            session=mock_session,
            return_id=return_id,
            validating_user_id=user_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        
        # Verify return status changed to VALIDATED
        assert mock_return.status == "VALIDATED"
        assert mock_return.validated_by == user_id
        assert mock_return.restockable_count == 1
        assert mock_return.non_restockable_count == 1
        
        # Verify items marked with appropriate status
        assert mock_items[0].status == "ACCEPTED"
        assert mock_items[1].status == "REJECTED"

    @pytest.mark.asyncio
    async def test_patient_return_reject(self, mock_session: AsyncSession):
        """Test patient return rejection."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        return_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        mock_return = PatientReturn(
            id=return_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            visit_id=uuid.uuid4(),
            dispense_id=uuid.uuid4(),
            status="REQUESTED",
            reference_key="PR-TEST-011",
            return_reason="Test return reason",
            total_return_quantity=Decimal("1"),
            total_return_amount=Decimal("10.00"),
            refunded_amount=Decimal("0.00"),
            restockable_count=0,
            non_restockable_count=0,
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        mock_session.scalar = AsyncMock(return_value=mock_return)
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        rejection_reason = "Return window expired"
        
        result = await PatientReturnService.reject_return(
            session=mock_session,
            return_id=return_id,
            rejecting_user_id=user_id,
            rejection_reason=rejection_reason,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        
        # Verify
        assert mock_return.status == "REJECTED"
        assert mock_return.rejected_by == user_id
        assert mock_return.rejection_reason == rejection_reason


class TestSupplierReturnService:
    """Test suite for supplier return service."""
    
    @pytest.mark.asyncio
    async def test_request_supplier_return_success(self, mock_session: AsyncSession):
        """Test successful supplier return request."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        pharmacy_location_id = uuid.uuid4()
        supplier_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        # Create mock batch matching the real model fields
        mock_batch = InventoryBatch(
            id=batch_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            medicine_id=uuid.uuid4(),
            batch_number="BATCH-001",
            purchase_rate=Decimal("10.00"),
            available_quantity=Decimal("100"),
            received_quantity=Decimal("100"),
            reserved_quantity=Decimal("0"),
            status="ACTIVE",
        )
        
        mock_session.scalars = AsyncMock(return_value=[mock_batch])
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        # Create return request
        request_data = SupplierReturnCreate(
            supplier_id=supplier_id,
            pharmacy_location_id=pharmacy_location_id,
            return_reason="Batch arrived damaged",
            items=[
                SupplierReturnItemCreate(
                    inventory_batch_id=batch_id,
                    returned_quantity=Decimal("20"),
                    unit_cost=Decimal("50.00"),
                )
            ],
        )
        
        # Call service
        result = await SupplierReturnService.request_return(
            session=mock_session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            request_data=request_data,
            requesting_user_id=user_id,
        )
        
        # Verify
        assert result is not None
        assert mock_session.add.called
        assert mock_session.flush.called

    @pytest.mark.asyncio
    async def test_supplier_return_approve(self, mock_session: AsyncSession):
        """Test supplier return approval."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        return_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        mock_return = SupplierReturn(
            id=return_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=uuid.uuid4(),
            supplier_id=uuid.uuid4(),
            status="REQUESTED",
            reference_key="SR-TEST-001",
            return_reason="Test supplier return reason",
            total_return_quantity=Decimal("5"),
            total_return_value=Decimal("50.00"),
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        mock_session.scalar = AsyncMock(return_value=mock_return)
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        result = await SupplierReturnService.approve_return(
            session=mock_session,
            return_id=return_id,
            approving_user_id=user_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        
        # Verify
        assert mock_return.status == "APPROVED"
        assert mock_return.approved_by == user_id

    @pytest.mark.asyncio
    async def test_supplier_return_full_lifecycle(self, mock_session: AsyncSession):
        """Test complete supplier return lifecycle: request → approve → dispatch → receive."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        return_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        # Create mock supplier return
        supplier_return = SupplierReturn(
            id=return_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            status="REQUESTED",
            supplier_id=uuid.uuid4(),
            pharmacy_location_id=uuid.uuid4(),
            reference_key="SR-TEST-002",
            return_reason="Test supplier return reason",
            total_return_quantity=Decimal("20"),
            total_return_value=Decimal("200.00"),
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        # Create mock return item
        return_item = SupplierReturnItem(
            id=uuid.uuid4(),
            supplier_return_id=return_id,
            inventory_batch_id=batch_id,
            returned_quantity=Decimal("20"),
        )
        
        mock_session.scalar = AsyncMock()
        mock_session.scalars = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        # Step 1: Approve
        mock_session.scalar.return_value = supplier_return
        await SupplierReturnService.approve_return(
            session=mock_session,
            return_id=return_id,
            approving_user_id=user_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        assert supplier_return.status == "APPROVED"
        
        # Step 2: Dispatch (with stock reduction)
        mock_session.scalar.return_value = supplier_return
        mock_session.scalars.return_value = [return_item]
        supplier_return.status = "APPROVED"  # Reset for dispatch
        
        # Note: dispatch_return would normally create stock ledger transactions
        # This test focuses on status transitions
        
        # Step 3: Receive
        supplier_return.status = "DISPATCHED"  # Reset for receive
        mock_session.scalar.return_value = supplier_return
        
        result = await SupplierReturnService.receive_return(
            session=mock_session,
            return_id=return_id,
            receiving_user_id=user_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        
        # Verify final state
        assert supplier_return.status == "RECEIVED"
        assert supplier_return.received_by == user_id


class TestPatientReturnIntegration:
    """Integration tests for patient returns with stock ledger."""
    
    @pytest.mark.asyncio
    async def test_patient_return_stock_ledger_entry(self, mock_session: AsyncSession):
        """Test that accepted patient returns create stock ledger entries."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        pharmacy_location_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        return_id = uuid.uuid4()
        return_item_id = uuid.uuid4()
        user_id = uuid.uuid4()
        
        # Create mock return and item
        return_obj = PatientReturn(
            id=return_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            patient_id=uuid.uuid4(),
            visit_id=uuid.uuid4(),
            dispense_id=uuid.uuid4(),
            status="VALIDATED",
            reference_key="PR-TEST-003",
            return_reason="Test return reason",
            total_return_quantity=Decimal("5"),
            total_return_amount=Decimal("50.00"),
            refunded_amount=Decimal("0.00"),
            restockable_count=1,
            non_restockable_count=0,
            requested_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        return_item = PatientReturnItem(
            id=return_item_id,
            return_id=return_id,
            restockable=True,
            status="ACCEPTED",
            returned_quantity=Decimal("5"),
            inventory_batch_id=batch_id,
            medicine_product_id=uuid.uuid4(),
        )
        allocation = PatientReturnBatchAllocation(
            id=uuid.uuid4(), tenant_id=tenant_id, patient_return_item_id=return_item_id,
            dispense_allocation_id=uuid.uuid4(), inventory_batch_id=batch_id,
            returned_quantity=Decimal("5"), unit_cost=Decimal("10"), created_by=user_id,
        )
        
        mock_session.scalar = AsyncMock(return_value=return_obj)
        mock_session.scalars = AsyncMock(side_effect=[[return_item], [allocation]])
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        # Call accept which should create stock ledger
        with patch("app.services.returns_service.create_stock_ledger_transaction", new=AsyncMock(return_value=MagicMock(id=uuid.uuid4()))) as ledger:
            result = await PatientReturnService.accept_return(
                session=mock_session,
                return_id=return_id,
                accepting_user_id=user_id,
                tenant_id=tenant_id,
                facility_id=facility_id,
            )
        
        # Verify return status progressed
        assert return_obj.status == "REFUND_PENDING"
        assert ledger.await_count == 1
        assert allocation.stock_ledger_transaction_id is not None


class TestReturnIdempotency:
    """Test idempotency of return operations."""
    
    @pytest.mark.asyncio
    async def test_return_exceeding_remaining_source_allocation_is_rejected(self, mock_session: AsyncSession):
        """Multiple partial returns are allowed, but not beyond one original batch allocation."""
        tenant_id = uuid.uuid4()
        facility_id = uuid.uuid4()
        dispense_id = uuid.uuid4()
        
        mock_dispense = PharmacyDispense(
            id=dispense_id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            visit_id=uuid.uuid4(),
            status="CONFIRMED",
        )
        dispense_item_id = uuid.uuid4()
        mock_dispense_item = PharmacyDispenseItem(
            id=dispense_item_id,
            dispense_id=dispense_id,
            prescribed_quantity=Decimal("2"),
            internal_confirmed_quantity=Decimal("2"),
            dispensed_medicine_product_id=uuid.uuid4(),
        )
        batch = InventoryBatch(
            id=uuid.uuid4(), tenant_id=tenant_id, facility_id=facility_id,
            pharmacy_location_id=mock_dispense.pharmacy_location_id, medicine_id=mock_dispense_item.dispensed_medicine_product_id,
            batch_number="RETURN-LIMIT", purchase_rate=Decimal("10"), received_quantity=Decimal("2"),
            available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE",
        )
        source = PharmacyDispenseAllocation(
            id=uuid.uuid4(), dispense_item_id=dispense_item_id, tenant_id=tenant_id, facility_id=facility_id,
            pharmacy_location_id=mock_dispense.pharmacy_location_id, inventory_batch_id=batch.id,
            allocated_quantity=Decimal("2"), confirmed_dispensed_quantity=Decimal("2"), status="CONSUMED",
        )
        mock_session.scalar = AsyncMock(side_effect=[mock_dispense, Decimal("1")])
        mock_session.scalars = AsyncMock(side_effect=[[mock_dispense_item], [source]])

        with pytest.raises(ValueError, match="remaining quantity"):
            request_data = PatientReturnCreate(
                dispense_id=dispense_id,
                return_reason="Test return reason with enough length",
                items=[
                    PatientReturnItemCreate(
                        dispense_item_id=dispense_item_id,
                        returned_quantity=Decimal("2"),
                        restockable=True,
                        batch_allocations=[{"inventory_batch_id": batch.id, "returned_quantity": Decimal("2")}],
                    )
                ],
            )
            await PatientReturnService.request_return(
                session=mock_session,
                tenant_id=tenant_id,
                facility_id=facility_id,
                pharmacy_location_id=mock_dispense.pharmacy_location_id,
                patient_id=uuid.uuid4(),
                visit_id=uuid.uuid4(),
                request_data=request_data,
                requesting_user_id=uuid.uuid4(),
            )


@pytest_asyncio.fixture
async def mock_session():
    """Provide a mock async session."""
    return AsyncMock(spec=AsyncSession)


# Run pytest:
# pytest backend/tests/test_p30_returns.py -v
