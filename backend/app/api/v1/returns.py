"""
Patient and Supplier Return API Endpoints - P30

REST API for managing patient and supplier returns.
"""

from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user, get_session, get_tenant_id_from_token, get_facility_id
from app.core.security import require_permission, require_role
from app.models.tenant import User, PharmacyLocation
from app.schemas.returns import (
    PatientReturnCreate, PatientReturnRead, PatientReturnAcceptRequest, PatientReturnRejectRequest,
    PatientReturnValidateRequest,
    SupplierReturnCreate, SupplierReturnRead, SupplierReturnApproveRequest,
    SupplierReturnDispatchRequest, SupplierReturnReceiveRequest,
)
from app.services.returns_service import PatientReturnService, SupplierReturnService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1", tags=["returns"])


# ============ PATIENT RETURN ENDPOINTS ============

@router.post("/patient-returns", response_model=PatientReturnRead, status_code=status.HTTP_201_CREATED)
async def request_patient_return(
    request: PatientReturnCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Request a patient return for dispensed medicines.
    
    **Permissions**: PHARMACY_RETURN_REQUEST
    """
    from sqlalchemy import select, and_
    from app.models.tenant import PharmacyDispense
    
    await require_permission(session, current_user.id, "PHARMACY_RETURN_REQUEST")
    
    # Fetch dispense to get patient_id, visit_id, pharmacy_location_id
    stmt = select(PharmacyDispense).where(
        and_(
            PharmacyDispense.id == request.dispense_id,
            PharmacyDispense.facility_id == facility_id,
            PharmacyDispense.tenant_id == tenant_id,
        )
    )
    dispense = await session.scalar(stmt)
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
            requesting_user_id=current_user.id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to request return")


@router.post("/patient-returns/{return_id}/validate", response_model=PatientReturnRead)
async def validate_patient_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Validate patient return items for restockability.
    
    **Permissions**: PHARMACY_RETURN_VALIDATE
    """
    await require_permission(session, current_user.id, "PHARMACY_RETURN_VALIDATE")
    
    try:
        result = await PatientReturnService.validate_return(
            session=session,
            return_id=return_id,
            validating_user_id=current_user.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to validate return")


@router.post("/patient-returns/{return_id}/accept", response_model=PatientReturnRead)
async def accept_patient_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Accept validated patient return and restock items.
    
    **Permissions**: PHARMACY_RETURN_ACCEPT
    """
    await require_permission(session, current_user.id, "PHARMACY_RETURN_ACCEPT")
    
    try:
        result = await PatientReturnService.accept_return(
            session=session,
            return_id=return_id,
            accepting_user_id=current_user.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to accept return")


@router.post("/patient-returns/{return_id}/reject", response_model=PatientReturnRead)
async def reject_patient_return(
    return_id: UUID,
    request: PatientReturnRejectRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Reject patient return.
    
    **Permissions**: PHARMACY_RETURN_REJECT
    """
    await require_permission(session, current_user.id, "PHARMACY_RETURN_REJECT")
    
    try:
        result = await PatientReturnService.reject_return(
            session=session,
            return_id=return_id,
            rejecting_user_id=current_user.id,
            rejection_reason=request.rejection_reason,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to reject return")


@router.get("/patient-returns/{return_id}", response_model=PatientReturnRead)
async def get_patient_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
):
    """Get patient return details."""
    from sqlalchemy import select, and_
    from app.models.tenant import PatientReturn
    
    stmt = select(PatientReturn).where(
        and_(
            PatientReturn.id == return_id,
            PatientReturn.tenant_id == tenant_id,
        )
    )
    patient_return = await session.scalar(stmt)
    if not patient_return:
        raise HTTPException(status_code=404, detail="Patient return not found")
    
    return PatientReturnRead.from_orm(patient_return)


# ============ SUPPLIER RETURN ENDPOINTS ============

@router.post("/supplier-returns", response_model=SupplierReturnRead, status_code=status.HTTP_201_CREATED)
async def request_supplier_return(
    request: SupplierReturnCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Request a supplier return for received goods.
    
    **Permissions**: SUPPLIER_RETURN_REQUEST
    """
    from sqlalchemy import select, and_
    from app.models.tenant import PharmacyLocation
    
    await require_permission(session, current_user.id, "SUPPLIER_RETURN_REQUEST")
    
    # Fetch default pharmacy location for facility
    stmt = select(PharmacyLocation).where(
        and_(
            PharmacyLocation.facility_id == facility_id,
            PharmacyLocation.tenant_id == tenant_id,
            PharmacyLocation.is_primary == True,
        )
    )
    pharmacy_location = await session.scalar(stmt)
    if not pharmacy_location:
        raise HTTPException(status_code=404, detail="Pharmacy location not found")
    
    try:
        result = await SupplierReturnService.request_return(
            session=session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location.id,
            request_data=request,
            requesting_user_id=current_user.id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to request supplier return")


@router.post("/supplier-returns/{return_id}/approve", response_model=SupplierReturnRead)
async def approve_supplier_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Approve supplier return.
    
    **Permissions**: SUPPLIER_RETURN_APPROVE
    """
    await require_permission(session, current_user.id, "SUPPLIER_RETURN_APPROVE")
    
    try:
        result = await SupplierReturnService.approve_return(
            session=session,
            return_id=return_id,
            approving_user_id=current_user.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to approve supplier return")


@router.post("/supplier-returns/{return_id}/dispatch", response_model=SupplierReturnRead)
async def dispatch_supplier_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Dispatch supplier return (reduce stock immediately).
    
    **Permissions**: SUPPLIER_RETURN_DISPATCH
    """
    await require_permission(session, current_user.id, "SUPPLIER_RETURN_DISPATCH")
    
    try:
        result = await SupplierReturnService.dispatch_return(
            session=session,
            return_id=return_id,
            dispatching_user_id=current_user.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to dispatch supplier return")


@router.post("/supplier-returns/{return_id}/receive", response_model=SupplierReturnRead)
async def receive_supplier_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    """
    Confirm supplier return received.
    
    **Permissions**: SUPPLIER_RETURN_RECEIVE
    """
    await require_permission(session, current_user.id, "SUPPLIER_RETURN_RECEIVE")
    
    try:
        result = await SupplierReturnService.receive_return(
            session=session,
            return_id=return_id,
            receiving_user_id=current_user.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
        )
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to receive supplier return")


@router.get("/supplier-returns/{return_id}", response_model=SupplierReturnRead)
async def get_supplier_return(
    return_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
):
    """Get supplier return details."""
    from sqlalchemy import select, and_
    from app.models.tenant import SupplierReturn
    
    stmt = select(SupplierReturn).where(
        and_(
            SupplierReturn.id == return_id,
            SupplierReturn.tenant_id == tenant_id,
        )
    )
    supplier_return = await session.scalar(stmt)
    if not supplier_return:
        raise HTTPException(status_code=404, detail="Supplier return not found")
    
    return SupplierReturnRead.from_orm(supplier_return)
