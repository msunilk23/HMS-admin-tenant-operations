from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id, get_tenant_id_from_token
from app.core.dependencies import require_permission
from app.db.engine import get_session
from app.models.tenant import InventoryBatch, ProductRecall, RecallAffectedStock, StockTransfer, StockTransferDiscrepancy, StockTransferItem
from app.schemas.p32 import (
    AffectedDispensingRead, DiscrepancyReconcile, EligibleTransferBatch, IdempotentAction,
    RecallCreate, RecallDetail, RecallNotificationUpdate, RecallRead, RecallResolve,
    TransferCreate, TransferDetail, TransferDiscrepancyRead, TransferRead, TransferReceive,
)
from app.services.p32_service import (
    P32NotFoundError, affected_dispensings, approve_recall, approve_transfer, cancel_transfer,
    create_recall, create_transfer, dispatch_transfer, receive_transfer, reconcile_discrepancy,
    resolve_recall, update_recall_notification,
)

recall_router = APIRouter()
transfer_router = APIRouter()


async def _commit(session: AsyncSession, operation):
    try:
        result = await operation
        await session.commit()
        await session.refresh(result)
        return result
    except P32NotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise


@recall_router.get("", response_model=list[RecallRead])
async def list_recalls(session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_VIEW")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return (await session.execute(select(ProductRecall).where(ProductRecall.tenant_id == tenant_id, ProductRecall.facility_id == facility_id).order_by(ProductRecall.created_at.desc()))).scalars().all()


@recall_router.get("/{recall_id}", response_model=RecallDetail)
async def get_recall(recall_id: UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_VIEW")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    record = await session.scalar(select(ProductRecall).where(ProductRecall.id == recall_id, ProductRecall.tenant_id == tenant_id, ProductRecall.facility_id == facility_id))
    if not record:
        raise HTTPException(status_code=404, detail="Recall not found")
    affected = (await session.execute(select(RecallAffectedStock).where(RecallAffectedStock.recall_id == record.id).order_by(RecallAffectedStock.pharmacy_location_id))).scalars().all()
    return {**RecallRead.model_validate(record).model_dump(), "affected_stock": affected}


@recall_router.post("", response_model=RecallRead, status_code=status.HTTP_201_CREATED)
async def post_recall(payload: RecallCreate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_CREATE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, create_recall(session, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


@recall_router.post("/{recall_id}/approve", response_model=RecallRead)
async def post_recall_approve(recall_id: UUID, payload: IdempotentAction, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_APPROVE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, approve_recall(session, recall_id=recall_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=payload.idempotency_key, current_user=current_user))


@recall_router.post("/{recall_id}/resolve", response_model=RecallRead)
async def post_recall_resolve(recall_id: UUID, payload: RecallResolve, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_RESOLVE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, resolve_recall(session, recall_id=recall_id, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


@recall_router.post("/{recall_id}/notification-status", response_model=RecallRead)
async def post_recall_notification(recall_id: UUID, payload: RecallNotificationUpdate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_NOTIFICATION")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, update_recall_notification(session, recall_id=recall_id, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


@recall_router.get("/{recall_id}/affected-dispensings", response_model=list[AffectedDispensingRead])
async def get_affected_dispensings(recall_id: UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_RECALL_VIEW")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    try:
        return await affected_dispensings(session, recall_id=recall_id, tenant_id=tenant_id, facility_id=facility_id)
    except P32NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@transfer_router.get("/eligible-batches", response_model=list[EligibleTransferBatch])
async def eligible_batches(source_location_id: UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_VIEW")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return (await session.execute(select(InventoryBatch).where(
        InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id,
        InventoryBatch.pharmacy_location_id == source_location_id, InventoryBatch.status == "ACTIVE",
        InventoryBatch.available_quantity > InventoryBatch.reserved_quantity,
    ).order_by(InventoryBatch.expiry_date.asc().nulls_last(), InventoryBatch.id))).scalars().all()


@transfer_router.get("", response_model=list[TransferRead])
async def list_transfers(location_id: UUID | None = Query(default=None), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_VIEW")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    stmt = select(StockTransfer).where(StockTransfer.tenant_id == tenant_id, StockTransfer.facility_id == facility_id)
    if location_id:
        stmt = stmt.where((StockTransfer.from_location_id == location_id) | (StockTransfer.to_location_id == location_id))
    return (await session.execute(stmt.order_by(StockTransfer.created_at.desc()))).scalars().all()


@transfer_router.get("/{transfer_id}", response_model=TransferDetail)
async def get_transfer(transfer_id: UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_VIEW")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    record = await session.scalar(select(StockTransfer).where(StockTransfer.id == transfer_id, StockTransfer.tenant_id == tenant_id, StockTransfer.facility_id == facility_id))
    if not record:
        raise HTTPException(status_code=404, detail="Stock transfer not found")
    items = (await session.execute(select(StockTransferItem).where(StockTransferItem.transfer_id == record.id).order_by(StockTransferItem.id))).scalars().all()
    discrepancies = (await session.execute(select(StockTransferDiscrepancy).where(StockTransferDiscrepancy.transfer_id == record.id).order_by(StockTransferDiscrepancy.created_at))).scalars().all()
    return {**TransferRead.model_validate(record).model_dump(), "items": items, "discrepancies": discrepancies}


@transfer_router.post("", response_model=TransferRead, status_code=status.HTTP_201_CREATED)
async def post_transfer(payload: TransferCreate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_CREATE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, create_transfer(session, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


@transfer_router.post("/{transfer_id}/approve", response_model=TransferRead)
async def post_transfer_approve(transfer_id: UUID, payload: IdempotentAction, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_APPROVE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, approve_transfer(session, transfer_id=transfer_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=payload.idempotency_key, current_user=current_user))


@transfer_router.post("/{transfer_id}/dispatch", response_model=TransferRead)
async def post_transfer_dispatch(transfer_id: UUID, payload: IdempotentAction, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_DISPATCH")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, dispatch_transfer(session, transfer_id=transfer_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=payload.idempotency_key, current_user=current_user))


@transfer_router.post("/{transfer_id}/receive", response_model=TransferRead)
async def post_transfer_receive(transfer_id: UUID, payload: TransferReceive, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_RECEIVE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, receive_transfer(session, transfer_id=transfer_id, tenant_id=tenant_id, facility_id=facility_id, payload=payload, current_user=current_user))


@transfer_router.post("/{transfer_id}/cancel", response_model=TransferRead)
async def post_transfer_cancel(transfer_id: UUID, payload: IdempotentAction, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_APPROVE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, cancel_transfer(session, transfer_id=transfer_id, tenant_id=tenant_id, facility_id=facility_id, idempotency_key=payload.idempotency_key, current_user=current_user))


@transfer_router.post("/discrepancies/{discrepancy_id}/reconcile", response_model=TransferDiscrepancyRead)
async def post_reconcile(discrepancy_id: UUID, payload: DiscrepancyReconcile, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_TRANSFER_RECONCILE")), tenant_id: UUID = Depends(get_tenant_id_from_token), facility_id: UUID = Depends(get_facility_id)):
    return await _commit(session, reconcile_discrepancy(session, discrepancy_id=discrepancy_id, tenant_id=tenant_id, facility_id=facility_id, action=payload.action, notes=payload.notes, idempotency_key=payload.idempotency_key, current_user=current_user))