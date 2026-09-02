"""
Patient and Supplier Return API Endpoints - P30

REST API for managing patient and supplier returns.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id, get_tenant_id_from_token
from app.core.dependencies import require_permission
from app.db.engine import get_session
from app.models.tenant import Patient, PatientReturnBatchAllocation, PatientReturnItem, PharmacyDispense, PharmacyDispenseAllocation, PharmacyDispenseItem, PharmacyLocation
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.returns import PatientReturn, SupplierReturn
from app.schemas.returns import (
    PatientReturnCreate,
    PatientReturnEligibilityRead,
    PatientReturnEligibleDispenseRead,
    PatientReturnListResponse,
    PatientReturnRead,
    PatientReturnRejectRequest,
    SupplierReturnCreate,
    SupplierReturnListResponse,
    SupplierReturnRead,
)
from app.services.returns_service import PatientReturnService, SupplierReturnService

router = APIRouter(tags=["returns"])


async def _patient_return_eligibility(
    session: AsyncSession,
    dispense: PharmacyDispense,
    patient: Patient,
    tenant_id: UUID,
    facility_id: UUID,
) -> dict:
    rows = (
        await session.execute(
            select(PharmacyDispenseItem, InventoryBatch, PharmacyDispenseAllocation)
            .join(PharmacyDispenseAllocation, PharmacyDispenseAllocation.dispense_item_id == PharmacyDispenseItem.id)
            .join(InventoryBatch, InventoryBatch.id == PharmacyDispenseAllocation.inventory_batch_id)
            .where(
                PharmacyDispenseItem.dispense_id == dispense.id,
                PharmacyDispenseAllocation.tenant_id == tenant_id,
                PharmacyDispenseAllocation.facility_id == facility_id,
                PharmacyDispenseAllocation.status == "CONSUMED",
            )
            .order_by(InventoryBatch.expiry_date.asc().nulls_last())
        )
    ).all()
    allocation_ids = [allocation.id for _, _, allocation in rows]
    previously_returned: dict[UUID, Decimal] = {}
    if allocation_ids:
        previous_rows = await session.execute(
            select(
                PatientReturnBatchAllocation.dispense_allocation_id,
                func.coalesce(func.sum(PatientReturnBatchAllocation.returned_quantity), Decimal("0")),
            )
            .join(PatientReturnItem, PatientReturnBatchAllocation.patient_return_item_id == PatientReturnItem.id)
            .join(PatientReturn, PatientReturnItem.return_id == PatientReturn.id)
            .where(
                PatientReturnBatchAllocation.dispense_allocation_id.in_(allocation_ids),
                PatientReturn.status.not_in(["REJECTED"]),
            )
            .group_by(PatientReturnBatchAllocation.dispense_allocation_id)
        )
        previously_returned = {allocation_id: Decimal(str(quantity)) for allocation_id, quantity in previous_rows}

    grouped: dict[UUID, list[dict]] = {}
    for dispense_item, inventory_batch, allocation in rows:
        prior_quantity = previously_returned.get(allocation.id, Decimal("0"))
        remaining_quantity = allocation.confirmed_dispensed_quantity - prior_quantity
        grouped.setdefault(dispense_item.id, []).append({
            "allocation_id": str(allocation.id),
            "inventory_batch_id": str(inventory_batch.id),
            "batch_number": inventory_batch.batch_number,
            "expiry_date": inventory_batch.expiry_date.isoformat() if inventory_batch.expiry_date else None,
            "originally_dispensed_quantity": str(allocation.confirmed_dispensed_quantity),
            "previously_returned_quantity": str(prior_quantity),
            "remaining_returnable_quantity": str(max(remaining_quantity, Decimal("0"))),
        })

    items = []
    for dispense_item in (
        await session.execute(select(PharmacyDispenseItem).where(PharmacyDispenseItem.dispense_id == dispense.id))
    ).scalars().all():
        allocations = grouped.get(dispense_item.id, [])
        remaining_quantity = sum((Decimal(entry["remaining_returnable_quantity"]) for entry in allocations), Decimal("0"))
        items.append({
            "dispense_item_id": str(dispense_item.id),
            "medicine_name": dispense_item.prescribed_name_snapshot,
            "prescribed_quantity": str(dispense_item.prescribed_quantity),
            "originally_dispensed_quantity": str(dispense_item.internal_confirmed_quantity),
            "previously_returned_quantity": str(dispense_item.internal_confirmed_quantity - remaining_quantity),
            "remaining_returnable_quantity": str(remaining_quantity),
            "allocations": allocations,
        })
    return {
        "dispense_id": str(dispense.id),
        "patient_id": str(patient.id),
        "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
        "visit_id": str(dispense.visit_id),
        "invoice_id": str(dispense.invoice_id) if dispense.invoice_id else None,
        "prescription_id": str(dispense.prescription_id),
        "dispense_reference": str(dispense.id),
        "facility_id": str(dispense.facility_id),
        "pharmacy_location_id": str(dispense.pharmacy_location_id),
        "items": items,
    }


@router.post("/patient-returns", response_model=PatientReturnRead, status_code=status.HTTP_201_CREATED)
async def request_patient_return(
    request: PatientReturnCreate,
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    dispense = await session.scalar(
        select(PharmacyDispense).where(
            and_(
                PharmacyDispense.id == request.dispense_id,
                PharmacyDispense.tenant_id == tenant_id,
                PharmacyDispense.facility_id == facility_id,
            )
        )
    )
    if not dispense:
        raise HTTPException(status_code=404, detail="Dispense not found")

    try:
        result = await PatientReturnService.request_return(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=dispense.pharmacy_location_id,
            patient_id=dispense.patient_id,
            visit_id=dispense.visit_id,
            request_data=request,
            requesting_user_id=UUID(str(current_user["sub"])),
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to request return")


@router.post("/patient-returns/{return_id}/validate", response_model=PatientReturnRead)
async def validate_patient_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_VALIDATE")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    try:
        result = await PatientReturnService.validate_return(
            session=session,
            return_id=return_id,
            validating_user_id=UUID(str(current_user["sub"])),
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to validate return")


@router.post("/patient-returns/{return_id}/accept", response_model=PatientReturnRead)
async def accept_patient_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_ACCEPT")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    try:
        result = await PatientReturnService.accept_return(
            session=session,
            return_id=return_id,
            accepting_user_id=UUID(str(current_user["sub"])),
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to accept return")


@router.post("/patient-returns/{return_id}/reject", response_model=PatientReturnRead)
async def reject_patient_return(
    return_id: UUID,
    request: PatientReturnRejectRequest,
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_REJECT")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    try:
        result = await PatientReturnService.reject_return(
            session=session,
            return_id=return_id,
            rejecting_user_id=UUID(str(current_user["sub"])),
            rejection_reason=request.rejection_reason,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to reject return")


@router.get("/patient-returns", response_model=PatientReturnListResponse)
async def list_patient_returns(
    status: str | None = None,
    patient_id: UUID | None = None,
    dispense_id: UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    stmt = select(PatientReturn).where(PatientReturn.tenant_id == tenant_id, PatientReturn.facility_id == facility_id)
    if status:
        stmt = stmt.where(PatientReturn.status == status)
    if patient_id:
        stmt = stmt.where(PatientReturn.patient_id == patient_id)
    if dispense_id:
        stmt = stmt.where(PatientReturn.dispense_id == dispense_id)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await session.execute(
            stmt.order_by(PatientReturn.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": [PatientReturnRead.from_orm(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total or 0,
        "total_pages": total_pages,
    }


@router.get("/patient-returns/eligible-dispenses", response_model=list[PatientReturnEligibleDispenseRead])
async def list_patient_return_eligible_dispenses(
    q: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    stmt = (
        select(PharmacyDispense, Patient)
        .join(Patient, Patient.id == PharmacyDispense.patient_id)
        .where(
            PharmacyDispense.tenant_id == tenant_id,
            PharmacyDispense.facility_id == facility_id,
            PharmacyDispense.status == "CONFIRMED",
        )
        .order_by(PharmacyDispense.completed_at.desc().nulls_last(), PharmacyDispense.created_at.desc())
        .limit(limit)
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Patient.uhid.ilike(term), Patient.first_name.ilike(term), Patient.last_name.ilike(term)))
    candidates = (await session.execute(stmt)).all()
    eligible = []
    for dispense, patient in candidates:
        eligibility = await _patient_return_eligibility(session, dispense, patient, tenant_id, facility_id)
        if any(Decimal(item["remaining_returnable_quantity"]) > 0 for item in eligibility["items"]):
            eligible.append({
                "dispense_id": str(dispense.id),
                "patient_id": str(patient.id),
                "patient_name": eligibility["patient_name"],
                "patient_uhid": patient.uhid,
                "visit_id": str(dispense.visit_id),
                "prescription_id": str(dispense.prescription_id),
                "invoice_id": str(dispense.invoice_id) if dispense.invoice_id else None,
                "dispense_reference": str(dispense.id),
                "completed_at": dispense.completed_at.isoformat() if dispense.completed_at else None,
            })
    return eligible


@router.get("/patient-returns/eligibility/{dispense_id}", response_model=PatientReturnEligibilityRead)
async def get_patient_return_eligibility(
    dispense_id: UUID,
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    row = (await session.execute(
        select(PharmacyDispense, Patient).join(Patient, Patient.id == PharmacyDispense.patient_id).where(
            and_(
                PharmacyDispense.id == dispense_id,
                PharmacyDispense.tenant_id == tenant_id,
                PharmacyDispense.facility_id == facility_id,
            )
        )
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Dispense not found")
    dispense, patient = row
    return await _patient_return_eligibility(session, dispense, patient, tenant_id, facility_id)


@router.get("/patient-returns/{return_id}", response_model=PatientReturnRead)
async def get_patient_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("PHARMACY_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    record = await session.scalar(
        select(PatientReturn).where(
            and_(
                PatientReturn.id == return_id,
                PatientReturn.tenant_id == tenant_id,
                PatientReturn.facility_id == facility_id,
            )
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="Patient return not found")
    return record


@router.post("/supplier-returns", response_model=SupplierReturnRead, status_code=status.HTTP_201_CREATED)
async def request_supplier_return(
    request: SupplierReturnCreate,
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    location = await session.scalar(
        select(PharmacyLocation).where(
            and_(
                PharmacyLocation.id == request.pharmacy_location_id,
                PharmacyLocation.facility_id == facility_id,
                PharmacyLocation.tenant_id == tenant_id,
                PharmacyLocation.location_type == "PHARMACY",
                PharmacyLocation.active == True,
            )
        )
    )
    if not location:
        raise HTTPException(status_code=404, detail="Pharmacy location not found in the authenticated facility")

    try:
        result = await SupplierReturnService.request_return(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=request.pharmacy_location_id,
            request_data=request,
            requesting_user_id=UUID(str(current_user["sub"])),
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to request supplier return")


@router.post("/supplier-returns/{return_id}/approve", response_model=SupplierReturnRead)
async def approve_supplier_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_APPROVE")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    try:
        result = await SupplierReturnService.approve_return(
            session=session,
            return_id=return_id,
            approving_user_id=UUID(str(current_user["sub"])),
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to approve supplier return")


@router.post("/supplier-returns/{return_id}/dispatch", response_model=SupplierReturnRead)
async def dispatch_supplier_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_DISPATCH")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    try:
        result = await SupplierReturnService.dispatch_return(
            session=session,
            return_id=return_id,
            dispatching_user_id=UUID(str(current_user["sub"])),
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to dispatch supplier return")


@router.post("/supplier-returns/{return_id}/receive", response_model=SupplierReturnRead)
async def receive_supplier_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_RECEIVE")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    try:
        result = await SupplierReturnService.receive_return(
            session=session,
            return_id=return_id,
            receiving_user_id=UUID(str(current_user["sub"])),
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to receive supplier return")


@router.get("/supplier-returns", response_model=SupplierReturnListResponse)
async def list_supplier_returns(
    status: str | None = None,
    supplier_id: UUID | None = None,
    goods_receipt_id: UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    stmt = select(SupplierReturn).where(SupplierReturn.tenant_id == tenant_id, SupplierReturn.facility_id == facility_id)
    if status:
        stmt = stmt.where(SupplierReturn.status == status)
    if supplier_id:
        stmt = stmt.where(SupplierReturn.supplier_id == supplier_id)
    if goods_receipt_id:
        stmt = stmt.where(SupplierReturn.goods_receipt_id == goods_receipt_id)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await session.execute(
            stmt.order_by(SupplierReturn.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": [SupplierReturnRead.from_orm(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total or 0,
        "total_pages": total_pages,
    }


@router.get("/supplier-returns/eligibility")
async def get_supplier_return_eligibility(
    supplier_id: UUID,
    facility_id: UUID = Depends(get_facility_id),
    pharmacy_location_id: UUID = Query(...),
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
):
    from app.models.tenant.supplier import Supplier

    supplier = await session.get(Supplier, supplier_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(status_code=404, detail="Supplier not found")

    location = await session.scalar(
        select(PharmacyLocation).where(
            and_(
                PharmacyLocation.id == pharmacy_location_id,
                PharmacyLocation.tenant_id == tenant_id,
                PharmacyLocation.facility_id == facility_id,
                PharmacyLocation.location_type == "PHARMACY",
                PharmacyLocation.active == True,
            )
        )
    )
    if not location:
        raise HTTPException(status_code=404, detail="Pharmacy location not found in the authenticated facility")

    batches = (
        await session.execute(
            select(InventoryBatch).where(
                and_(
                    InventoryBatch.tenant_id == tenant_id,
                    InventoryBatch.facility_id == facility_id,
                    InventoryBatch.pharmacy_location_id == pharmacy_location_id,
                    InventoryBatch.supplier_id == supplier_id,
                    InventoryBatch.available_quantity > Decimal("0"),
                )
            ).order_by(InventoryBatch.expiry_date.asc().nulls_last())
        )
    ).scalars().all()

    return {
        "supplier_id": str(supplier_id),
        "supplier_name": supplier.supplier_name,
        "goods_receipt_id": None,
        "purchase_order_id": None,
        "facility_id": str(facility_id),
        "pharmacy_location_id": str(pharmacy_location_id),
        "items": [
            {
                "inventory_batch_id": str(batch.id),
                "batch_number": batch.batch_number,
                "medicine_name": None,
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                "available_quantity": str(batch.available_quantity),
                "original_received_quantity": str(batch.received_quantity),
                "eligible_return_quantity": str(batch.available_quantity),
                "unit_cost": str(batch.purchase_rate),
                "supplier_id": str(supplier_id),
                "goods_receipt_id": str(batch.goods_receipt_id) if batch.goods_receipt_id else None,
                "purchase_order_id": None,
            }
            for batch in batches
        ],
    }


@router.get("/supplier-returns/{return_id}", response_model=SupplierReturnRead)
async def get_supplier_return(
    return_id: UUID,
    current_user: dict = Depends(require_permission("SUPPLIER_RETURN_REQUEST")),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    record = await session.scalar(
        select(SupplierReturn).where(
            and_(
                SupplierReturn.id == return_id,
                SupplierReturn.tenant_id == tenant_id,
                SupplierReturn.facility_id == facility_id,
            )
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="Supplier return not found")
    return record
