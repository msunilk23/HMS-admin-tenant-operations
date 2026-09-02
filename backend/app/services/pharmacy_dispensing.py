from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tenant.inventory_batch import InventoryBatch
from app.services.stock_ledger_service import assert_inventory_batch_not_frozen
from app.models.tenant.invoice import Invoice, Refund
from app.models.tenant.pharmacy_dispense import PharmacyDispense, PharmacyDispenseAllocation, PharmacyDispenseItem, PharmacyStockReservation
from app.models.tenant.stock_transaction import StockTransaction
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.visit import Visit
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.medicine_product import MedicineProduct


def _decimal_quantity(value: Any) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Prescription quantity is invalid") from exc
    if quantity <= 0:
        raise ValueError("Prescription quantity must be positive")
    return quantity


def prepare_billable_pharmacy_line_items(
    line_items: list[dict[str, Any]],
    dispense_items: list[PharmacyDispenseItem],
    already_billed_quantities: dict[uuid.UUID, Decimal] | None = None,
) -> list[dict[str, Any]]:
    """Keep only hospital-supplied quantity and remove outside-purchase lines."""
    already_billed_quantities = already_billed_quantities or {}
    by_id = {item.id: item for item in dispense_items}
    by_name: dict[str, list[PharmacyDispenseItem]] = {}
    for item in dispense_items:
        by_name.setdefault(item.prescribed_name_snapshot.strip().casefold(), []).append(item)

    billable: list[dict[str, Any]] = []
    used_ids: set[uuid.UUID] = set()
    for line in line_items:
        dispense_item_id = line.get("dispense_item_id")
        item = by_id.get(uuid.UUID(str(dispense_item_id))) if dispense_item_id else None
        if item is None and not dispense_item_id:
            matches = by_name.get(str(line.get("name", "")).strip().casefold(), [])
            item = matches[0] if len(matches) == 1 else None
        if item is None:
            raise ValueError("Each pharmacy billing line must identify one dispense item")
        if item.id in used_ids:
            raise ValueError("A dispense item cannot appear on multiple billing lines")
        used_ids.add(item.id)

        internal_quantity = Decimal(str(item.internal_confirmed_quantity or 0))
        internal_quantity -= already_billed_quantities.get(item.prescription_item_id, Decimal("0"))
        if internal_quantity <= 0:
            continue
        requested_quantity = Decimal(str(line.get("qty", 0)))
        if requested_quantity <= 0:
            raise ValueError("Billing quantity must be positive")
        quantity = min(requested_quantity, internal_quantity)
        billable_line = dict(line)
        billable_line["dispense_item_id"] = str(item.id)
        billable_line["prescription_item_id"] = str(item.prescription_item_id)
        billable_line["qty"] = float(quantity)
        billable_line["total"] = float(quantity * Decimal(str(line.get("mrp", 0))))
        billable.append(billable_line)

    if not billable:
        raise ValueError("No hospital-supplied pharmacy quantity is billable")
    return billable


async def resolve_billable_pharmacy_line_items(
    session: AsyncSession,
    *,
    line_items: list[dict[str, Any]],
    dispense_items: list[PharmacyDispenseItem],
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Resolve billed price and tax from the server-side batch and product records."""
    prepared = prepare_billable_pharmacy_line_items(line_items, dispense_items)
    items_by_id = {item.id: item for item in dispense_items}
    resolved: list[dict[str, Any]] = []
    for line in prepared:
        item = items_by_id[uuid.UUID(str(line["dispense_item_id"]))]
        batches = (await session.execute(
            select(InventoryBatch, PharmacyDispenseAllocation).join(
                PharmacyDispenseAllocation,
                PharmacyDispenseAllocation.inventory_batch_id == InventoryBatch.id,
            ).where(
                PharmacyDispenseAllocation.dispense_item_id == item.id,
                PharmacyDispenseAllocation.tenant_id == tenant_id,
                PharmacyDispenseAllocation.facility_id == facility_id,
                PharmacyDispenseAllocation.status.in_(("RESERVED", "CONSUMED")),
                InventoryBatch.tenant_id == tenant_id,
                InventoryBatch.facility_id == facility_id,
            )
        )).all()
        if not batches:
            raise ValueError("No allocated pharmacy batch is available for billing")
        mrps = {batch.mrp for batch, _ in batches if batch.mrp is not None}
        if len(mrps) != 1:
            raise ValueError("Pharmacy batch price is missing or ambiguous")
        mrp = next(iter(mrps))
        product = None
        if item.prescribed_medicine_product_id:
            product = await session.get(MedicineProduct, item.prescribed_medicine_product_id)
        gst_rate = product.gst_rate if product and product.gst_rate is not None else Decimal("0")
        resolved_line = dict(line)
        resolved_line["mrp"] = float(mrp)
        resolved_line["gst_pct"] = float(gst_rate)
        resolved_line["dis_pct"] = 0.0
        resolved_line["total"] = float(Decimal(str(line["qty"])) * mrp)
        resolved.append(resolved_line)
    return resolved


async def _scoped_location(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    pharmacy_location_id: uuid.UUID,
) -> PharmacyLocation:
    location = await session.scalar(
        select(PharmacyLocation).where(
            PharmacyLocation.id == pharmacy_location_id,
            PharmacyLocation.tenant_id == tenant_id,
            PharmacyLocation.facility_id == facility_id,
            PharmacyLocation.active == True,  # noqa: E712
        )
    )
    if location is None:
        raise ValueError("Pharmacy location is missing, inactive, or outside the tenant facility")
    return location


async def start_pharmacy_dispense(
    session: AsyncSession,
    *,
    queue_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    pharmacy_location_id: uuid.UUID,
    started_by: uuid.UUID,
) -> PharmacyDispense:
    queue = await session.get(PharmacyQueue, queue_id)
    if queue is None:
        raise ValueError("Pharmacy queue item not found")
    if queue.status in {"cancelled", "dispensed", "out_of_stock"}:
        raise ValueError("Pharmacy queue item is not available for intake")
    await _scoped_location(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
    )
    prescription = await session.get(Prescription, queue.prescription_id)
    if prescription is None or prescription.status.lower() != "finalized":
        raise ValueError("Prescription is not finalized")
    visit = await session.get(Visit, prescription.visit_id)
    if visit is None:
        raise ValueError("Prescription visit not found")

    existing = await session.scalar(
        select(PharmacyDispense).where(
            PharmacyDispense.tenant_id == tenant_id,
            PharmacyDispense.pharmacy_queue_id == queue.id,
            PharmacyDispense.status.not_in(("CANCELLED", "EXPIRED")),
        )
    )
    if existing is not None:
        return existing

    dispense = PharmacyDispense(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        prescription_id=prescription.id,
        prescription_version=prescription.version,
        visit_id=visit.id,
        patient_id=visit.patient_id,
        pharmacy_queue_id=queue.id,
        classification="OPD_PRESCRIPTION",
        status="DRAFT",
        started_at=datetime.now(timezone.utc),
        started_by=started_by,
        created_by=started_by,
        updated_by=started_by,
    )
    session.add(dispense)
    queue.status = "dispensing"
    queue.dispensing_started_at = dispense.started_at
    await session.flush()
    return dispense


async def validate_pharmacy_dispense(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    validated_by: uuid.UUID,
) -> PharmacyDispense:
    dispense = await session.scalar(
        select(PharmacyDispense).where(
            PharmacyDispense.id == dispense_id,
            PharmacyDispense.tenant_id == tenant_id,
            PharmacyDispense.facility_id == facility_id,
        )
    )
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    await _scoped_location(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=dispense.pharmacy_location_id,
    )
    prescription = await session.get(Prescription, dispense.prescription_id)
    if prescription is None or prescription.status.lower() != "finalized":
        raise ValueError("Prescription is not finalized")
    if prescription.version != dispense.prescription_version:
        raise ValueError("Prescription version has changed")
    visit = await session.get(Visit, prescription.visit_id)
    if visit is None or visit.id != dispense.visit_id or visit.patient_id != dispense.patient_id:
        raise ValueError("Prescription encounter does not match dispense")
    if dispense.status == "VALIDATED":
        return dispense
    if dispense.status != "DRAFT":
        raise ValueError("Pharmacy dispense is not awaiting validation")

    items = (await session.execute(
        select(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription.id)
    )).scalars().all()
    if not items:
        raise ValueError("Prescription has no medicine items")
    for prescription_item in items:
        raw_quantity = prescription_item.final_quantity or prescription_item.quantity
        quantity = _decimal_quantity(raw_quantity)
        session.add(PharmacyDispenseItem(
            dispense_id=dispense.id,
            prescription_item_id=prescription_item.id,
            prescribed_medicine_product_id=prescription_item.medicine_product_id,
            prescribed_medicine_master_id=prescription_item.medicine_master_id,
            prescribed_name_snapshot=prescription_item.medicine,
            prescribed_strength_snapshot=prescription_item.strength_snapshot or prescription_item.strength,
            prescribed_dosage_form_snapshot=prescription_item.dosage_form_snapshot or prescription_item.dosage_form,
            prescribed_route_snapshot=prescription_item.route_snapshot or prescription_item.route,
            prescribed_quantity=quantity,
            internal_requested_quantity=Decimal("0"),
            internal_confirmed_quantity=Decimal("0"),
            outside_purchase_quantity=Decimal("0"),
            no_substitution_applied=prescription_item.no_substitution,
            status="PENDING",
            created_by=validated_by,
            updated_by=validated_by,
        ))
    dispense.status = "VALIDATED"
    dispense.updated_by = validated_by
    await session.flush()
    return dispense


async def propose_pharmacy_allocations(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    proposed_by: uuid.UUID,
    requested_quantities: dict[uuid.UUID, Decimal] | None = None,
    as_of_date: date | None = None,
) -> PharmacyDispense:
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status != "VALIDATED":
        raise ValueError("Pharmacy dispense must be validated before allocation")

    items = (await session.execute(select(PharmacyDispenseItem).where(
        PharmacyDispenseItem.dispense_id == dispense.id,
    ))).scalars().all()
    reference_date = as_of_date or date.today()
    for item in items:
        requested = _decimal_quantity((requested_quantities or {}).get(item.id, item.prescribed_quantity))
        if requested > item.prescribed_quantity:
            raise ValueError("Requested internal quantity exceeds prescribed quantity")
        previous = (await session.execute(select(PharmacyDispenseAllocation).where(
            PharmacyDispenseAllocation.dispense_item_id == item.id,
            PharmacyDispenseAllocation.status == "PROPOSED",
        ))).scalars().all()
        if any(allocation.confirmed_dispensed_quantity > 0 for allocation in previous):
            raise ValueError("Confirmed allocations cannot be replaced")
        for allocation in previous:
            await session.delete(allocation)

        if item.prescribed_medicine_product_id is None:
            raise ValueError("Product-based medicine identity is required for FEFO allocation")
        batches = (await session.execute(select(InventoryBatch).where(
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == dispense.pharmacy_location_id,
            InventoryBatch.medicine_id == item.prescribed_medicine_product_id,
            InventoryBatch.status == "ACTIVE",
            InventoryBatch.available_quantity > InventoryBatch.reserved_quantity,
            (InventoryBatch.expiry_date.is_(None) | (InventoryBatch.expiry_date >= reference_date)),
        ).order_by(InventoryBatch.expiry_date.asc().nulls_last(), InventoryBatch.id.asc()))).scalars().all()
        remaining = requested
        for batch in batches:
            allocatable = batch.available_quantity - batch.reserved_quantity
            allocation_quantity = min(remaining, allocatable)
            if allocation_quantity <= 0:
                continue
            session.add(PharmacyDispenseAllocation(
                dispense_item_id=item.id,
                tenant_id=tenant_id,
                facility_id=facility_id,
                pharmacy_location_id=dispense.pharmacy_location_id,
                inventory_batch_id=batch.id,
                allocated_quantity=allocation_quantity,
                allocation_source="FEFO",
                status="PROPOSED",
            ))
            remaining -= allocation_quantity
            if remaining <= 0:
                break
        item.internal_requested_quantity = requested
        if remaining > 0:
            item.status = "PARTIAL"
    dispense.updated_by = proposed_by
    await session.flush()
    return dispense


async def create_stock_reservations(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    reserved_by: uuid.UUID,
    now: datetime | None = None,
    ttl_minutes: int | None = None,
) -> list[PharmacyStockReservation]:
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status != "VALIDATED":
        raise ValueError("Pharmacy dispense must be validated before reservation")
    allocations = (await session.execute(select(PharmacyDispenseAllocation).where(
        PharmacyDispenseAllocation.dispense_item_id.in_(
            select(PharmacyDispenseItem.id).where(PharmacyDispenseItem.dispense_id == dispense.id)
        ),
        PharmacyDispenseAllocation.status == "PROPOSED",
    ))).scalars().all()
    if not allocations:
        raise ValueError("No proposed allocations to reserve")

    reserved_at = now or datetime.now(timezone.utc)
    expires_at = reserved_at + timedelta(minutes=ttl_minutes if ttl_minutes is not None else settings.PHARMACY_RESERVATION_TTL_MINUTES)
    reservations = []
    for allocation in allocations:
        batch = await session.scalar(select(InventoryBatch).where(
            InventoryBatch.id == allocation.inventory_batch_id,
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == dispense.pharmacy_location_id,
        ).with_for_update())
        if batch is None:
            raise ValueError("Inventory batch not found")
        assert_inventory_batch_not_frozen(batch)
        active_reserved = batch.reserved_quantity or Decimal("0")
        if batch.status != "ACTIVE" or (batch.expiry_date is not None and batch.expiry_date < reserved_at.date()):
            raise ValueError("Inventory batch is expired or inactive")
        if batch.available_quantity - active_reserved < allocation.allocated_quantity:
            raise ValueError("Insufficient available stock for reservation")
        existing = await session.scalar(select(PharmacyStockReservation).where(
            PharmacyStockReservation.dispense_item_id == allocation.dispense_item_id,
            PharmacyStockReservation.inventory_batch_id == batch.id,
            PharmacyStockReservation.status == "ACTIVE",
        ))
        if existing is not None:
            reservations.append(existing)
            continue
        batch.reserved_quantity = active_reserved + allocation.allocated_quantity
        reservation = PharmacyStockReservation(
            tenant_id=tenant_id, facility_id=facility_id,
            pharmacy_location_id=batch.pharmacy_location_id,
            dispense_id=dispense.id, dispense_item_id=allocation.dispense_item_id,
            inventory_batch_id=batch.id, quantity=allocation.allocated_quantity,
            status="ACTIVE", reserved_at=reserved_at, reserved_by=reserved_by,
            expires_at=expires_at,
        )
        allocation.status = "RESERVED"
        session.add(reservation)
        reservations.append(reservation)
    dispense.status = "RESERVED"
    dispense.updated_by = reserved_by
    await session.flush()
    return reservations


async def release_stock_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    released_by: uuid.UUID | None = None,
    reason: str = "Reservation released",
    status: str = "RELEASED",
) -> PharmacyStockReservation:
    reservation = await session.scalar(select(PharmacyStockReservation).where(
        PharmacyStockReservation.id == reservation_id,
        PharmacyStockReservation.tenant_id == tenant_id,
        PharmacyStockReservation.facility_id == facility_id,
    ))
    if reservation is None:
        raise ValueError("Stock reservation not found")
    if reservation.status != "ACTIVE":
        return reservation
    batch = await session.scalar(select(InventoryBatch).where(
        InventoryBatch.id == reservation.inventory_batch_id,
        InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id,
    ).with_for_update())
    if batch is None or batch.reserved_quantity < reservation.quantity:
        raise ValueError("Reservation balance is inconsistent")
    assert_inventory_batch_not_frozen(batch)
    batch.reserved_quantity -= reservation.quantity
    reservation.status = status
    reservation.released_at = datetime.now(timezone.utc)
    reservation.released_by = released_by
    reservation.release_reason = reason
    await session.flush()
    return reservation


async def release_dispense_reservations(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    released_by: uuid.UUID | None = None,
    reason: str = "Pharmacy billing cancelled",
) -> PharmacyDispense:
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ).with_for_update())
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status == "CONFIRMED":
        raise ValueError("Medicine has already been dispensed. Use patient return workflow.")
    if dispense.status in {"CANCELLED", "EXPIRED"}:
        return dispense

    invoice = None
    if dispense.invoice_id is not None:
        invoice = await session.get(Invoice, dispense.invoice_id)
    if invoice is not None and invoice.status == "paid" and dispense.billing_status == "AUTHORIZED":
        invoice.status = "refunded"
        invoice.paid_amount = 0.0
        if not invoice.receipt_number:
            invoice.receipt_number = f"REF-{datetime.now(timezone.utc):%Y%m%d}-{str(invoice.id)[:8].upper()}"
        existing_refund = await session.scalar(select(Refund).where(Refund.invoice_id == invoice.id))
        if existing_refund is None:
            session.add(Refund(
                id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=float(invoice.total),
                reason=reason,
                refunded_at=datetime.now(timezone.utc),
            ))

    reservations = (await session.execute(select(PharmacyStockReservation).where(
        PharmacyStockReservation.dispense_id == dispense.id,
        PharmacyStockReservation.status == "ACTIVE",
    ))).scalars().all()
    for reservation in reservations:
        await release_stock_reservation(
            session,
            reservation_id=reservation.id,
            tenant_id=tenant_id,
            facility_id=facility_id,
            released_by=released_by,
            reason=reason,
            status="CANCELLED",
        )
    dispense.status = "CANCELLED"
    dispense.billing_status = "CANCELLED"
    dispense.cancelled_at = datetime.now(timezone.utc)
    dispense.cancelled_by = released_by
    dispense.cancellation_reason = reason
    dispense.updated_by = released_by
    if dispense.pharmacy_queue_id is not None:
        queue = await session.scalar(select(PharmacyQueue).where(PharmacyQueue.id == dispense.pharmacy_queue_id))
        if queue is not None:
            queue.status = "cancelled"
    await session.flush()
    return dispense


async def expire_stock_reservations(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    now: datetime | None = None,
    released_by: uuid.UUID | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    reservations = (await session.execute(
        select(PharmacyStockReservation)
        .where(
            PharmacyStockReservation.tenant_id == tenant_id,
            PharmacyStockReservation.status == "ACTIVE",
            PharmacyStockReservation.expires_at <= current_time,
        )
        .order_by(PharmacyStockReservation.id)
    )).scalars().all()
    if not reservations:
        return 0

    released_count = 0
    affected_dispenses: dict[uuid.UUID, PharmacyDispense] = {}
    for reservation in reservations:
        dispense = await session.scalar(select(PharmacyDispense).where(
            PharmacyDispense.id == reservation.dispense_id,
            PharmacyDispense.tenant_id == tenant_id,
        ).with_for_update())
        if dispense is not None:
            affected_dispenses.setdefault(reservation.dispense_id, dispense)
        invoice = None
        if dispense is not None and dispense.invoice_id is not None:
            invoice = await session.get(Invoice, dispense.invoice_id)
        if dispense is not None and dispense.billing_status == "AUTHORIZED":
            if invoice is None or invoice.status == "paid":
                continue
        await release_stock_reservation(
            session,
            reservation_id=reservation.id,
            tenant_id=reservation.tenant_id,
            facility_id=reservation.facility_id,
            released_by=released_by,
            reason="Reservation expired",
            status="EXPIRED",
        )
        released_count += 1

    for dispense in affected_dispenses.values():
        if dispense.status in {"CONFIRMED", "CANCELLED", "EXPIRED"}:
            continue
        invoice = None
        if dispense.invoice_id is not None:
            invoice = await session.get(Invoice, dispense.invoice_id)
        if dispense.billing_status == "AUTHORIZED":
            if invoice is None or invoice.status == "paid":
                continue
        dispense.status = "EXPIRED"
        dispense.billing_status = "EXPIRED"
        dispense.cancelled_at = datetime.now(timezone.utc)
        dispense.cancelled_by = released_by
        dispense.cancellation_reason = "Reservation expired"
        dispense.updated_by = released_by
        if dispense.pharmacy_queue_id is not None:
            queue = await session.scalar(select(PharmacyQueue).where(PharmacyQueue.id == dispense.pharmacy_queue_id))
            if queue is not None:
                queue.status = "cancelled"
    await session.flush()
    return released_count


async def _confirm_internal_fulfillment(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    confirmed_by: uuid.UUID,
    allow_partial: bool,
) -> PharmacyDispense:
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    expected_status = "PARTIALLY_FULFILLED" if allow_partial else "READY_FOR_BILLING"
    if dispense.status == expected_status:
        return dispense
    if dispense.status != "RESERVED":
        raise ValueError("Pharmacy dispense must have active reservations")

    items = (await session.execute(select(PharmacyDispenseItem).where(
        PharmacyDispenseItem.dispense_id == dispense.id,
    ))).scalars().all()
    if not items:
        raise ValueError("Pharmacy dispense has no items")
    for item in items:
        allocations = (await session.execute(select(PharmacyDispenseAllocation).where(
            PharmacyDispenseAllocation.dispense_item_id == item.id,
            PharmacyDispenseAllocation.status == "RESERVED",
        ))).scalars().all()
        confirmed_quantity = sum((allocation.allocated_quantity for allocation in allocations), Decimal("0"))
        if confirmed_quantity <= 0:
            raise ValueError("Every dispense item requires an active internal reservation")
        if confirmed_quantity > item.prescribed_quantity:
            raise ValueError("Reserved quantity exceeds prescribed quantity")
        if not allow_partial and confirmed_quantity != item.prescribed_quantity:
            raise ValueError("Full internal fulfillment requires complete reserved coverage")
        if allow_partial and confirmed_quantity >= item.prescribed_quantity:
            raise ValueError("Partial fulfillment requires less than the prescribed quantity")
        for allocation in allocations:
            allocation.confirmed_dispensed_quantity = allocation.allocated_quantity
        item.internal_confirmed_quantity = confirmed_quantity
        item.status = "PARTIAL" if confirmed_quantity < item.prescribed_quantity else "FULFILLED"

    dispense.fulfillment_mode = "PARTIAL_INTERNAL" if allow_partial else "FULL_INTERNAL"
    dispense.status = expected_status
    dispense.billing_status = "PENDING"
    dispense.ready_for_billing_at = datetime.now(timezone.utc)
    dispense.ready_for_billing_by = confirmed_by
    dispense.updated_by = confirmed_by
    await session.flush()
    return dispense


async def confirm_full_internal_fulfillment(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    confirmed_by: uuid.UUID,
) -> PharmacyDispense:
    return await _confirm_internal_fulfillment(
        session,
        dispense_id=dispense_id,
        tenant_id=tenant_id,
        facility_id=facility_id,
        confirmed_by=confirmed_by,
        allow_partial=False,
    )


async def confirm_partial_internal_fulfillment(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    confirmed_by: uuid.UUID,
) -> PharmacyDispense:
    return await _confirm_internal_fulfillment(
        session,
        dispense_id=dispense_id,
        tenant_id=tenant_id,
        facility_id=facility_id,
        confirmed_by=confirmed_by,
        allow_partial=True,
    )


async def confirm_outside_purchase_fulfillment(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    quantities: dict[uuid.UUID, Decimal],
    confirmed_by: uuid.UUID,
) -> PharmacyDispense:
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status not in {"VALIDATED", "RESERVED", "PARTIALLY_FULFILLED"}:
        raise ValueError("Pharmacy dispense is not awaiting fulfillment")
    prescription = await session.get(Prescription, dispense.prescription_id)
    if prescription is None or prescription.version != dispense.prescription_version:
        raise ValueError("Prescription version has changed")
    items = (await session.execute(select(PharmacyDispenseItem).where(
        PharmacyDispenseItem.dispense_id == dispense.id,
    ))).scalars().all()
    if not items:
        raise ValueError("Pharmacy dispense has no items")
    for item in items:
        outside_quantity = quantities.get(item.id, Decimal("0"))
        outside_quantity = Decimal(str(outside_quantity))
        if outside_quantity < 0:
            raise ValueError("Outside purchase quantity cannot be negative")
        remaining = item.prescribed_quantity - item.internal_confirmed_quantity - item.outside_purchase_quantity
        if outside_quantity > remaining:
            raise ValueError("Outside purchase quantity exceeds remaining prescription quantity")
        item.outside_purchase_quantity += outside_quantity
        total = item.internal_confirmed_quantity + item.outside_purchase_quantity
        item.status = "FULFILLED" if total == item.prescribed_quantity else "PARTIAL"
    fully_fulfilled = all(
        item.internal_confirmed_quantity + item.outside_purchase_quantity == item.prescribed_quantity
        for item in items
    )
    has_internal = any(item.internal_confirmed_quantity > 0 for item in items)
    dispense.status = "OUTSIDE_FULFILLED" if fully_fulfilled and not has_internal else (
        "PARTIALLY_FULFILLED" if not fully_fulfilled else "READY_FOR_BILLING"
    )
    dispense.fulfillment_mode = "OUTSIDE_PURCHASE" if not has_internal else "PARTIAL_MIXED"
    dispense.billing_status = "PENDING"
    dispense.updated_by = confirmed_by
    await session.flush()
    return dispense


async def approve_pharmacy_substitution(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    dispense_item_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    dispensed_medicine_product_id: uuid.UUID,
    substitution_reason: str,
    approved_by: uuid.UUID,
) -> PharmacyDispenseItem:
    if not substitution_reason.strip():
        raise ValueError("Substitution reason is required")
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status not in {"VALIDATED", "RESERVED", "PARTIALLY_FULFILLED"}:
        raise ValueError("Pharmacy dispense is not awaiting substitution")
    item = await session.scalar(select(PharmacyDispenseItem).where(
        PharmacyDispenseItem.id == dispense_item_id,
        PharmacyDispenseItem.dispense_id == dispense.id,
    ))
    if item is None:
        raise ValueError("Pharmacy dispense item not found")
    if item.no_substitution_applied:
        raise ValueError("Substitution is prohibited for this prescription item")
    if item.prescribed_medicine_product_id is None:
        raise ValueError("Substitution requires a product-based prescription")
    prescribed = await session.get(MedicineProduct, item.prescribed_medicine_product_id)
    replacement = await session.get(MedicineProduct, dispensed_medicine_product_id)
    if prescribed is None or replacement is None or not replacement.is_active:
        raise ValueError("Replacement medicine product is missing or inactive")
    if prescribed.id == replacement.id:
        raise ValueError("Replacement medicine must differ from prescribed medicine")
    if (
        prescribed.generic_medicine_id != replacement.generic_medicine_id
        or prescribed.strength != replacement.strength
        or prescribed.unit != replacement.unit
        or prescribed.dosage_form_id != replacement.dosage_form_id
        or prescribed.default_route_id != replacement.default_route_id
    ):
        raise ValueError("Replacement medicine is not clinically equivalent")
    eligible = await session.scalar(select(HospitalFormulary.id).where(
        HospitalFormulary.medicine_product_id == replacement.id,
        HospitalFormulary.is_active == True,  # noqa: E712
        HospitalFormulary.is_approved == True,  # noqa: E712
        HospitalFormulary.is_prescribable == True,  # noqa: E712
    ))
    if eligible is None:
        raise ValueError("Replacement medicine is not an approved prescribable formulary product")
    if prescribed.is_controlled_drug and not replacement.is_controlled_drug:
        raise ValueError("Controlled medicine cannot be substituted with a non-controlled product")
    item.dispensed_medicine_product_id = replacement.id
    item.substitution_flag = True
    item.substitution_reason = substitution_reason.strip()
    item.substitution_approved_by = approved_by
    item.substitution_approved_at = datetime.now(timezone.utc)
    item.updated_by = approved_by
    await session.flush()
    return item


async def validate_billable_dispense_quantities(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    requested_total_quantity: Decimal | float | int,
) -> Decimal:
    """Validate that declared billing quantity never exceeds confirmed hospital-supplied quantity."""
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")

    items = (await session.execute(select(PharmacyDispenseItem).where(
        PharmacyDispenseItem.dispense_id == dispense.id,
    ))).scalars().all()
    if not items:
        raise ValueError("Pharmacy dispense has no items")

    confirmed_total = sum((item.internal_confirmed_quantity for item in items), Decimal("0"))
    outside_total = sum((item.outside_purchase_quantity for item in items), Decimal("0"))
    requested_total = Decimal(str(requested_total_quantity))

    if requested_total <= 0:
        raise ValueError("Billing quantity must be positive")
    if requested_total > confirmed_total + Decimal("0.000001"):
        if outside_total > 0:
            raise ValueError("Outside-purchase quantities cannot be billed as hospital-supplied items")
        raise ValueError("Billable quantity exceeds confirmed hospital-supplied quantity")
    return confirmed_total


async def authorize_pharmacy_billing(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    confirmed_by: uuid.UUID | None,
    invoice_id: uuid.UUID | None = None,
) -> PharmacyDispense:
    """Server-trust payment completion as billing authorization without consuming stock."""
    dispense = await session.scalar(
        select(PharmacyDispense).where(
            PharmacyDispense.id == dispense_id,
            PharmacyDispense.tenant_id == tenant_id,
            PharmacyDispense.facility_id == facility_id,
        ).with_for_update()
    )
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status == "CONFIRMED":
        dispense.billing_status = "AUTHORIZED"
        return dispense
    if dispense.status not in {"READY_FOR_BILLING", "PARTIALLY_FULFILLED"}:
        raise ValueError("Pharmacy dispense is not ready for billing authorization")

    invoice = None
    if invoice_id is not None:
        invoice = await session.get(Invoice, invoice_id)
    elif dispense.invoice_id is not None:
        invoice = await session.get(Invoice, dispense.invoice_id)
    if invoice is None:
        raise ValueError("Pharmacy invoice is required before billing can be authorized")
    if invoice.status != "paid":
        raise ValueError("Pharmacy billing must be paid before it can be authorized")
    if float(invoice.paid_amount) < float(invoice.total):
        raise ValueError("Pharmacy billing must be fully paid before it can be authorized")

    dispense.billing_status = "AUTHORIZED"
    dispense.updated_by = confirmed_by
    await session.flush()
    return dispense


async def confirm_dispense_stock_consumption(
    session: AsyncSession,
    *,
    dispense_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    confirmed_by: uuid.UUID | None,
    billing_authorized: bool,
) -> PharmacyDispense:
    """Consume active reservations only after a paid, server-authorized billing state."""
    if not billing_authorized:
        raise ValueError("Billing authorization is required before stock consumption")

    dispense = await session.scalar(
        select(PharmacyDispense).where(
            PharmacyDispense.id == dispense_id,
            PharmacyDispense.tenant_id == tenant_id,
            PharmacyDispense.facility_id == facility_id,
        ).with_for_update()
    )
    if dispense is None:
        raise ValueError("Pharmacy dispense not found")
    if dispense.status == "CONFIRMED":
        dispense.billing_status = "AUTHORIZED"
        return dispense
    if dispense.status not in {"READY_FOR_BILLING", "PARTIALLY_FULFILLED"}:
        raise ValueError("Pharmacy dispense is not ready for confirmation")

    invoice = None
    if dispense.invoice_id is not None:
        invoice = await session.get(Invoice, dispense.invoice_id)

    if dispense.billing_status != "AUTHORIZED":
        if invoice is None:
            raise ValueError("Pharmacy dispense has not been server-authorized for stock consumption")
        if invoice.status != "paid":
            raise ValueError("Pharmacy invoice must be paid before stock can be consumed")
        if float(invoice.paid_amount) < float(invoice.total):
            raise ValueError("Pharmacy invoice must be fully paid before stock can be consumed")
        raise ValueError("Pharmacy dispense has not been server-authorized for stock consumption")

    if invoice is not None:
        if invoice.status != "paid":
            raise ValueError("Pharmacy invoice must be paid before stock can be consumed")
        if float(invoice.paid_amount) < float(invoice.total):
            raise ValueError("Pharmacy invoice must be fully paid before stock can be consumed")

    allocations = (await session.execute(
        select(PharmacyDispenseAllocation).where(
            PharmacyDispenseAllocation.dispense_item_id.in_(
                select(PharmacyDispenseItem.id).where(PharmacyDispenseItem.dispense_id == dispense.id)
            ),
            PharmacyDispenseAllocation.status == "RESERVED",
        ).order_by(PharmacyDispenseAllocation.inventory_batch_id).with_for_update()
    )).scalars().all()
    if not allocations and dispense.status == "PARTIALLY_FULFILLED":
        return dispense
    if not allocations:
        raise ValueError("Pharmacy dispense has no reserved allocations")

    reservations = (await session.execute(
        select(PharmacyStockReservation).where(
            PharmacyStockReservation.dispense_id == dispense.id,
            PharmacyStockReservation.status == "ACTIVE",
        ).order_by(PharmacyStockReservation.inventory_batch_id).with_for_update()
    )).scalars().all()
    reservations_by_batch = {reservation.inventory_batch_id: reservation for reservation in reservations}
    batch_ids = sorted({allocation.inventory_batch_id for allocation in allocations})
    batches = (await session.execute(
        select(InventoryBatch).where(
            InventoryBatch.id.in_(batch_ids),
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == dispense.pharmacy_location_id,
        ).order_by(InventoryBatch.id).with_for_update()
    )).scalars().all()
    batches_by_id = {batch.id: batch for batch in batches}
    for batch in batches:
        assert_inventory_batch_not_frozen(batch)

    for allocation in allocations:
        reservation = reservations_by_batch.get(allocation.inventory_batch_id)
        batch = batches_by_id.get(allocation.inventory_batch_id)
        quantity = allocation.confirmed_dispensed_quantity
        if reservation is None or batch is None or reservation.quantity < quantity:
            raise ValueError("Active reservation does not cover the confirmed allocation")
        if batch.status != "ACTIVE" or (batch.expiry_date is not None and batch.expiry_date < datetime.now(timezone.utc).date()):
            raise ValueError("Inventory batch is expired or inactive")
        if batch.status != "ACTIVE":
            raise ValueError("Recalled or inactive inventory batch cannot be dispensed")
        if batch.available_quantity < quantity or batch.reserved_quantity < quantity:
            raise ValueError("Insufficient reserved stock for confirmation")

        previous_balance = batch.available_quantity
        batch.available_quantity -= quantity
        batch.reserved_quantity -= quantity
        reservation.status = "CONSUMED"
        reservation.consumed_at = datetime.now(timezone.utc)
        reservation.consumed_by = confirmed_by
        allocation.status = "CONSUMED"
        existing_transaction = await session.scalar(select(StockTransaction).where(
            StockTransaction.reference_type == "pharmacy_dispense",
            StockTransaction.reference_id == allocation.id,
            StockTransaction.transaction_type == "DISPENSE",
        ))
        if existing_transaction is None:
            transaction = StockTransaction(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                facility_id=facility_id,
                pharmacy_location_id=batch.pharmacy_location_id,
                medicine_id=batch.medicine_id,
                inventory_batch_id=batch.id,
                transaction_type="DISPENSE",
                quantity=-quantity,
                previous_balance=previous_balance,
                new_balance=batch.available_quantity,
                reference_type="pharmacy_dispense",
                reference_id=allocation.id,
                reason="Confirmed pharmacy dispensing",
                performed_by=confirmed_by,
            )
            session.add(transaction)
            # Flush the transaction row first so FK assignment is always valid.
            await session.flush()
            allocation.stock_transaction_id = transaction.id
        else:
            allocation.stock_transaction_id = existing_transaction.id

    dispense.status = "CONFIRMED"
    dispense.billing_status = "AUTHORIZED"
    dispense.completed_at = datetime.now(timezone.utc)
    dispense.completed_by = confirmed_by
    dispense.updated_by = confirmed_by
    if dispense.pharmacy_queue_id is not None:
        queue = await session.scalar(select(PharmacyQueue).where(PharmacyQueue.id == dispense.pharmacy_queue_id))
        if queue is not None:
            queue.status = "dispensed" if dispense.status == "CONFIRMED" else "partially_dispensed"
            queue.dispensed_at = dispense.completed_at
    await session.flush()
    return dispense