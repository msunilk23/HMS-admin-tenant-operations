from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import (
    CountDetail, CountRecount, CountRecountDetail, InventoryBatch, PharmacyLocation,
    StockCount, StockCountOperation, StockCountSettings,
)
from app.schemas.p33 import CountCreate
from app.services.audit_service import record_audit
from app.services.stock_ledger_service import create_stock_ledger_transaction


class P33NotFoundError(Exception):
    pass


class P33ConflictError(Exception):
    def __init__(self, message: str, *, audit_event: dict | None = None):
        super().__init__(message)
        self.audit_event = audit_event


class P33ValidationError(Exception):
    pass


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _actor(current_user: dict) -> UUID:
    return UUID(str(current_user["sub"]))


def _hash(payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _count_snapshot(count: StockCount) -> dict:
    fields = (
        "id", "tenant_id", "facility_id", "pharmacy_location_id", "status", "count_type",
        "reference_key", "selected_batch_ids", "notes", "quantity_tolerance_percent",
        "repeated_variance_lookback_days", "repeated_variance_trigger", "high_value_variance_threshold",
        "expected_total_quantity", "physical_total_quantity", "variance_quantity", "total_items_counted",
        "total_variance_items", "recount_count", "initiated_by", "initiated_at", "started_by", "started_at",
        "completed_by", "completed_at", "approved_by", "approved_at", "applied_by", "applied_at",
        "cancelled_by", "cancelled_at", "cancellation_reason", "created_at", "updated_at",
    )
    result = {}
    for field in fields:
        value = getattr(count, field)
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        result[field] = value
    return result


def _detail_snapshot(detail: CountDetail) -> dict:
    fields = (
        "id", "count_id", "inventory_batch_id", "medicine_id", "batch_number", "system_quantity",
        "available_quantity", "reserved_quantity", "unit_cost", "physical_quantity", "variance_quantity",
        "variance_percent", "variance_value", "classifications", "variance_reason", "is_unexpected",
        "evidence", "counted_by", "counted_at", "version", "adjustment_ledger_id",
    )
    result = {}
    for field in fields:
        value = getattr(detail, field)
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        result[field] = value
    return result


async def _serialize_key(session: AsyncSession, tenant_id: UUID, actor: UUID, action: str, key: str) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        lock_key = f"p33:{tenant_id}:{actor}:{action}:{key}"
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 33))"), {"key": lock_key})


async def _replay(
    session: AsyncSession, *, tenant_id: UUID, actor: UUID, action: str,
    scope: str, key: str, request_hash: str,
) -> dict | None:
    await _serialize_key(session, tenant_id, actor, action, key)
    operation = await session.scalar(select(StockCountOperation).where(
        StockCountOperation.tenant_id == tenant_id,
        StockCountOperation.user_id == actor,
        StockCountOperation.action == action,
        StockCountOperation.scope_resource == scope,
        StockCountOperation.idempotency_key == key,
    ).with_for_update())
    if operation is None:
        return None
    if operation.request_hash != request_hash:
        raise P33ConflictError("Idempotency key was already used with a different payload")
    return operation.response_payload


async def _store_operation(
    session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, actor: UUID,
    action: str, scope: str, key: str, request_hash: str, count_id: UUID, response: dict,
) -> None:
    session.add(StockCountOperation(
        tenant_id=tenant_id, facility_id=facility_id, user_id=actor, action=action,
        scope_resource=scope, idempotency_key=key, request_hash=request_hash,
        count_id=count_id, response_payload=response,
    ))
    await session.flush()


async def _locked_count(session: AsyncSession, count_id: UUID, tenant_id: UUID, facility_id: UUID) -> StockCount:
    count = await session.scalar(select(StockCount).where(
        StockCount.id == count_id, StockCount.tenant_id == tenant_id, StockCount.facility_id == facility_id,
    ).with_for_update())
    if count is None:
        raise P33NotFoundError("Inventory count not found")
    return count


async def create_count(
    session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, payload: CountCreate,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash(payload)
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="INITIATE", scope="new", key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    location = await session.scalar(select(PharmacyLocation).where(
        PharmacyLocation.id == payload.pharmacy_location_id,
        PharmacyLocation.tenant_id == tenant_id,
        PharmacyLocation.facility_id == facility_id,
        PharmacyLocation.active.is_(True),
    ))
    if location is None:
        raise P33NotFoundError("Pharmacy location not found")
    if payload.selected_batch_ids:
        selected = (await session.execute(select(InventoryBatch.id).where(
            InventoryBatch.id.in_(payload.selected_batch_ids), InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == payload.pharmacy_location_id,
        ))).scalars().all()
        if set(selected) != set(payload.selected_batch_ids):
            raise P33ValidationError("Every selected batch must belong to the authenticated facility and location")
    settings = await session.scalar(select(StockCountSettings).where(
        StockCountSettings.tenant_id == tenant_id, StockCountSettings.facility_id == facility_id,
    ))
    count = StockCount(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=payload.pharmacy_location_id,
        status="CREATED", count_type=payload.count_type, reference_key=f"SC-{uuid.uuid4().hex[:12]}".upper(),
        selected_batch_ids=[str(item) for item in payload.selected_batch_ids], notes=payload.notes,
        quantity_tolerance_percent=settings.quantity_tolerance_percent if settings else Decimal("0.5"),
        repeated_variance_lookback_days=settings.repeated_variance_lookback_days if settings else 90,
        repeated_variance_trigger=settings.repeated_variance_trigger if settings else 2,
        high_value_variance_threshold=settings.high_value_variance_threshold if settings else Decimal("5000"),
        initiated_by=actor,
    )
    session.add(count)
    await session.flush()
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="INITIATE", scope="new", key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="INITIATE", resource_type="stock_count", resource_id=count.id, new_value=response)
    return response


async def start_count(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="START", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status != "CREATED":
        raise P33ConflictError("Only CREATED counts can be started")
    query = select(InventoryBatch).where(
        InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id,
        InventoryBatch.pharmacy_location_id == count.pharmacy_location_id, InventoryBatch.status == "ACTIVE",
    )
    if count.count_type != "FULL":
        query = query.where(InventoryBatch.id.in_([UUID(value) for value in count.selected_batch_ids]))
    batches = (await session.execute(query.order_by(InventoryBatch.id).with_for_update())).scalars().all()
    if not batches:
        raise P33ValidationError("The count scope contains no active inventory batches")
    if count.count_type != "FULL" and len(batches) != len(count.selected_batch_ids):
        raise P33ConflictError("A selected batch is no longer active in this location")
    if any(batch.frozen_by_count_id not in {None, count.id} for batch in batches):
        raise P33ConflictError("An inventory batch is already frozen by another count")
    now = datetime.now(timezone.utc)
    expected = Decimal("0")
    for batch in batches:
        available = _decimal(batch.available_quantity)
        reserved = _decimal(batch.reserved_quantity)
        system = available + reserved
        session.add(CountDetail(
            count_id=count.id, inventory_batch_id=batch.id, medicine_id=batch.medicine_id,
            batch_number=batch.batch_number, system_quantity=system, available_quantity=available,
            reserved_quantity=reserved, unit_cost=batch.purchase_rate, classifications=[],
        ))
        batch.frozen_by_count_id = count.id
        batch.frozen_at = now
        expected += system
    count.status = "IN_PROGRESS"
    count.started_by = actor
    count.started_at = now
    count.expected_total_quantity = expected
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="START", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="START", resource_type="stock_count", resource_id=count.id, old_value={"status": "CREATED"}, new_value={"status": "IN_PROGRESS", "batch_count": len(batches)})
    return response


async def _is_repeated(session: AsyncSession, count: StockCount, detail: CountDetail) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=count.repeated_variance_lookback_days)
    prior = await session.scalar(select(func.count()).select_from(CountDetail).join(StockCount, StockCount.id == CountDetail.count_id).where(
        StockCount.tenant_id == count.tenant_id, StockCount.facility_id == count.facility_id,
        StockCount.status == "APPLIED", StockCount.applied_at >= cutoff,
        CountDetail.medicine_id == detail.medicine_id, CountDetail.batch_number == detail.batch_number,
        CountDetail.variance_quantity.is_not(None), CountDetail.variance_quantity != 0,
    ))
    return int(prior or 0) >= count.repeated_variance_trigger


async def _classify(session: AsyncSession, count: StockCount, detail: CountDetail, physical: Decimal) -> None:
    system = _decimal(detail.system_quantity)
    variance = physical - system
    percent = Decimal("0") if system == 0 else abs(variance) / system * Decimal("100")
    flags: list[str] = []
    if variance == 0:
        flags.append("ZERO")
    elif system == 0:
        flags.append("UNEXPECTED_STOCK")
    elif percent <= _decimal(count.quantity_tolerance_percent):
        flags.append("WITHIN_TOLERANCE")
    else:
        flags.append("OUTSIDE_TOLERANCE")
    value = abs(variance) * _decimal(detail.unit_cost) if detail.unit_cost is not None else None
    if value is not None and value >= _decimal(count.high_value_variance_threshold) and variance != 0:
        flags.append("HIGH_VALUE")
    if variance != 0 and await _is_repeated(session, count, detail):
        flags.append("REPEATED")
    detail.variance_quantity = variance
    detail.variance_percent = percent
    detail.variance_value = value
    detail.classifications = flags


async def record_detail(
    session: AsyncSession, *, count_id: UUID, detail_id: UUID, tenant_id: UUID, facility_id: UUID,
    physical_quantity: Decimal, version: int, variance_reason: str | None, evidence: str | None,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request = {"detail_id": detail_id, "physical_quantity": physical_quantity, "version": version, "variance_reason": variance_reason, "evidence": evidence}
    request_hash = _hash(request)
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="RECORD", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status != "IN_PROGRESS":
        raise P33ConflictError("Physical quantities can only be recorded while a count is IN_PROGRESS")
    detail = await session.scalar(select(CountDetail).where(CountDetail.id == detail_id, CountDetail.count_id == count.id).with_for_update())
    if detail is None:
        raise P33NotFoundError("Count detail not found")
    if detail.version != version:
        raise P33ConflictError("Count detail version conflict")
    detail.physical_quantity = physical_quantity
    detail.variance_reason = variance_reason
    detail.evidence = evidence
    detail.counted_by = actor
    detail.counted_at = datetime.now(timezone.utc)
    detail.version += 1
    await _classify(session, count, detail, physical_quantity)
    await session.flush()
    response = _detail_snapshot(detail)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="RECORD", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="RECORD", resource_type="count_detail", resource_id=detail.id, new_value=response)
    return response


async def add_unexpected_stock(
    session: AsyncSession, *, count_id: UUID, inventory_batch_id: UUID, tenant_id: UUID,
    facility_id: UUID, physical_quantity: Decimal, evidence: str, variance_reason: str | None,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request = {"inventory_batch_id": inventory_batch_id, "physical_quantity": physical_quantity, "evidence": evidence, "variance_reason": variance_reason}
    request_hash = _hash(request)
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="ADD_UNEXPECTED", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status != "IN_PROGRESS":
        raise P33ConflictError("Unexpected stock can only be added while a count is IN_PROGRESS")
    existing = await session.scalar(select(CountDetail.id).where(CountDetail.count_id == count.id, CountDetail.inventory_batch_id == inventory_batch_id))
    if existing is not None:
        raise P33ConflictError("This batch is already in the count scope")
    batch = await session.scalar(select(InventoryBatch).where(
        InventoryBatch.id == inventory_batch_id, InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id, InventoryBatch.pharmacy_location_id == count.pharmacy_location_id,
    ).with_for_update())
    if batch is None:
        raise P33NotFoundError("Unexpected inventory batch not found")
    if _decimal(batch.available_quantity) + _decimal(batch.reserved_quantity) != 0:
        raise P33ValidationError("Unexpected stock must have a zero system quantity")
    if batch.frozen_by_count_id not in {None, count.id}:
        raise P33ConflictError("The unexpected batch is frozen by another count")
    now = datetime.now(timezone.utc)
    batch.frozen_by_count_id = count.id
    batch.frozen_at = now
    detail = CountDetail(
        count_id=count.id, inventory_batch_id=batch.id, medicine_id=batch.medicine_id,
        batch_number=batch.batch_number, system_quantity=Decimal("0"), available_quantity=Decimal("0"),
        reserved_quantity=Decimal("0"), unit_cost=batch.purchase_rate, physical_quantity=physical_quantity,
        variance_reason=variance_reason, evidence=evidence, is_unexpected=True, counted_by=actor, counted_at=now,
    )
    session.add(detail)
    await session.flush()
    await _classify(session, count, detail, physical_quantity)
    await session.flush()
    response = _detail_snapshot(detail)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="ADD_UNEXPECTED", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="ADD_UNEXPECTED", resource_type="count_detail", resource_id=detail.id, new_value=response, reason=variance_reason)
    return response


async def _details(session: AsyncSession, count_id: UUID, lock: bool = False) -> list[CountDetail]:
    query = select(CountDetail).where(CountDetail.count_id == count_id).order_by(CountDetail.batch_number, CountDetail.id)
    if lock:
        query = query.with_for_update()
    return list((await session.execute(query)).scalars().all())


async def _latest_recount(session: AsyncSession, count_id: UUID, lock: bool = False) -> CountRecount | None:
    query = select(CountRecount).where(CountRecount.count_id == count_id).order_by(CountRecount.attempt_number.desc()).limit(1)
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


async def _effective_quantities(session: AsyncSession, count: StockCount, details: list[CountDetail]) -> dict[UUID, Decimal]:
    recount = await _latest_recount(session, count.id)
    if recount is None or recount.status != "SUBMITTED":
        return {detail.id: _decimal(detail.physical_quantity) for detail in details}
    values = (await session.execute(select(CountRecountDetail).where(CountRecountDetail.recount_id == recount.id))).scalars().all()
    return {value.count_detail_id: _decimal(value.physical_quantity) for value in values}


async def submit_count(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="SUBMIT", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status != "IN_PROGRESS":
        raise P33ConflictError("Only IN_PROGRESS counts can be submitted")
    details = await _details(session, count.id, lock=True)
    if not details or any(detail.physical_quantity is None for detail in details):
        raise P33ValidationError("Every count detail requires a physical quantity")
    count.status = "SUBMITTED"
    count.completed_by = actor
    count.completed_at = datetime.now(timezone.utc)
    count.total_items_counted = len(details)
    count.physical_total_quantity = sum((_decimal(detail.physical_quantity) for detail in details), Decimal("0"))
    count.variance_quantity = sum((_decimal(detail.variance_quantity) for detail in details), Decimal("0"))
    count.total_variance_items = sum(detail.variance_quantity != 0 for detail in details)
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="SUBMIT", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="SUBMIT", resource_type="stock_count", resource_id=count.id, old_value={"status": "IN_PROGRESS"}, new_value={"status": "SUBMITTED", "variance_quantity": count.variance_quantity})
    return response


async def request_recount(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID, reason: str,
    assigned_to: UUID, idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request = {"count_id": count_id, "reason": reason, "assigned_to": assigned_to}
    request_hash = _hash(request)
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="REQUEST_RECOUNT", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status not in {"SUBMITTED", "RESUBMITTED"}:
        raise P33ConflictError("Recount can only be requested for SUBMITTED or RESUBMITTED counts")
    if count.recount_count >= 2:
        raise P33ConflictError("Maximum of two recounts has been reached")
    details = await _details(session, count.id, lock=True)
    original_counters = {detail.counted_by for detail in details if detail.counted_by is not None}
    if assigned_to in original_counters:
        raise P33ValidationError("Recount assignee must differ from the original counter")
    recount = CountRecount(
        count_id=count.id, attempt_number=count.recount_count + 1, status="ASSIGNED",
        reason=reason, assigned_to=assigned_to, requested_by=actor,
    )
    session.add(recount)
    await session.flush()
    for detail in details:
        session.add(CountRecountDetail(recount_id=recount.id, count_detail_id=detail.id))
    count.recount_count += 1
    count.status = "RECOUNT_REQUIRED"
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="REQUEST_RECOUNT", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="REQUEST_RECOUNT", resource_type="stock_count", resource_id=count.id, new_value={"status": count.status, "attempt": recount.attempt_number, "assigned_to": assigned_to}, reason=reason)
    return response


async def start_recount(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="START_RECOUNT", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    recount = await _latest_recount(session, count.id, lock=True)
    if count.status != "RECOUNT_REQUIRED" or recount is None or recount.status != "ASSIGNED":
        raise P33ConflictError("No assigned recount can be started")
    if recount.assigned_to != actor:
        raise P33ConflictError("Only the assigned user can start this recount")
    recount.status = "IN_PROGRESS"
    recount.started_at = datetime.now(timezone.utc)
    count.status = "RECOUNT_IN_PROGRESS"
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="START_RECOUNT", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="START_RECOUNT", resource_type="stock_count", resource_id=count.id, new_value={"status": count.status, "attempt": recount.attempt_number})
    return response


async def record_recount_detail(
    session: AsyncSession, *, count_id: UUID, detail_id: UUID, tenant_id: UUID, facility_id: UUID,
    physical_quantity: Decimal, version: int, variance_reason: str | None,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request = {"detail_id": detail_id, "physical_quantity": physical_quantity, "version": version, "variance_reason": variance_reason}
    request_hash = _hash(request)
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="RECOUNT_RECORD", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    recount = await _latest_recount(session, count.id, lock=True)
    if count.status != "RECOUNT_IN_PROGRESS" or recount is None or recount.assigned_to != actor:
        raise P33ConflictError("Only the assigned user can record the active recount")
    value = await session.scalar(select(CountRecountDetail).where(
        CountRecountDetail.recount_id == recount.id, CountRecountDetail.count_detail_id == detail_id,
    ).with_for_update())
    if value is None:
        raise P33NotFoundError("Recount detail not found")
    if value.version != version:
        raise P33ConflictError("Recount detail version conflict")
    detail = await session.get(CountDetail, detail_id)
    value.physical_quantity = physical_quantity
    value.variance_quantity = physical_quantity - _decimal(detail.system_quantity)
    value.variance_reason = variance_reason
    value.counted_by = actor
    value.counted_at = datetime.now(timezone.utc)
    value.version += 1
    await session.flush()
    response = {
        "id": str(value.id), "recount_id": str(value.recount_id), "count_detail_id": str(value.count_detail_id),
        "physical_quantity": str(value.physical_quantity), "variance_quantity": str(value.variance_quantity),
        "variance_reason": value.variance_reason, "counted_by": str(value.counted_by),
        "counted_at": value.counted_at.isoformat(), "version": value.version,
    }
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="RECOUNT_RECORD", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="RECOUNT_RECORD", resource_type="count_recount_detail", resource_id=value.id, new_value=response)
    return response


async def resubmit_recount(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="RESUBMIT", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    recount = await _latest_recount(session, count.id, lock=True)
    if count.status != "RECOUNT_IN_PROGRESS" or recount is None or recount.assigned_to != actor:
        raise P33ConflictError("Only the assigned user can resubmit the active recount")
    values = list((await session.execute(select(CountRecountDetail).where(CountRecountDetail.recount_id == recount.id).with_for_update())).scalars().all())
    if not values or any(value.physical_quantity is None for value in values):
        raise P33ValidationError("Every recount detail requires a physical quantity")
    await _details(session, count.id, lock=True)
    recount.status = "SUBMITTED"
    recount.submitted_at = datetime.now(timezone.utc)
    count.status = "RESUBMITTED"
    count.completed_by = actor
    count.completed_at = recount.submitted_at
    count.physical_total_quantity = sum((_decimal(value.physical_quantity) for value in values), Decimal("0"))
    count.variance_quantity = sum((_decimal(value.variance_quantity) for value in values), Decimal("0"))
    count.total_variance_items = sum(value.variance_quantity != 0 for value in values)
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="RESUBMIT", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="RESUBMIT", resource_type="stock_count", resource_id=count.id, new_value={"status": count.status, "attempt": recount.attempt_number})
    return response


async def _validate_snapshot(session: AsyncSession, count: StockCount, details: list[CountDetail], current_user: dict, action: str) -> dict[UUID, InventoryBatch]:
    batches = list((await session.execute(select(InventoryBatch).where(
        InventoryBatch.id.in_([detail.inventory_batch_id for detail in details]),
        InventoryBatch.tenant_id == count.tenant_id, InventoryBatch.facility_id == count.facility_id,
    ).order_by(InventoryBatch.id).with_for_update())).scalars().all())
    by_id = {batch.id: batch for batch in batches}
    drift = []
    for detail in details:
        batch = by_id.get(detail.inventory_batch_id)
        if batch is None or batch.frozen_by_count_id != count.id or _decimal(batch.available_quantity) != _decimal(detail.available_quantity) or _decimal(batch.reserved_quantity) != _decimal(detail.reserved_quantity):
            drift.append(str(detail.inventory_batch_id))
    if drift:
        raise P33ConflictError("Inventory balances drifted from the count snapshot", audit_event={
            "current_user": current_user, "action": "SNAPSHOT_DRIFT", "resource_type": "stock_count",
            "resource_id": count.id, "new_value": {"during": action, "inventory_batch_ids": drift},
        })
    return by_id


async def approve_count(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID,
    reason: str | None, idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id, "reason": reason})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="APPROVE", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status not in {"SUBMITTED", "RESUBMITTED"}:
        raise P33ConflictError("Only submitted counts can be approved")
    details = await _details(session, count.id, lock=True)
    disallowed = {count.initiated_by, count.completed_by} | {detail.counted_by for detail in details}
    recounts = list((await session.execute(select(CountRecount).where(CountRecount.count_id == count.id))).scalars().all())
    recount_values = list((await session.execute(select(CountRecountDetail).join(CountRecount).where(CountRecount.count_id == count.id))).scalars().all())
    disallowed |= {recount.assigned_to for recount in recounts} | {value.counted_by for value in recount_values}
    if actor in disallowed:
        raise P33ConflictError("Maker-checker separation prevents this user from approving the count")
    if any(detail.unit_cost is None for detail in details):
        raise P33ValidationError("Missing acquisition cost blocks approval")
    await _validate_snapshot(session, count, details, current_user, "APPROVE")
    count.status = "APPROVED"
    count.approved_by = actor
    count.approved_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="APPROVE", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="APPROVE", resource_type="stock_count", resource_id=count.id, old_value={"status": "SUBMITTED"}, new_value={"status": "APPROVED"}, reason=reason)
    return response


async def apply_count(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID,
    reason: str | None, idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id, "reason": reason})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="APPLY", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    if count.status != "APPROVED":
        raise P33ConflictError("Only APPROVED counts can be applied")
    recounts = list((await session.execute(select(CountRecount).where(CountRecount.count_id == count.id))).scalars().all())
    if actor in {recount.assigned_to for recount in recounts}:
        raise P33ConflictError("A recount participant cannot apply this count")
    details = await _details(session, count.id, lock=True)
    batches = await _validate_snapshot(session, count, details, current_user, "APPLY")
    effective = await _effective_quantities(session, count, details)
    for detail in details:
        physical = effective[detail.id]
        if physical < _decimal(detail.reserved_quantity):
            raise P33ConflictError("Adjustment would reduce physical stock below reserved quantity")
        variance = physical - _decimal(detail.system_quantity)
        if variance == 0:
            continue
        batch = batches[detail.inventory_batch_id]
        ledger = await create_stock_ledger_transaction(
            session, tenant_id=tenant_id, facility_id=facility_id,
            pharmacy_location_id=batch.pharmacy_location_id, medicine_id=batch.medicine_id,
            inventory_batch_id=batch.id, transaction_type="ADJUSTMENT_IN" if variance > 0 else "ADJUSTMENT_OUT",
            quantity=variance, reference_type="STOCK_COUNT_DETAIL", reference_id=detail.id,
            correlation_reference=count.reference_key, reason=reason or f"Stock count {count.reference_key}",
            user_id=actor, allowed_count_id=count.id,
        )
        detail.adjustment_ledger_id = ledger.id
        if detail.is_unexpected and variance > 0:
            batch.status = "ACTIVE"
    now = datetime.now(timezone.utc)
    for batch in batches.values():
        batch.frozen_by_count_id = None
        batch.frozen_at = None
    count.status = "APPLIED"
    count.applied_by = actor
    count.applied_at = now
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="APPLY", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="APPLY", resource_type="stock_count", resource_id=count.id, old_value={"status": "APPROVED"}, new_value={"status": "APPLIED"}, reason=reason)
    return response


async def cancel_count(
    session: AsyncSession, *, count_id: UUID, tenant_id: UUID, facility_id: UUID, reason: str,
    idempotency_key: str, current_user: dict,
) -> dict:
    actor = _actor(current_user)
    request_hash = _hash({"count_id": count_id, "reason": reason})
    replay = await _replay(session, tenant_id=tenant_id, actor=actor, action="CANCEL", scope=str(count_id), key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    count = await _locked_count(session, count_id, tenant_id, facility_id)
    allowed = {"CREATED", "IN_PROGRESS", "SUBMITTED", "RECOUNT_REQUIRED", "RECOUNT_IN_PROGRESS", "RESUBMITTED"}
    if count.status not in allowed:
        raise P33ConflictError("This count can no longer be cancelled")
    if current_user.get("role") == "pharmacist" and count.status not in {"CREATED", "IN_PROGRESS"}:
        raise P33ConflictError("Pharmacists can only cancel before submission")
    batches = list((await session.execute(select(InventoryBatch).where(InventoryBatch.frozen_by_count_id == count.id).with_for_update())).scalars().all())
    for batch in batches:
        batch.frozen_by_count_id = None
        batch.frozen_at = None
    count.status = "CANCELLED"
    count.cancelled_by = actor
    count.cancelled_at = datetime.now(timezone.utc)
    count.cancellation_reason = reason
    await session.flush()
    await session.refresh(count)
    response = _count_snapshot(count)
    await _store_operation(session, tenant_id=tenant_id, facility_id=facility_id, actor=actor, action="CANCEL", scope=str(count.id), key=idempotency_key, request_hash=request_hash, count_id=count.id, response=response)
    record_audit(session, current_user=current_user, action="CANCEL", resource_type="stock_count", resource_id=count.id, new_value={"status": "CANCELLED"}, reason=reason)
    return response