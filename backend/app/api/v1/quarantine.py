from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id, get_tenant_id_from_token
from app.core.dependencies import require_permission
from app.db.engine import get_session
from app.models.tenant import InventoryBatch, StockQuarantine
from app.schemas.quarantine import (
    QuarantineBatchRead,
    StockQuarantineCreate,
    StockQuarantineDispose,
    StockQuarantineListResponse,
    StockQuarantineRead,
    StockQuarantineRelease,
)
from app.services.quarantine_service import QuarantineNotFoundError, create_quarantine, dispose_quarantine, release_quarantine

router = APIRouter()


@router.get("/batches", response_model=list[QuarantineBatchRead])
async def list_quarantine_candidates(
    pharmacy_location_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_QUARANTINE_VIEW")),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    stmt = select(InventoryBatch).where(
        InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id,
        InventoryBatch.available_quantity > 0,
    )
    if pharmacy_location_id is not None:
        stmt = stmt.where(InventoryBatch.pharmacy_location_id == pharmacy_location_id)
    return (await session.execute(stmt.order_by(InventoryBatch.expiry_date.asc().nulls_last(), InventoryBatch.batch_number))).scalars().all()


@router.get("", response_model=StockQuarantineListResponse)
async def list_quarantines(
    quarantine_status: str | None = Query(default=None, alias="status"),
    pharmacy_location_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_QUARANTINE_VIEW")),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    stmt = select(StockQuarantine).where(StockQuarantine.tenant_id == tenant_id, StockQuarantine.facility_id == facility_id)
    if quarantine_status:
        stmt = stmt.where(StockQuarantine.status == quarantine_status.upper())
    if pharmacy_location_id:
        stmt = stmt.where(StockQuarantine.pharmacy_location_id == pharmacy_location_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await session.execute(stmt.order_by(StockQuarantine.created_at.desc()))).scalars().all()
    return {"items": rows, "total": total or 0}


@router.post("", response_model=StockQuarantineRead, status_code=status.HTTP_201_CREATED)
async def quarantine_stock(
    payload: StockQuarantineCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_QUARANTINE_CREATE")),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    return await _commit_or_400(session, create_quarantine(session, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


@router.post("/{quarantine_id}/release", response_model=StockQuarantineRead)
async def release_stock(
    quarantine_id: UUID,
    payload: StockQuarantineRelease,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_QUARANTINE_APPROVE")),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    return await _commit_or_400(session, release_quarantine(session, quarantine_id=quarantine_id, tenant_id=tenant_id, facility_id=facility_id, release_reason=payload.release_reason, current_user=current_user))


@router.post("/{quarantine_id}/dispose", response_model=StockQuarantineRead)
async def dispose_stock(
    quarantine_id: UUID,
    payload: StockQuarantineDispose,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_QUARANTINE_APPROVE")),
    tenant_id: UUID = Depends(get_tenant_id_from_token),
    facility_id: UUID = Depends(get_facility_id),
):
    return await _commit_or_400(session, dispose_quarantine(session, quarantine_id=quarantine_id, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


async def _commit_or_400(session: AsyncSession, operation):
    try:
        result = await operation
        await session.commit()
        await session.refresh(result)
        return result
    except QuarantineNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise