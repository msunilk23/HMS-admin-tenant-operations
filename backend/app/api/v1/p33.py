from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id, get_tenant_id_from_token
from app.core.dependencies import require_permission
from app.db.engine import get_session
from app.models.tenant import AuditLog, CountDetail, CountRecount, CountRecountDetail, StockCount
from app.schemas.p33 import (
    CountAction, CountCancel, CountCreate, CountDetailRead, CountDetailResponse,
    CountDetailUpdate, CountListResponse, CountRead, RecountDetailRead,
    RecountDetailUpdate, RecountRead, RecountRequest, UnexpectedStockCreate, VarianceListResponse,
)
from app.services.p33_service import (
    P33ConflictError, P33NotFoundError, P33ValidationError, apply_count, approve_count,
    add_unexpected_stock, cancel_count, create_count, record_detail, record_recount_detail, request_recount,
    resubmit_recount, start_count, start_recount, submit_count,
)

router = APIRouter()


async def _commit(session: AsyncSession, operation):
    try:
        result = await operation
        await session.commit()
        return result
    except P33NotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except P33ConflictError as exc:
        await session.rollback()
        if exc.audit_event:
            from app.services.audit_service import record_audit
            record_audit(session, **exc.audit_event)
            await session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except P33ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise


async def _count_or_404(session: AsyncSession, count_id: UUID, tenant_id: UUID, facility_id: UUID) -> StockCount:
    count = await session.scalar(select(StockCount).where(
        StockCount.id == count_id, StockCount.tenant_id == tenant_id, StockCount.facility_id == facility_id,
    ))
    if count is None:
        raise HTTPException(status_code=404, detail="Inventory count not found")
    return count


@router.get("", response_model=CountListResponse)
async def list_counts(
    count_status: str | None = Query(default=None, alias="status"),
    count_type: str | None = None,
    pharmacy_location_id: UUID | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("INVENTORY_COUNT_VIEW")),
    tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id),
):
    query = select(StockCount).where(StockCount.tenant_id == tenant_id, StockCount.facility_id == facility_id)
    if count_status:
        query = query.where(StockCount.status == count_status.upper())
    if count_type:
        query = query.where(StockCount.count_type == count_type.upper())
    if pharmacy_location_id:
        query = query.where(StockCount.pharmacy_location_id == pharmacy_location_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(StockCount.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": rows, "total": total or 0, "page": page, "page_size": page_size}


@router.get("/variances", response_model=VarianceListResponse)
async def list_variances(
    classification: str | None = None,
    pharmacy_location_id: UUID | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("INVENTORY_COUNT_VIEW")),
    tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id),
):
    query = select(CountDetail).join(StockCount).where(
        StockCount.tenant_id == tenant_id, StockCount.facility_id == facility_id,
        CountDetail.variance_quantity.is_not(None), CountDetail.variance_quantity != 0,
    )
    if pharmacy_location_id:
        query = query.where(StockCount.pharmacy_location_id == pharmacy_location_id)
    if classification:
        query = query.where(CountDetail.classifications.contains([classification.upper()]))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(CountDetail.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": rows, "total": total or 0, "page": page, "page_size": page_size}


@router.get("/{count_id}", response_model=CountDetailResponse)
async def get_count(
    count_id: UUID, session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("INVENTORY_COUNT_VIEW")),
    tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id),
):
    count = await _count_or_404(session, count_id, tenant_id, facility_id)
    details = list((await session.execute(select(CountDetail).where(CountDetail.count_id == count.id).order_by(CountDetail.batch_number, CountDetail.id))).scalars().all())
    recounts = list((await session.execute(select(CountRecount).where(CountRecount.count_id == count.id).order_by(CountRecount.attempt_number))).scalars().all())
    recount_payload = []
    for recount in recounts:
        values = list((await session.execute(select(CountRecountDetail).where(CountRecountDetail.recount_id == recount.id).order_by(CountRecountDetail.count_detail_id))).scalars().all())
        recount_payload.append({**RecountRead.model_validate(recount).model_dump(), "details": [RecountDetailRead.model_validate(value) for value in values]})
    resource_ids = [str(count.id), *(str(detail.id) for detail in details), *(str(recount.id) for recount in recounts)]
    history = list((await session.execute(select(AuditLog).where(AuditLog.resource_id.in_(resource_ids)).order_by(AuditLog.timestamp))).scalars().all())
    header = CountRead.model_validate(count).model_dump()
    return {
        **header, "details": details, "recounts": recount_payload,
        "history": [{"action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id, "user_id": str(row.user_id) if row.user_id else None, "timestamp": row.timestamp.isoformat(), "reason": row.reason, "old_value": row.old_value, "new_value": row.new_value} for row in history],
    }


@router.post("", response_model=CountRead, status_code=status.HTTP_201_CREATED)
async def post_count(
    payload: CountCreate, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_INITIATE")),
    tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id),
):
    return await _commit(session, create_count(session, tenant_id=tenant_id, facility_id=facility_id, payload=payload, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/start", response_model=CountRead)
async def post_start(count_id: UUID, payload: CountAction, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECORD")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, start_count(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=idempotency_key, current_user=current_user))


@router.patch("/{count_id}/details/{detail_id}", response_model=CountDetailRead)
async def patch_detail(count_id: UUID, detail_id: UUID, payload: CountDetailUpdate, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECORD")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, record_detail(session, count_id=count_id, detail_id=detail_id, tenant_id=tenant_id, facility_id=facility_id, physical_quantity=payload.physical_quantity, version=payload.version, variance_reason=payload.variance_reason, evidence=payload.evidence, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/details/unexpected", response_model=CountDetailRead, status_code=status.HTTP_201_CREATED)
async def post_unexpected_detail(count_id: UUID, payload: UnexpectedStockCreate, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECORD")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, add_unexpected_stock(session, count_id=count_id, inventory_batch_id=payload.inventory_batch_id, tenant_id=tenant_id, facility_id=facility_id, physical_quantity=payload.physical_quantity, evidence=payload.evidence, variance_reason=payload.variance_reason, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/submit", response_model=CountRead)
async def post_submit(count_id: UUID, payload: CountAction, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_COMPLETE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, submit_count(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/recounts", response_model=CountRead)
async def post_recount(count_id: UUID, payload: RecountRequest, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECOUNT")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, request_recount(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, reason=payload.reason, assigned_to=payload.assigned_to, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/recounts/start", response_model=CountRead)
async def post_recount_start(count_id: UUID, payload: CountAction, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECOUNT")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, start_recount(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=idempotency_key, current_user=current_user))


@router.patch("/{count_id}/recounts/details/{detail_id}", response_model=RecountDetailRead)
async def patch_recount_detail(count_id: UUID, detail_id: UUID, payload: RecountDetailUpdate, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECOUNT")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, record_recount_detail(session, count_id=count_id, detail_id=detail_id, tenant_id=tenant_id, facility_id=facility_id, physical_quantity=payload.physical_quantity, version=payload.version, variance_reason=payload.variance_reason, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/recounts/resubmit", response_model=CountRead)
async def post_recount_resubmit(count_id: UUID, payload: CountAction, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_RECOUNT")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, resubmit_recount(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/approve", response_model=CountRead)
async def post_approve(count_id: UUID, payload: CountAction, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_APPROVE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, approve_count(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, reason=payload.reason, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/apply", response_model=CountRead)
async def post_apply(count_id: UUID, payload: CountAction, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_APPLY")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, apply_count(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, reason=payload.reason, idempotency_key=idempotency_key, current_user=current_user))


@router.post("/{count_id}/cancel", response_model=CountRead)
async def post_cancel(count_id: UUID, payload: CountCancel, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=100), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("INVENTORY_COUNT_CANCEL")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, cancel_count(session, count_id=count_id, tenant_id=tenant_id, facility_id=facility_id, reason=payload.reason, idempotency_key=idempotency_key, current_user=current_user))