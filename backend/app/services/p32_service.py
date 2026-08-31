import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import (
    InventoryBatch,
    Patient,
    PharmacyDispense,
    PharmacyDispenseAllocation,
    PharmacyDispenseItem,
    PharmacyStockReservation,
    PharmacyWorkflowOperation,
    ProductRecall,
    RecallAffectedStock,
    StockQuarantine,
    StockTransfer,
    StockTransferDiscrepancy,
    StockTransferItem,
)
from app.schemas.p32 import RecallCreate, RecallNotificationUpdate, RecallResolve, TransferCreate, TransferReceive
from app.services.audit_service import record_audit
from app.services.stock_ledger_service import create_stock_ledger_transaction


class P32NotFoundError(ValueError):
    pass


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _user_id(current_user: dict) -> UUID:
    return UUID(str(current_user["sub"]))


def _audit(session, current_user, action: str, resource_type: str, resource_id: UUID, old_value=None, new_value=None, reason=None):
    record_audit(session, current_user=current_user, action=action, resource_type=resource_type, resource_id=resource_id, old_value=old_value, new_value=new_value, reason=reason)


async def _operation(session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, key: str, request_hash: str, operation_type: str, resource_id: UUID) -> bool:
    existing = await session.scalar(select(PharmacyWorkflowOperation).where(
        PharmacyWorkflowOperation.tenant_id == tenant_id,
        PharmacyWorkflowOperation.idempotency_key == key,
    ).with_for_update())
    if existing:
        if existing.request_hash != request_hash or existing.operation_type != operation_type or existing.resource_id != resource_id:
            raise ValueError("Idempotency key was already used with a different request")
        return True
    session.add(PharmacyWorkflowOperation(
        tenant_id=tenant_id, facility_id=facility_id, idempotency_key=key,
        request_hash=request_hash, operation_type=operation_type, resource_id=resource_id,
    ))
    await session.flush()
    return False


async def create_recall(session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, payload: RecallCreate, current_user: dict) -> ProductRecall:
    request_hash = _hash(payload)
    existing = await session.scalar(select(ProductRecall).where(
        ProductRecall.tenant_id == tenant_id, ProductRecall.idempotency_key == payload.idempotency_key,
    ).with_for_update())
    if existing:
        if existing.request_hash != request_hash:
            raise ValueError("Idempotency key was already used with a different request")
        return existing
    batch_exists = await session.scalar(select(InventoryBatch.id).where(
        InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id,
        InventoryBatch.medicine_id == payload.medicine_id, InventoryBatch.batch_number == payload.batch_number,
    ).limit(1))
    if not batch_exists:
        raise P32NotFoundError("Medicine batch not found")
    record = ProductRecall(
        tenant_id=tenant_id, facility_id=facility_id, medicine_id=payload.medicine_id,
        batch_number=payload.batch_number, status="DRAFT", reference_key=f"RC-{uuid.uuid4().hex[:12]}".upper(),
        idempotency_key=payload.idempotency_key, request_hash=request_hash,
        recall_reason=payload.recall_reason, regulatory_reference=payload.regulatory_reference,
        initiated_by=_user_id(current_user), notification_status="NOT_STARTED",
    )
    session.add(record)
    await session.flush()
    _audit(session, current_user, "CREATE", "product_recall", record.id, new_value={"status": "DRAFT", "medicine_id": record.medicine_id, "batch_number": record.batch_number}, reason=record.recall_reason)
    return record


async def approve_recall(session: AsyncSession, *, recall_id: UUID, tenant_id: UUID, facility_id: UUID, idempotency_key: str, current_user: dict) -> ProductRecall:
    record = await _locked_recall(session, recall_id, tenant_id, facility_id)
    request_hash = hashlib.sha256(json.dumps({"recall_id": str(recall_id)}, sort_keys=True).encode()).hexdigest()
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=idempotency_key, request_hash=request_hash, operation_type="RECALL_APPROVE", resource_id=recall_id):
        return record
    actor = _user_id(current_user)
    if record.status != "DRAFT":
        raise ValueError("Only draft recalls may be approved")
    if record.initiated_by == actor:
        raise ValueError("Initiator cannot approve their own recall")
    batches = (await session.execute(select(InventoryBatch).where(
        InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id,
        InventoryBatch.medicine_id == record.medicine_id, InventoryBatch.batch_number == record.batch_number,
    ).order_by(InventoryBatch.id).with_for_update())).scalars().all()
    if not batches:
        raise P32NotFoundError("Affected medicine batch not found")
    batch_ids = [batch.id for batch in batches]
    reservations = (await session.execute(select(PharmacyStockReservation).where(
        PharmacyStockReservation.inventory_batch_id.in_(batch_ids), PharmacyStockReservation.status == "ACTIVE",
    ).order_by(PharmacyStockReservation.inventory_batch_id, PharmacyStockReservation.id).with_for_update())).scalars().all()
    for reservation in reservations:
        batch = next(item for item in batches if item.id == reservation.inventory_batch_id)
        batch.reserved_quantity = max(Decimal("0"), Decimal(str(batch.reserved_quantity)) - Decimal(str(reservation.quantity)))
        reservation.status = "CANCELLED"
        reservation.released_at = datetime.now(timezone.utc)
        reservation.released_by = actor
        reservation.release_reason = f"Recall {record.reference_key}"
    for batch in batches:
        quantity = Decimal(str(batch.available_quantity))
        batch.status = "RECALLED"
        if quantity <= 0:
            continue
        quarantine = StockQuarantine(
            tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=batch.pharmacy_location_id,
            inventory_batch_id=batch.id, status="QUARANTINED", reference_key=f"{record.reference_key}-{str(batch.id)[:8]}",
            idempotency_key=f"recall:{record.id}:{batch.id}", request_hash=record.request_hash, reason="RECALL",
            total_quantity_quarantined=quantity, remaining_quantity=quantity, notes=record.recall_reason, quarantined_by=actor,
        )
        session.add(quarantine)
        await session.flush()
        ledger = await create_stock_ledger_transaction(
            session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=batch.pharmacy_location_id,
            medicine_id=batch.medicine_id, inventory_batch_id=batch.id, transaction_type="RECALL_QUARANTINE",
            quantity=-quantity, reference_type="PRODUCT_RECALL_BATCH", reference_id=quarantine.id,
            correlation_reference=record.reference_key, reason=record.recall_reason, user_id=actor,
        )
        quarantine.quarantine_ledger_transaction_id = ledger.id
        session.add(RecallAffectedStock(recall_id=record.id, inventory_batch_id=batch.id, pharmacy_location_id=batch.pharmacy_location_id, quarantine_id=quarantine.id, quantity_quarantined=quantity))
        _audit(session, current_user, "QUARANTINE", "product_recall_stock", quarantine.id, new_value={"recall_id": record.id, "quantity": quantity, "location_id": batch.pharmacy_location_id}, reason=record.recall_reason)
    record.status = "ACTIVE"
    record.approved_by = actor
    record.approved_at = datetime.now(timezone.utc)
    _audit(session, current_user, "APPROVE", "product_recall", record.id, old_value={"status": "DRAFT"}, new_value={"status": "ACTIVE"}, reason=record.recall_reason)
    await session.flush()
    return record


async def resolve_recall(session: AsyncSession, *, recall_id: UUID, tenant_id: UUID, facility_id: UUID, payload: RecallResolve, current_user: dict) -> ProductRecall:
    record = await _locked_recall(session, recall_id, tenant_id, facility_id)
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=payload.idempotency_key, request_hash=_hash(payload), operation_type="RECALL_RESOLVE", resource_id=recall_id):
        return record
    if record.status != "ACTIVE":
        raise ValueError("Only active recalls may be resolved")
    actor = _user_id(current_user)
    affected = (await session.execute(select(RecallAffectedStock).where(RecallAffectedStock.recall_id == recall_id).order_by(RecallAffectedStock.inventory_batch_id).with_for_update())).scalars().all()
    quarantines = []
    for item in affected:
        quarantine = await session.scalar(select(StockQuarantine).where(StockQuarantine.id == item.quarantine_id).with_for_update())
        batch = await session.scalar(select(InventoryBatch).where(InventoryBatch.id == item.inventory_batch_id).with_for_update())
        if not quarantine or not batch or quarantine.status != "QUARANTINED":
            raise ValueError("All affected stock must remain quarantined before resolution")
        quarantines.append((quarantine, batch))
    for quarantine, batch in quarantines:
        quantity = Decimal(str(quarantine.remaining_quantity))
        if payload.action == "APPROVED_RELEASE":
            ledger = await create_stock_ledger_transaction(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=batch.pharmacy_location_id, medicine_id=batch.medicine_id, inventory_batch_id=batch.id, transaction_type="RECALL_RELEASE", quantity=quantity, reference_type="PRODUCT_RECALL_RESOLUTION", reference_id=quarantine.id, correlation_reference=record.reference_key, reason=payload.reason, user_id=actor)
            quarantine.status = "RELEASED"
            quarantine.release_ledger_transaction_id = ledger.id
            quarantine.release_reason = payload.reason
            quarantine.released_by = actor
            quarantine.released_at = datetime.now(timezone.utc)
            batch.status = "ACTIVE"
        else:
            transaction_type = "RECALL_SUPPLIER_RETURN" if payload.action == "SUPPLIER_RETURN" else "RECALL_DISPOSAL"
            ledger = await create_stock_ledger_transaction(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=batch.pharmacy_location_id, medicine_id=batch.medicine_id, inventory_batch_id=batch.id, transaction_type=transaction_type, quantity=-quantity, reference_type="PRODUCT_RECALL_RESOLUTION", reference_id=quarantine.id, correlation_reference=record.reference_key, reason=payload.reason, user_id=actor, affects_available_balance=False)
            quarantine.status = "RETURNED_TO_SUPPLIER" if payload.action == "SUPPLIER_RETURN" else "DISPOSED"
            if payload.action == "DISPOSAL":
                quarantine.disposal_ledger_transaction_id = ledger.id
                quarantine.disposal_reason = payload.reason
                quarantine.disposed_by = actor
                quarantine.disposed_at = datetime.now(timezone.utc)
        quarantine.remaining_quantity = Decimal("0")
        quarantine.approved_by = actor
        quarantine.approved_at = datetime.now(timezone.utc)
        quarantine.approved_action = payload.action
        _audit(session, current_user, "RESOLVE", "product_recall_stock", quarantine.id, new_value={"action": payload.action, "quantity": quantity}, reason=payload.reason)
    record.status = "RESOLVED"
    record.resolution_action = payload.action
    record.resolution_reason = payload.reason
    record.resolved_by = actor
    record.resolved_date = datetime.now(timezone.utc)
    _audit(session, current_user, "RESOLVE", "product_recall", record.id, old_value={"status": "ACTIVE"}, new_value={"status": "RESOLVED", "action": payload.action}, reason=payload.reason)
    await session.flush()
    return record


async def update_recall_notification(session: AsyncSession, *, recall_id: UUID, tenant_id: UUID, facility_id: UUID, payload: RecallNotificationUpdate, current_user: dict) -> ProductRecall:
    record = await _locked_recall(session, recall_id, tenant_id, facility_id)
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=payload.idempotency_key, request_hash=_hash(payload), operation_type="RECALL_NOTIFICATION", resource_id=recall_id):
        return record
    old = record.notification_status
    record.notification_status = payload.notification_status
    _audit(session, current_user, "NOTIFICATION_STATUS", "product_recall", record.id, old_value={"notification_status": old}, new_value={"notification_status": record.notification_status})
    await session.flush()
    return record


async def affected_dispensings(session: AsyncSession, *, recall_id: UUID, tenant_id: UUID, facility_id: UUID):
    record = await _locked_recall(session, recall_id, tenant_id, facility_id, lock=False)
    rows = (await session.execute(
        select(PharmacyDispense.id, Patient.id, Patient.uhid, Patient.first_name, Patient.last_name, Patient.phone, PharmacyDispenseAllocation.confirmed_dispensed_quantity, PharmacyDispense.completed_at)
        .join(PharmacyDispenseItem, PharmacyDispenseItem.dispense_id == PharmacyDispense.id)
        .join(PharmacyDispenseAllocation, PharmacyDispenseAllocation.dispense_item_id == PharmacyDispenseItem.id)
        .join(InventoryBatch, InventoryBatch.id == PharmacyDispenseAllocation.inventory_batch_id)
        .join(Patient, Patient.id == PharmacyDispense.patient_id)
        .where(PharmacyDispense.tenant_id == tenant_id, PharmacyDispense.facility_id == facility_id, InventoryBatch.medicine_id == record.medicine_id, InventoryBatch.batch_number == record.batch_number, PharmacyDispenseAllocation.confirmed_dispensed_quantity > 0)
        .order_by(PharmacyDispense.completed_at.desc(), PharmacyDispense.id)
    )).all()
    return [{"dispense_id": row[0], "patient_id": row[1], "uhid": row[2], "patient_name": f"{row[3]} {row[4]}".strip(), "phone": row[5], "dispensed_quantity": row[6], "dispensed_at": row[7], "notification_status": record.notification_status} for row in rows]


async def _locked_recall(session: AsyncSession, recall_id: UUID, tenant_id: UUID, facility_id: UUID, lock: bool = True) -> ProductRecall:
    stmt = select(ProductRecall).where(ProductRecall.id == recall_id, ProductRecall.tenant_id == tenant_id, ProductRecall.facility_id == facility_id)
    record = await session.scalar(stmt.with_for_update() if lock else stmt)
    if not record:
        raise P32NotFoundError("Recall not found")
    return record


async def create_transfer(session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, payload: TransferCreate, current_user: dict) -> StockTransfer:
    request_hash = _hash(payload)
    existing = await session.scalar(select(StockTransfer).where(StockTransfer.tenant_id == tenant_id, StockTransfer.idempotency_key == payload.idempotency_key).with_for_update())
    if existing:
        if existing.request_hash != request_hash:
            raise ValueError("Idempotency key was already used with a different request")
        return existing
    from app.models.tenant import PharmacyLocation
    location_ids = sorted((payload.source_location_id, payload.destination_location_id), key=str)
    locations = (await session.execute(select(PharmacyLocation).where(
        PharmacyLocation.id.in_(location_ids), PharmacyLocation.tenant_id == tenant_id,
        PharmacyLocation.facility_id == facility_id, PharmacyLocation.active.is_(True),
    ).order_by(PharmacyLocation.id).with_for_update())).scalars().all()
    if {item.id for item in locations} != set(location_ids):
        raise P32NotFoundError("Source or destination pharmacy location not found")
    requested = {item.inventory_batch_id: item.quantity for item in payload.items}
    batches = (await session.execute(select(InventoryBatch).where(
        InventoryBatch.id.in_(sorted(requested, key=str)), InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id, InventoryBatch.pharmacy_location_id == payload.source_location_id,
    ).order_by(InventoryBatch.id).with_for_update())).scalars().all()
    if {item.id for item in batches} != set(requested):
        raise P32NotFoundError("One or more source batches were not found")
    for batch in batches:
        if batch.status != "ACTIVE":
            raise ValueError("Recalled or inactive inventory batch cannot be transferred")
        available = Decimal(str(batch.available_quantity)) - Decimal(str(batch.reserved_quantity))
        if requested[batch.id] > available:
            raise ValueError("Transfer quantity exceeds unreserved source stock")
    record = StockTransfer(
        tenant_id=tenant_id, facility_id=facility_id, from_location_id=payload.source_location_id,
        to_location_id=payload.destination_location_id, status="DRAFT", reference_key=f"TR-{uuid.uuid4().hex[:12]}".upper(),
        idempotency_key=payload.idempotency_key, request_hash=request_hash, total_items=len(payload.items),
        total_quantity=sum(requested.values(), Decimal("0")), notes=payload.notes, requested_by=_user_id(current_user),
    )
    session.add(record)
    await session.flush()
    for batch in batches:
        session.add(StockTransferItem(transfer_id=record.id, inventory_batch_id=batch.id, transfer_quantity=requested[batch.id]))
    _audit(session, current_user, "CREATE", "stock_transfer", record.id, new_value={"status": "DRAFT", "quantity": record.total_quantity, "source": record.from_location_id, "destination": record.to_location_id}, reason=payload.notes)
    await session.flush()
    return record


async def approve_transfer(session: AsyncSession, *, transfer_id: UUID, tenant_id: UUID, facility_id: UUID, idempotency_key: str, current_user: dict) -> StockTransfer:
    record = await _locked_transfer(session, transfer_id, tenant_id, facility_id)
    request_hash = hashlib.sha256(json.dumps({"transfer_id": str(transfer_id)}, sort_keys=True).encode()).hexdigest()
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=idempotency_key, request_hash=request_hash, operation_type="TRANSFER_APPROVE", resource_id=transfer_id):
        return record
    actor = _user_id(current_user)
    if record.status != "DRAFT":
        raise ValueError("Only draft transfers may be approved")
    if record.requested_by == actor:
        raise ValueError("Requester cannot approve their own transfer")
    items = await _locked_transfer_items(session, transfer_id)
    batches = await _locked_batches(session, [item.inventory_batch_id for item in items], tenant_id, facility_id)
    for item in items:
        batch = batches[item.inventory_batch_id]
        if batch.status != "ACTIVE":
            raise ValueError("Recalled or inactive inventory batch cannot be transferred")
        available = Decimal(str(batch.available_quantity)) - Decimal(str(batch.reserved_quantity))
        if item.transfer_quantity > available:
            raise ValueError("Transfer approval would exceed unreserved source stock")
    for item in items:
        batches[item.inventory_batch_id].reserved_quantity += item.transfer_quantity
    record.status = "APPROVED"
    record.approved_by = actor
    record.approved_at = datetime.now(timezone.utc)
    _audit(session, current_user, "APPROVE", "stock_transfer", record.id, old_value={"status": "DRAFT"}, new_value={"status": "APPROVED"})
    await session.flush()
    return record


async def dispatch_transfer(session: AsyncSession, *, transfer_id: UUID, tenant_id: UUID, facility_id: UUID, idempotency_key: str, current_user: dict) -> StockTransfer:
    record = await _locked_transfer(session, transfer_id, tenant_id, facility_id)
    request_hash = hashlib.sha256(json.dumps({"transfer_id": str(transfer_id)}, sort_keys=True).encode()).hexdigest()
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=idempotency_key, request_hash=request_hash, operation_type="TRANSFER_DISPATCH", resource_id=transfer_id):
        return record
    if record.status != "APPROVED":
        raise ValueError("Only approved transfers may be dispatched")
    actor = _user_id(current_user)
    items = await _locked_transfer_items(session, transfer_id)
    batches = await _locked_batches(session, [item.inventory_batch_id for item in items], tenant_id, facility_id)
    for item in items:
        batch = batches[item.inventory_batch_id]
        if batch.status != "ACTIVE":
            raise ValueError("Recalled or inactive inventory batch cannot be transferred")
        if batch.reserved_quantity < item.transfer_quantity or batch.available_quantity < item.transfer_quantity:
            raise ValueError("Reserved source stock is no longer available")
    for item in items:
        batch = batches[item.inventory_batch_id]
        batch.reserved_quantity -= item.transfer_quantity
        ledger = await create_stock_ledger_transaction(
            session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=record.from_location_id,
            medicine_id=batch.medicine_id, inventory_batch_id=batch.id, transaction_type="TRANSFER_DISPATCH",
            quantity=-item.transfer_quantity, reference_type="STOCK_TRANSFER_ITEM", reference_id=item.id,
            correlation_reference=record.reference_key, reason="Inter-location transfer dispatched", user_id=actor,
        )
        item.dispatch_ledger_id = ledger.id
    record.status = "IN_TRANSIT"
    record.dispatched_by = actor
    record.dispatched_at = datetime.now(timezone.utc)
    _audit(session, current_user, "DISPATCH", "stock_transfer", record.id, old_value={"status": "APPROVED"}, new_value={"status": "IN_TRANSIT"})
    await session.flush()
    return record


async def receive_transfer(session: AsyncSession, *, transfer_id: UUID, tenant_id: UUID, facility_id: UUID, payload: TransferReceive, current_user: dict) -> StockTransfer:
    record = await _locked_transfer(session, transfer_id, tenant_id, facility_id)
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=payload.idempotency_key, request_hash=_hash(payload), operation_type="TRANSFER_RECEIVE", resource_id=transfer_id):
        return record
    if record.status != "IN_TRANSIT":
        raise ValueError("Only in-transit stock may be received")
    items = await _locked_transfer_items(session, transfer_id)
    by_id = {item.id: item for item in items}
    if len({entry.transfer_item_id for entry in payload.items}) != len(payload.items) or any(entry.transfer_item_id not in by_id for entry in payload.items):
        raise ValueError("Receipt contains an invalid or duplicate transfer item")
    for entry in payload.items:
        item = by_id[entry.transfer_item_id]
        if item.received_quantity is not None:
            raise ValueError("Transfer item was already received")
        if entry.quantity_received > item.transfer_quantity:
            raise ValueError("Received quantity cannot exceed dispatched quantity")
        difference = item.transfer_quantity - entry.quantity_received
        if difference > 0 and entry.discrepancy_type is None:
            raise ValueError("Partial receipt requires an explicit discrepancy")
        if entry.discrepancy_type and entry.discrepancy_quantity != difference:
            raise ValueError("Discrepancy quantity must match dispatched minus received quantity")
    source_batches = await _locked_batches(session, [by_id[entry.transfer_item_id].inventory_batch_id for entry in payload.items], tenant_id, facility_id)
    actor = _user_id(current_user)
    for entry in payload.items:
        item = by_id[entry.transfer_item_id]
        source = source_batches[item.inventory_batch_id]
        destination = await session.scalar(select(InventoryBatch).where(
            InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == record.to_location_id, InventoryBatch.medicine_id == source.medicine_id,
            InventoryBatch.batch_number == source.batch_number,
        ).with_for_update())
        if destination is None:
            destination = InventoryBatch(
                tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=record.to_location_id,
                medicine_id=source.medicine_id, batch_number=source.batch_number, manufacturing_date=source.manufacturing_date,
                expiry_date=source.expiry_date, purchase_rate=source.purchase_rate, mrp=source.mrp,
                received_quantity=Decimal("0"), available_quantity=Decimal("0"), reserved_quantity=Decimal("0"),
                supplier_id=source.supplier_id, status="ACTIVE", created_by=actor,
            )
            session.add(destination)
            await session.flush()
        if destination.manufacturing_date != source.manufacturing_date or destination.expiry_date != source.expiry_date:
            raise ValueError("Destination batch identity does not match dispatched batch")
        item.received_quantity = entry.quantity_received
        item.destination_batch_id = destination.id
        if entry.quantity_received > 0:
            ledger = await create_stock_ledger_transaction(
                session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=record.to_location_id,
                medicine_id=destination.medicine_id, inventory_batch_id=destination.id, transaction_type="TRANSFER_RECEIVE",
                quantity=entry.quantity_received, reference_type="STOCK_TRANSFER_ITEM", reference_id=item.id,
                correlation_reference=record.reference_key, reason="Inter-location transfer received", user_id=actor,
            )
            item.receive_ledger_id = ledger.id
            destination.received_quantity += entry.quantity_received
        if entry.discrepancy_type:
            session.add(StockTransferDiscrepancy(
                transfer_id=record.id, transfer_item_id=item.id, discrepancy_type=entry.discrepancy_type,
                quantity=entry.discrepancy_quantity, notes=entry.discrepancy_notes.strip(), status="OPEN", reported_by=actor,
            ))
    all_received = all(item.received_quantity is not None or item.id in {entry.transfer_item_id for entry in payload.items} for item in items)
    if payload.complete_receipt and not all_received:
        raise ValueError("Complete receipt must account for every transfer item")
    record.received_quantity = sum((Decimal(str(item.received_quantity or 0)) for item in items), Decimal("0"))
    if payload.complete_receipt:
        record.status = "RECEIVED"
        record.received_by = actor
        record.received_at = datetime.now(timezone.utc)
    _audit(session, current_user, "RECEIVE", "stock_transfer", record.id, old_value={"status": "IN_TRANSIT"}, new_value={"status": record.status, "received_quantity": record.received_quantity})
    await session.flush()
    return record


async def reconcile_discrepancy(session: AsyncSession, *, discrepancy_id: UUID, tenant_id: UUID, facility_id: UUID, action: str, notes: str, idempotency_key: str, current_user: dict) -> StockTransferDiscrepancy:
    discrepancy = await session.scalar(select(StockTransferDiscrepancy).join(StockTransfer, StockTransfer.id == StockTransferDiscrepancy.transfer_id).where(
        StockTransferDiscrepancy.id == discrepancy_id, StockTransfer.tenant_id == tenant_id, StockTransfer.facility_id == facility_id,
    ).with_for_update())
    if not discrepancy:
        raise P32NotFoundError("Transfer discrepancy not found")
    request_hash = hashlib.sha256(json.dumps({"action": action, "notes": notes}, sort_keys=True).encode()).hexdigest()
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=idempotency_key, request_hash=request_hash, operation_type="TRANSFER_RECONCILE", resource_id=discrepancy_id):
        return discrepancy
    if discrepancy.status != "OPEN":
        raise ValueError("Only open discrepancies may be reconciled")
    discrepancy.status = "RECONCILED"
    discrepancy.reconciled_by = _user_id(current_user)
    discrepancy.reconciled_at = datetime.now(timezone.utc)
    discrepancy.reconciliation_action = action
    discrepancy.reconciliation_notes = notes
    _audit(session, current_user, "RECONCILE", "stock_transfer_discrepancy", discrepancy.id, old_value={"status": "OPEN"}, new_value={"status": "RECONCILED", "action": action}, reason=notes)
    await session.flush()
    return discrepancy


async def cancel_transfer(session: AsyncSession, *, transfer_id: UUID, tenant_id: UUID, facility_id: UUID, idempotency_key: str, current_user: dict) -> StockTransfer:
    record = await _locked_transfer(session, transfer_id, tenant_id, facility_id)
    request_hash = hashlib.sha256(json.dumps({"transfer_id": str(transfer_id)}, sort_keys=True).encode()).hexdigest()
    if await _operation(session, tenant_id=tenant_id, facility_id=facility_id, key=idempotency_key, request_hash=request_hash, operation_type="TRANSFER_CANCEL", resource_id=transfer_id):
        return record
    if record.status not in {"DRAFT", "APPROVED"}:
        raise ValueError("Dispatched transfers require an explicit return movement")
    if record.status == "APPROVED":
        items = await _locked_transfer_items(session, transfer_id)
        batches = await _locked_batches(session, [item.inventory_batch_id for item in items], tenant_id, facility_id)
        for item in items:
            batches[item.inventory_batch_id].reserved_quantity -= item.transfer_quantity
    old = record.status
    record.status = "CANCELLED"
    _audit(session, current_user, "CANCEL", "stock_transfer", record.id, old_value={"status": old}, new_value={"status": "CANCELLED"})
    await session.flush()
    return record


async def _locked_transfer(session: AsyncSession, transfer_id: UUID, tenant_id: UUID, facility_id: UUID) -> StockTransfer:
    record = await session.scalar(select(StockTransfer).where(StockTransfer.id == transfer_id, StockTransfer.tenant_id == tenant_id, StockTransfer.facility_id == facility_id).with_for_update())
    if not record:
        raise P32NotFoundError("Stock transfer not found")
    return record


async def _locked_transfer_items(session: AsyncSession, transfer_id: UUID) -> list[StockTransferItem]:
    return list((await session.execute(select(StockTransferItem).where(StockTransferItem.transfer_id == transfer_id).order_by(StockTransferItem.inventory_batch_id).with_for_update())).scalars().all())


async def _locked_batches(session: AsyncSession, batch_ids: list[UUID], tenant_id: UUID, facility_id: UUID) -> dict[UUID, InventoryBatch]:
    batches = (await session.execute(select(InventoryBatch).where(InventoryBatch.id.in_(sorted(batch_ids, key=str)), InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id).order_by(InventoryBatch.id).with_for_update())).scalars().all()
    if len(batches) != len(set(batch_ids)):
        raise P32NotFoundError("One or more inventory batches were not found")
    return {batch.id: batch for batch in batches}
