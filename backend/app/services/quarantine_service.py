import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import InventoryBatch, StockQuarantine
from app.schemas.quarantine import StockQuarantineCreate, StockQuarantineDispose
from app.services.audit_service import record_audit
from app.services.stock_ledger_service import create_stock_ledger_transaction


class QuarantineNotFoundError(ValueError):
    pass


def _snapshot(record: StockQuarantine) -> dict:
    return {
        "status": record.status,
        "reason": record.reason,
        "quantity": record.total_quantity_quarantined,
        "remaining_quantity": record.remaining_quantity,
        "inventory_batch_id": record.inventory_batch_id,
        "approved_action": record.approved_action,
    }


async def create_quarantine(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    facility_id: UUID,
    payload: StockQuarantineCreate,
    current_user: dict,
) -> StockQuarantine:
    request_hash = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = await session.scalar(
        select(StockQuarantine).where(
            StockQuarantine.tenant_id == tenant_id,
            StockQuarantine.idempotency_key == payload.idempotency_key,
        ).with_for_update()
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("Idempotency key was already used with a different request")
        return existing

    batch = await session.scalar(
        select(InventoryBatch).where(
            InventoryBatch.id == payload.inventory_batch_id,
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
        ).with_for_update()
    )
    if batch is None:
        raise QuarantineNotFoundError("Inventory batch not found")
    if payload.quantity > Decimal(str(batch.available_quantity)):
        raise ValueError("Quarantine quantity exceeds saleable batch quantity")
    if payload.reason == "EXPIRED" and (batch.expiry_date is None or batch.expiry_date > date.today()):
        raise ValueError("Only expired batches may use the EXPIRED reason")

    user_id = UUID(str(current_user["sub"]))
    record = StockQuarantine(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=batch.pharmacy_location_id,
        inventory_batch_id=batch.id,
        status="QUARANTINED",
        reference_key=f"QT-{uuid.uuid4().hex[:12]}".upper(),
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        reason=payload.reason,
        total_quantity_quarantined=payload.quantity,
        remaining_quantity=payload.quantity,
        notes=payload.notes,
        quarantined_by=user_id,
    )
    session.add(record)
    await session.flush()
    ledger = await create_stock_ledger_transaction(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=batch.pharmacy_location_id,
        medicine_id=batch.medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="QUARANTINE_OUT",
        quantity=-payload.quantity,
        reference_type="STOCK_QUARANTINE",
        reference_id=record.id,
        reason=payload.reason,
        user_id=user_id,
    )
    record.quarantine_ledger_transaction_id = ledger.id
    record_audit(
        session,
        current_user=current_user,
        action="QUARANTINE",
        resource_type="stock_quarantine",
        resource_id=record.id,
        new_value=_snapshot(record),
        reason=payload.notes or payload.reason,
    )
    await session.flush()
    return record


async def release_quarantine(
    session: AsyncSession,
    *,
    quarantine_id: UUID,
    tenant_id: UUID,
    facility_id: UUID,
    release_reason: str,
    current_user: dict,
) -> StockQuarantine:
    record = await _locked_quarantine(session, quarantine_id, tenant_id, facility_id)
    if record.status != "QUARANTINED":
        raise ValueError("Only quarantined stock may be released")
    if record.reason != "INVESTIGATION":
        raise ValueError("Expired or damaged stock can never return to saleable inventory")
    user_id = UUID(str(current_user["sub"]))
    if record.quarantined_by == user_id:
        raise ValueError("Initiator cannot approve their own quarantine release")
    batch = await session.scalar(select(InventoryBatch).where(InventoryBatch.id == record.inventory_batch_id).with_for_update())
    if batch is None:
        raise ValueError("Inventory batch not found")
    if batch.expiry_date is not None and batch.expiry_date <= date.today():
        raise ValueError("Expired stock can never return to saleable inventory")

    old_value = _snapshot(record)
    ledger = await create_stock_ledger_transaction(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=record.pharmacy_location_id,
        medicine_id=batch.medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="QUARANTINE_RELEASE",
        quantity=record.total_quantity_quarantined,
        reference_type="STOCK_QUARANTINE",
        reference_id=record.id,
        reason=release_reason,
        user_id=user_id,
    )
    now = datetime.now(timezone.utc)
    record.status = "RELEASED"
    record.release_reason = release_reason
    record.released_by = user_id
    record.released_at = now
    record.approved_by = user_id
    record.approved_at = now
    record.approved_action = "RELEASE"
    record.release_ledger_transaction_id = ledger.id
    record.remaining_quantity = Decimal("0")
    record_audit(session, current_user=current_user, action="RELEASE", resource_type="stock_quarantine", resource_id=record.id, old_value=old_value, new_value=_snapshot(record), reason=release_reason)
    await session.flush()
    return record


async def dispose_quarantine(
    session: AsyncSession,
    *,
    quarantine_id: UUID,
    tenant_id: UUID,
    facility_id: UUID,
    payload: StockQuarantineDispose,
    current_user: dict,
) -> StockQuarantine:
    record = await _locked_quarantine(session, quarantine_id, tenant_id, facility_id)
    if record.status != "QUARANTINED":
        raise ValueError("Disposal is allowed only from quarantine")
    if payload.disposal_date > date.today():
        raise ValueError("Disposal date cannot be in the future")
    user_id = UUID(str(current_user["sub"]))
    if record.quarantined_by == user_id:
        raise ValueError("Initiator cannot approve their own disposal")
    batch = await session.scalar(select(InventoryBatch).where(InventoryBatch.id == record.inventory_batch_id).with_for_update())
    if batch is None:
        raise ValueError("Inventory batch not found")

    old_value = _snapshot(record)
    ledger = await create_stock_ledger_transaction(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=record.pharmacy_location_id,
        medicine_id=batch.medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="QUARANTINE_DISPOSAL",
        quantity=-record.remaining_quantity,
        reference_type="STOCK_QUARANTINE",
        reference_id=record.id,
        reason=payload.disposal_reason,
        user_id=user_id,
        affects_available_balance=False,
    )
    now = datetime.now(timezone.utc)
    record.status = "DISPOSED"
    record.disposal_reason = payload.disposal_reason
    record.disposal_method = payload.disposal_method
    record.disposal_date = payload.disposal_date
    record.witnessed_by = payload.witnessed_by
    record.disposed_by = user_id
    record.disposed_at = now
    record.approved_by = user_id
    record.approved_at = now
    record.approved_action = "DISPOSE"
    record.disposal_ledger_transaction_id = ledger.id
    record.remaining_quantity = Decimal("0")
    record_audit(session, current_user=current_user, action="DISPOSE", resource_type="stock_quarantine", resource_id=record.id, old_value=old_value, new_value=_snapshot(record), reason=payload.disposal_reason)
    await session.flush()
    return record


async def _locked_quarantine(session: AsyncSession, quarantine_id: UUID, tenant_id: UUID, facility_id: UUID) -> StockQuarantine:
    record = await session.scalar(
        select(StockQuarantine).where(
            StockQuarantine.id == quarantine_id,
            StockQuarantine.tenant_id == tenant_id,
            StockQuarantine.facility_id == facility_id,
        ).with_for_update()
    )
    if record is None:
        raise QuarantineNotFoundError("Quarantine record not found")
    return record