from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from math import ceil
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.audit_log import AuditLog
from app.models.tenant.goods_receipt import GoodsReceipt
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.invoice import Invoice, Payment, Refund
from app.models.tenant.p31_p34 import CountDetail, PharmacyAlert, PharmacyAlertConfiguration, StockCount
from app.models.tenant.pharmacy_dispense import PharmacyDispense, PharmacyDispenseItem
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.returns import PatientReturn, PatientReturnItem, SupplierReturn
from app.models.tenant.stock_transaction import StockTransaction

_ACTIVE_INVENTORY_STATUSES = ("ACTIVE", "QUARANTINED")
_PENDING_DISPENSE_STATUSES = (
    "DRAFT", "VALIDATED", "RESERVED", "READY_FOR_BILLING", "BILLING_FAILED",
    "READY_TO_CONFIRM", "PARTIALLY_FULFILLED",
)

REPORT_NAMES = (
    "sales-payments", "dispensing", "purchase-grn", "patient-returns",
    "supplier-returns", "outside-purchases", "current-stock", "inventory-valuation",
    "reorder", "expiry", "stock-ledger", "stock-adjustments", "stock-count-variance",
    "inventory-movement", "alerts", "audit",
)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _resolved_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def business_window(timezone_name: str | None, business_date: date | None = None) -> tuple[date, datetime, datetime, str]:
    zone = _resolved_timezone(timezone_name)
    effective_date = business_date or datetime.now(zone).date()
    local_start = datetime.combine(effective_date, time.min, tzinfo=zone)
    return effective_date, local_start.astimezone(timezone.utc), (local_start + timedelta(days=1)).astimezone(timezone.utc), zone.key


async def validate_location(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    facility_id: UUID,
    pharmacy_location_id: UUID | None,
) -> None:
    if pharmacy_location_id is None:
        return
    exists = await session.scalar(select(PharmacyLocation.id).where(
        PharmacyLocation.id == pharmacy_location_id,
        PharmacyLocation.tenant_id == tenant_id,
        PharmacyLocation.facility_id == facility_id,
        PharmacyLocation.active.is_(True),
    ))
    if exists is None:
        raise HTTPException(status_code=404, detail="Pharmacy location not found")


def _location_filter(column, pharmacy_location_id: UUID | None):
    return column == pharmacy_location_id if pharmacy_location_id else None


async def dashboard_cards(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    facility_id: UUID,
    pharmacy_location_id: UUID | None,
    timezone_name: str | None,
    financial_data_visible: bool,
) -> dict[str, Any]:
    await validate_location(
        session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
    )
    business_date, start, end, resolved_timezone = business_window(timezone_name)
    dispense_scope = [
        PharmacyDispense.tenant_id == tenant_id,
        PharmacyDispense.facility_id == facility_id,
    ]
    inventory_scope = [
        InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id,
        InventoryBatch.status.in_(_ACTIVE_INVENTORY_STATUSES),
    ]
    transaction_scope = [
        StockTransaction.tenant_id == tenant_id,
        StockTransaction.facility_id == facility_id,
    ]
    if pharmacy_location_id:
        dispense_scope.append(PharmacyDispense.pharmacy_location_id == pharmacy_location_id)
        inventory_scope.append(InventoryBatch.pharmacy_location_id == pharmacy_location_id)
        transaction_scope.append(StockTransaction.pharmacy_location_id == pharmacy_location_id)

    sales_values = {"gross": Decimal("0"), "discount": Decimal("0"), "tax": Decimal("0"), "invoice_net": Decimal("0"), "refunds": Decimal("0"), "net_paid": Decimal("0")}
    if financial_data_visible:
        invoice_totals = (await session.execute(select(
            func.coalesce(func.sum(Invoice.subtotal), 0),
            func.coalesce(func.sum(Invoice.discount), 0),
            func.coalesce(func.sum(Invoice.tax), 0),
        ).join(PharmacyDispense, PharmacyDispense.id == Invoice.pharmacy_dispense_id).where(
            *dispense_scope,
            Invoice.status.not_in(("draft", "cancelled")),
            Invoice.created_at >= start,
            Invoice.created_at < end,
        ))).one()
        paid = await session.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).join(PharmacyDispense, PharmacyDispense.id == Invoice.pharmacy_dispense_id).where(
            *dispense_scope, Payment.status == "captured", Payment.paid_at >= start, Payment.paid_at < end,
        ))
        refunds = await session.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).join(
            Invoice, Invoice.id == Refund.invoice_id
        ).join(PharmacyDispense, PharmacyDispense.id == Invoice.pharmacy_dispense_id).where(
            *dispense_scope, Refund.status == "completed", Refund.refunded_at >= start, Refund.refunded_at < end,
        ))
        gross, discount, tax = map(_decimal, invoice_totals)
        refund_amount = _decimal(refunds)
        sales_values = {
            "gross": gross,
            "discount": discount,
            "tax": tax,
            "invoice_net": gross - discount + tax,
            "refunds": refund_amount,
            "net_paid": _decimal(paid) - refund_amount,
        }

    pending = await session.scalar(select(func.count()).select_from(PharmacyDispense).where(
        *dispense_scope, PharmacyDispense.status.in_(_PENDING_DISPENSE_STATUSES)
    )) or 0
    dispensed = (await session.execute(select(
        func.count(PharmacyDispense.id), func.coalesce(func.sum(PharmacyDispenseItem.internal_confirmed_quantity), 0)
    ).outerjoin(PharmacyDispenseItem, PharmacyDispenseItem.dispense_id == PharmacyDispense.id).where(
        *dispense_scope, PharmacyDispense.status == "CONFIRMED",
        PharmacyDispense.completed_at >= start, PharmacyDispense.completed_at < end,
    ))).one()

    grn_scope = [GoodsReceipt.facility_id == facility_id, GoodsReceipt.received_date == business_date, GoodsReceipt.status.in_(("PARTIALLY_RECEIVED", "FULLY_RECEIVED"))]
    if pharmacy_location_id:
        grn_scope.append(GoodsReceipt.pharmacy_location_id == pharmacy_location_id)
    purchases = (await session.execute(select(func.count(GoodsReceipt.id), func.coalesce(func.sum(GoodsReceipt.total_amount), 0)).where(*grn_scope))).one()

    patient_scope = [PatientReturn.tenant_id == tenant_id, PatientReturn.facility_id == facility_id, PatientReturn.status.in_(("ACCEPTED", "REFUNDED", "RESTOCKED", "NON_RESTOCKABLE")), PatientReturn.accepted_at >= start, PatientReturn.accepted_at < end]
    supplier_scope = [SupplierReturn.tenant_id == tenant_id, SupplierReturn.facility_id == facility_id, SupplierReturn.status.in_(("DISPATCHED", "RECEIVED")), SupplierReturn.dispatched_at >= start, SupplierReturn.dispatched_at < end]
    if pharmacy_location_id:
        patient_scope.append(PatientReturn.pharmacy_location_id == pharmacy_location_id)
        supplier_scope.append(SupplierReturn.pharmacy_location_id == pharmacy_location_id)
    patient_returns = (await session.execute(select(func.count(PatientReturn.id), func.coalesce(func.sum(PatientReturn.refunded_amount), 0)).where(*patient_scope))).one()
    supplier_returns = (await session.execute(select(func.count(SupplierReturn.id), func.coalesce(func.sum(SupplierReturn.total_return_value), 0)).where(*supplier_scope))).one()

    adjustment_condition = StockTransaction.transaction_type.in_(("ADJUSTMENT_IN", "ADJUSTMENT_OUT", "INWARD_ADJUSTMENT", "OUTWARD_ADJUSTMENT"))
    adjustments = (await session.execute(select(
        func.count(StockTransaction.id),
        func.coalesce(func.sum(func.abs(StockTransaction.quantity)), 0),
    ).where(*transaction_scope, adjustment_condition, StockTransaction.created_at >= start, StockTransaction.created_at < end))).one()

    config = await effective_configuration(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id)
    reorder_level = _decimal(config["reorder_level"])
    low_stock = await session.scalar(select(func.count()).select_from(InventoryBatch).where(
        *inventory_scope, InventoryBatch.available_quantity > 0, InventoryBatch.available_quantity <= reorder_level,
    )) or 0
    out_of_stock = await session.scalar(select(func.count()).select_from(InventoryBatch).where(
        *inventory_scope, InventoryBatch.available_quantity <= 0,
    )) or 0

    expiry_counts: dict[str, int] = {}
    for label, lower, upper in (("0_30", None, 30), ("31_60", 31, 60), ("61_90", 61, 90)):
        conditions = [*inventory_scope, InventoryBatch.available_quantity + InventoryBatch.reserved_quantity > 0, InventoryBatch.expiry_date <= business_date + timedelta(days=upper)]
        if lower is not None:
            conditions.append(InventoryBatch.expiry_date >= business_date + timedelta(days=lower))
        expiry_counts[label] = await session.scalar(select(func.count()).select_from(InventoryBatch).where(*conditions)) or 0

    valuations = (await session.execute(select(
        func.coalesce(func.sum(InventoryBatch.available_quantity * InventoryBatch.purchase_rate), 0),
        func.coalesce(func.sum(InventoryBatch.reserved_quantity * InventoryBatch.purchase_rate), 0),
        func.coalesce(func.sum((InventoryBatch.available_quantity + InventoryBatch.reserved_quantity) * InventoryBatch.purchase_rate), 0),
    ).where(*inventory_scope))).one()
    unvalued_quantity = await session.scalar(select(func.coalesce(func.sum(InventoryBatch.available_quantity + InventoryBatch.reserved_quantity), 0)).where(
        *inventory_scope, InventoryBatch.purchase_rate.is_(None)
    )) or 0
    outside = (await session.execute(select(
        func.count(PharmacyDispenseItem.id), func.coalesce(func.sum(PharmacyDispenseItem.outside_purchase_quantity), 0)
    ).join(PharmacyDispense, PharmacyDispense.id == PharmacyDispenseItem.dispense_id).where(
        *dispense_scope, PharmacyDispenseItem.outside_purchase_quantity > 0,
        PharmacyDispenseItem.updated_at >= start, PharmacyDispenseItem.updated_at < end,
    ))).one()

    generated_at = datetime.now(timezone.utc)
    return {
        "metadata": {
            "business_date": business_date,
            "timezone": resolved_timezone,
            "facility_id": facility_id,
            "pharmacy_location_id": pharmacy_location_id,
            "generated_at": generated_at,
            "currencies": ["INR"],
        },
        "financial_data_visible": financial_data_visible,
        "cards": {
            "sales": {"currency": "INR", **sales_values},
            "prescriptions_pending": pending,
            "dispensed_today": {"count": dispensed[0], "quantity": _decimal(dispensed[1])},
            "purchases_today": {"count": purchases[0], "value": _decimal(purchases[1]), "currency": "INR"},
            "patient_returns_today": {"count": patient_returns[0], "refund_value": _decimal(patient_returns[1]), "currency": "INR"},
            "supplier_returns_today": {"count": supplier_returns[0], "value": _decimal(supplier_returns[1]), "currency": "INR"},
            "stock_adjustments_today": {"count": adjustments[0], "quantity": _decimal(adjustments[1]), "value": None},
            "low_stock_items": low_stock,
            "out_of_stock_items": out_of_stock,
            "expiring_stock": expiry_counts,
            "inventory_valuation": {
                "available": _decimal(valuations[0]) if financial_data_visible else None,
                "reserved": _decimal(valuations[1]) if financial_data_visible else None,
                "quarantined": Decimal("0") if financial_data_visible else None,
                "total_physical": _decimal(valuations[2]) if financial_data_visible else None,
                "unvalued_quantity": _decimal(unvalued_quantity), "currency": "INR",
            },
            "outside_purchases": {"item_count": outside[0], "quantity": _decimal(outside[1])},
        },
    }


async def effective_configuration(session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, pharmacy_location_id: UUID | None) -> dict[str, Any]:
    scopes = []
    if pharmacy_location_id:
        scopes.append((f"location:{pharmacy_location_id}", "location"))
    scopes.extend(((f"facility:{facility_id}", "facility"), ("tenant", "tenant")))
    for scope_key, scope in scopes:
        row = await session.scalar(select(PharmacyAlertConfiguration).where(
            PharmacyAlertConfiguration.tenant_id == tenant_id,
            PharmacyAlertConfiguration.scope_key == scope_key,
        ))
        if row:
            return {
                "id": row.id, "tenant_id": tenant_id, "facility_id": row.facility_id,
                "pharmacy_location_id": row.pharmacy_location_id, "scope": scope,
                "effective_from": scope, "reorder_level": row.reorder_level,
                "expiry_horizon_days": row.expiry_horizon_days,
                "high_value_thresholds": row.high_value_thresholds,
                "quantity_percentage_threshold": row.quantity_percentage_threshold,
                "repeated_event_count": row.repeated_event_count, "lookback_days": row.lookback_days,
                "version": row.version, "updated_at": row.updated_at,
            }
    return {
        "id": None, "tenant_id": tenant_id, "facility_id": facility_id,
        "pharmacy_location_id": pharmacy_location_id, "scope": "default", "effective_from": "default",
        "reorder_level": Decimal("0"), "expiry_horizon_days": 90,
        "high_value_thresholds": {"INR": Decimal("5000.00")},
        "quantity_percentage_threshold": Decimal("10"), "repeated_event_count": 2,
        "lookback_days": 90, "version": 1, "updated_at": None,
    }


async def list_alerts(session: AsyncSession, *, tenant_id: UUID, facility_id: UUID, pharmacy_location_id: UUID | None, status: str | None, page: int, page_size: int) -> dict[str, Any]:
    conditions = [PharmacyAlert.tenant_id == tenant_id, PharmacyAlert.facility_id == facility_id]
    if pharmacy_location_id:
        conditions.append(PharmacyAlert.pharmacy_location_id == pharmacy_location_id)
    if status:
        conditions.append(PharmacyAlert.status == status)
    total = await session.scalar(select(func.count()).select_from(PharmacyAlert).where(*conditions)) or 0
    items = (await session.execute(select(PharmacyAlert).where(*conditions).order_by(PharmacyAlert.last_evaluated_at.desc(), PharmacyAlert.id).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _alert_key(alert_type: str, location_id: UUID, subject_key: str) -> str:
    return f"{alert_type}:{location_id}:{subject_key}"


async def recalculate_alerts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    facility_id: UUID,
    pharmacy_location_id: UUID | None,
    timezone_name: str | None,
) -> dict[str, int]:
    await validate_location(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id)
    configuration = await effective_configuration(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id)
    now = datetime.now(timezone.utc)
    business_date = datetime.now(_resolved_timezone(timezone_name)).date()
    reorder_level = _decimal(configuration["reorder_level"])
    horizon = int(configuration["expiry_horizon_days"])
    quantity_threshold = _decimal(configuration["quantity_percentage_threshold"])
    repeated_count = int(configuration["repeated_event_count"])
    lookback_start = now - timedelta(days=int(configuration["lookback_days"]))
    value_threshold = _decimal(configuration["high_value_thresholds"].get("INR", 5000))
    candidates: dict[str, dict[str, Any]] = {}

    inventory_conditions = [
        InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id,
        InventoryBatch.status.in_(_ACTIVE_INVENTORY_STATUSES),
    ]
    if pharmacy_location_id:
        inventory_conditions.append(InventoryBatch.pharmacy_location_id == pharmacy_location_id)
    inventory = (await session.execute(select(InventoryBatch).where(*inventory_conditions))).scalars().all()
    stock_by_subject: dict[tuple[UUID, UUID], Decimal] = {}
    for batch in inventory:
        stock_key = (batch.pharmacy_location_id, batch.medicine_id)
        stock_by_subject[stock_key] = stock_by_subject.get(stock_key, Decimal("0")) + _decimal(batch.available_quantity)
        physical_quantity = _decimal(batch.available_quantity) + _decimal(batch.reserved_quantity)
        if physical_quantity > 0 and batch.expiry_date and batch.expiry_date <= business_date + timedelta(days=horizon):
            days_remaining = (batch.expiry_date - business_date).days
            key = _alert_key("EXPIRY", batch.pharmacy_location_id, str(batch.id))
            candidates[key] = {
                "pharmacy_location_id": batch.pharmacy_location_id, "alert_type": "EXPIRY",
                "severity": "CRITICAL" if days_remaining <= 30 else "WARNING" if days_remaining <= 60 else "INFO",
                "subject_type": "inventory_batch", "subject_key": str(batch.id),
                "subject_data": {"medicine_id": str(batch.medicine_id), "batch_number": batch.batch_number},
                "title": f"{'Expired' if days_remaining < 0 else 'Expiring'} stock: {batch.batch_number}",
                "message": f"Batch {batch.batch_number} has {physical_quantity} units and {days_remaining} days remaining.",
                "condition_data": {"physical_quantity": str(physical_quantity), "expiry_date": batch.expiry_date.isoformat(), "days_remaining": days_remaining, "expired": days_remaining < 0},
            }
    for (location_id, medicine_id), available in stock_by_subject.items():
        alert_type = "OUT_OF_STOCK" if available <= 0 else "LOW_STOCK" if available <= reorder_level else None
        if alert_type:
            key = _alert_key(alert_type, location_id, str(medicine_id))
            candidates[key] = {
                "pharmacy_location_id": location_id, "alert_type": alert_type,
                "severity": "CRITICAL" if alert_type == "OUT_OF_STOCK" else "WARNING",
                "subject_type": "medicine_location", "subject_key": str(medicine_id),
                "subject_data": {"medicine_id": str(medicine_id)},
                "title": f"{alert_type.replace('_', ' ').title()}: {medicine_id}",
                "message": f"Available quantity is {available}; reorder level is {reorder_level}.",
                "condition_data": {"available_quantity": str(available), "reorder_level": str(reorder_level)},
            }

    transaction_conditions = [StockTransaction.tenant_id == tenant_id, StockTransaction.facility_id == facility_id, StockTransaction.created_at >= lookback_start, StockTransaction.transaction_type.in_(("STOCK_ADJUSTMENT", "ADJUSTMENT_IN", "ADJUSTMENT_OUT", "INWARD_ADJUSTMENT", "OUTWARD_ADJUSTMENT"))]
    if pharmacy_location_id:
        transaction_conditions.append(StockTransaction.pharmacy_location_id == pharmacy_location_id)
    adjustments = (await session.execute(select(StockTransaction, InventoryBatch.purchase_rate).outerjoin(InventoryBatch, InventoryBatch.id == StockTransaction.inventory_batch_id).where(*transaction_conditions))).all()
    for transaction, unit_cost in adjustments:
        quantity = abs(_decimal(transaction.quantity))
        value = quantity * _decimal(unit_cost)
        percentage = quantity * Decimal("100") / abs(_decimal(transaction.previous_balance)) if _decimal(transaction.previous_balance) else (Decimal("100") if quantity else Decimal("0"))
        if value >= value_threshold or percentage >= quantity_threshold:
            key = _alert_key("UNUSUAL_ADJUSTMENT", transaction.pharmacy_location_id, str(transaction.id))
            candidates[key] = {
                "pharmacy_location_id": transaction.pharmacy_location_id, "alert_type": "UNUSUAL_ADJUSTMENT", "severity": "WARNING",
                "subject_type": "stock_transaction", "subject_key": str(transaction.id),
                "subject_data": {"medicine_id": str(transaction.medicine_id), "batch_id": str(transaction.inventory_batch_id) if transaction.inventory_batch_id else None},
                "title": "Unusual stock adjustment", "message": f"Adjustment quantity {quantity} is {percentage:.3f}% of prior on-hand.",
                "condition_data": {"absolute_quantity": str(quantity), "absolute_value": str(value), "percentage": str(percentage), "currency": "INR"},
            }

    count_conditions = [StockCount.tenant_id == tenant_id, StockCount.facility_id == facility_id, StockCount.status == "APPLIED", StockCount.applied_at >= lookback_start, CountDetail.variance_quantity != 0]
    if pharmacy_location_id:
        count_conditions.append(StockCount.pharmacy_location_id == pharmacy_location_id)
    repeated = (await session.execute(select(StockCount.pharmacy_location_id, CountDetail.medicine_id, CountDetail.inventory_batch_id, CountDetail.batch_number, func.count(CountDetail.id)).join(CountDetail, CountDetail.count_id == StockCount.id).where(*count_conditions).group_by(StockCount.pharmacy_location_id, CountDetail.medicine_id, CountDetail.inventory_batch_id, CountDetail.batch_number).having(func.count(CountDetail.id) >= repeated_count))).all()
    for location_id, medicine_id, batch_id, batch_number, occurrences in repeated:
        key = _alert_key("REPEATED_VARIANCE", location_id, str(batch_id))
        candidates[key] = {
            "pharmacy_location_id": location_id, "alert_type": "REPEATED_VARIANCE", "severity": "WARNING",
            "subject_type": "inventory_batch", "subject_key": str(batch_id),
            "subject_data": {"medicine_id": str(medicine_id), "batch_number": batch_number},
            "title": f"Repeated count variance: {batch_number}", "message": f"Batch {batch_number} varied in {occurrences} applied counts.",
            "condition_data": {"occurrences": occurrences, "lookback_days": configuration["lookback_days"]},
        }

    return_conditions = [PatientReturn.tenant_id == tenant_id, PatientReturn.facility_id == facility_id, PatientReturn.status.in_(("ACCEPTED", "REFUND_PENDING", "REFUNDED", "RESTOCKED", "NON_RESTOCKABLE")), PatientReturn.accepted_at >= lookback_start]
    if pharmacy_location_id:
        return_conditions.append(PatientReturn.pharmacy_location_id == pharmacy_location_id)
    unusual_returns = (await session.execute(select(PatientReturn, func.coalesce(func.sum(PatientReturnItem.prescribed_quantity), 0)).join(PatientReturnItem, PatientReturnItem.return_id == PatientReturn.id).where(*return_conditions).group_by(PatientReturn.id))).all()
    for patient_return, prescribed_quantity in unusual_returns:
        percentage = _decimal(patient_return.total_return_quantity) * Decimal("100") / _decimal(prescribed_quantity) if _decimal(prescribed_quantity) else Decimal("0")
        if _decimal(patient_return.total_return_amount) >= value_threshold or percentage >= quantity_threshold:
            key = _alert_key("UNUSUAL_RETURN", patient_return.pharmacy_location_id, str(patient_return.id))
            candidates[key] = {
                "pharmacy_location_id": patient_return.pharmacy_location_id, "alert_type": "UNUSUAL_RETURN", "severity": "WARNING",
                "subject_type": "patient_return", "subject_key": str(patient_return.id),
                "subject_data": {"reference_key": patient_return.reference_key}, "title": f"Unusual patient return: {patient_return.reference_key}",
                "message": f"Return value is {patient_return.total_return_amount} INR and quantity is {percentage:.3f}% of prescribed.",
                "condition_data": {"return_value": str(patient_return.total_return_amount), "quantity_percentage": str(percentage), "currency": "INR"},
            }

    existing_conditions = [PharmacyAlert.tenant_id == tenant_id, PharmacyAlert.facility_id == facility_id, PharmacyAlert.active_subject_key.is_not(None)]
    if pharmacy_location_id:
        existing_conditions.append(PharmacyAlert.pharmacy_location_id == pharmacy_location_id)
    active_alerts = {alert.active_subject_key: alert for alert in (await session.execute(select(PharmacyAlert).where(*existing_conditions).with_for_update())).scalars()}
    created = updated = resolved = 0
    for key, values in candidates.items():
        alert = active_alerts.get(key)
        if alert:
            for field, value in values.items():
                setattr(alert, field, value)
            alert.last_evaluated_at = now
            updated += 1
            continue
        previous = await session.scalar(select(PharmacyAlert).where(
            PharmacyAlert.tenant_id == tenant_id, PharmacyAlert.facility_id == facility_id,
            PharmacyAlert.alert_type == values["alert_type"], PharmacyAlert.subject_key == values["subject_key"],
            PharmacyAlert.pharmacy_location_id == values["pharmacy_location_id"], PharmacyAlert.status == "RESOLVED",
        ).order_by(PharmacyAlert.resolved_at.desc()).limit(1))
        session.add(PharmacyAlert(tenant_id=tenant_id, facility_id=facility_id, active_subject_key=key, previous_alert_id=previous.id if previous else None, first_detected_at=now, last_evaluated_at=now, **values))
        created += 1
    for key, alert in active_alerts.items():
        if key not in candidates:
            alert.status = "RESOLVED"
            alert.active_subject_key = None
            alert.resolved_at = now
            alert.last_evaluated_at = now
            resolved += 1
    await session.flush()
    return {"created": created, "updated": updated, "resolved": resolved, "active": len(candidates)}


def _record(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


async def report_rows(
    session: AsyncSession,
    *,
    report: str,
    tenant_id: UUID,
    facility_id: UUID,
    pharmacy_location_id: UUID | None,
    timezone_name: str | None,
    start_date: date,
    end_date: date,
    page: int,
    page_size: int,
    medicine_id: UUID | None = None,
    batch_number: str | None = None,
    supplier_id: UUID | None = None,
    status: str | None = None,
    alert_type: str | None = None,
) -> dict[str, Any]:
    if report not in REPORT_NAMES:
        raise HTTPException(status_code=404, detail="Unknown Pharmacy report")
    if end_date < start_date or (end_date - start_date).days > 366:
        raise HTTPException(status_code=422, detail="Report date range must be between 0 and 366 days")
    await validate_location(session, tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=pharmacy_location_id)
    _, start, _, resolved_timezone = business_window(timezone_name, start_date)
    _, _, end, _ = business_window(timezone_name, end_date)

    applied_filters = {
        "start_date": start_date, "end_date": end_date,
        "pharmacy_location_id": pharmacy_location_id, "medicine_id": medicine_id,
        "batch_number": batch_number, "supplier_id": supplier_id,
        "status": status, "alert_type": alert_type,
    }

    if report == "inventory-movement":
        inventory_conditions = [InventoryBatch.tenant_id == tenant_id, InventoryBatch.facility_id == facility_id, InventoryBatch.status.in_(_ACTIVE_INVENTORY_STATUSES)]
        if pharmacy_location_id:
            inventory_conditions.append(InventoryBatch.pharmacy_location_id == pharmacy_location_id)
        if medicine_id:
            inventory_conditions.append(InventoryBatch.medicine_id == medicine_id)
        current_rows = (await session.execute(select(
            InventoryBatch.medicine_id,
            func.coalesce(func.sum(InventoryBatch.available_quantity + InventoryBatch.reserved_quantity), 0),
            func.coalesce(func.sum((InventoryBatch.available_quantity + InventoryBatch.reserved_quantity) * InventoryBatch.purchase_rate), 0),
        ).where(*inventory_conditions).group_by(InventoryBatch.medicine_id))).all()
        movement_conditions = [
            PharmacyDispense.tenant_id == tenant_id, PharmacyDispense.facility_id == facility_id,
            PharmacyDispense.status == "CONFIRMED", PharmacyDispense.completed_at >= end - timedelta(days=90), PharmacyDispense.completed_at < end,
        ]
        if pharmacy_location_id:
            movement_conditions.append(PharmacyDispense.pharmacy_location_id == pharmacy_location_id)
        movement_medicine = func.coalesce(PharmacyDispenseItem.dispensed_medicine_product_id, PharmacyDispenseItem.prescribed_medicine_product_id)
        if medicine_id:
            movement_conditions.append(movement_medicine == medicine_id)
        movement_rows = (await session.execute(select(
            movement_medicine.label("medicine_id"),
            func.coalesce(func.sum(PharmacyDispenseItem.internal_confirmed_quantity).filter(PharmacyDispense.completed_at >= end - timedelta(days=30)), 0),
            func.coalesce(func.sum(PharmacyDispenseItem.internal_confirmed_quantity), 0),
        ).join(PharmacyDispenseItem, PharmacyDispenseItem.dispense_id == PharmacyDispense.id).where(*movement_conditions).group_by(movement_medicine))).all()
        movements = {row[0]: (_decimal(row[1]), _decimal(row[2])) for row in movement_rows if row[0] is not None}
        moving = sorted(((item[0], movements.get(item[0], (Decimal("0"), Decimal("0")))[0], movements.get(item[0], (Decimal("0"), Decimal("0")))[1]) for item in current_rows if movements.get(item[0], (Decimal("0"), Decimal("0")))[1] > 0), key=lambda item: (-item[1], str(item[0])))
        boundary = ceil(len(moving) * 0.2) if moving else 0
        fast_ids = {item[0] for item in moving[:boundary]}
        slow_ids = {item[0] for item in sorted(moving, key=lambda item: (item[2], str(item[0])))[:boundary]}
        items = []
        for current in current_rows:
            qty_30, qty_90 = movements.get(current[0], (Decimal("0"), Decimal("0")))
            classification = "NON_MOVING" if qty_90 == 0 and _decimal(current[1]) > 0 else "FAST_MOVING" if current[0] in fast_ids else "SLOW_MOVING" if current[0] in slow_ids else "MOVING"
            items.append({
                "medicine_id": current[0], "classification": classification,
                "dispensed_quantity_30_days": qty_30, "dispensed_quantity_90_days": qty_90,
                "current_inventory_quantity": _decimal(current[1]), "inventory_value": _decimal(current[2]),
                "currency": "INR", "calculation_window_start": (end - timedelta(days=90)).date(), "calculation_window_end": end_date,
            })
        items.sort(key=lambda item: (item["classification"], str(item["medicine_id"])))
        total = len(items)
        items = items[(page - 1) * page_size:page * page_size]
        return {
            "report": report,
            "metadata": {"business_date": datetime.now(_resolved_timezone(timezone_name)).date(), "timezone": resolved_timezone, "facility_id": facility_id, "pharmacy_location_id": pharmacy_location_id, "generated_at": datetime.now(timezone.utc), "currencies": ["INR"]},
            "filters": applied_filters, "items": items, "total": total, "page": page, "page_size": page_size,
        }

    if report in {"sales-payments", "dispensing", "outside-purchases"}:
        model = PharmacyDispense
        conditions = [model.tenant_id == tenant_id, model.facility_id == facility_id, model.created_at >= start, model.created_at < end]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if medicine_id:
            conditions.append(select(PharmacyDispenseItem.id).where(PharmacyDispenseItem.dispense_id == model.id, func.coalesce(PharmacyDispenseItem.dispensed_medicine_product_id, PharmacyDispenseItem.prescribed_medicine_product_id) == medicine_id).exists())
        if status:
            conditions.append(model.status == status)
    elif report == "purchase-grn":
        model = GoodsReceipt
        conditions = [model.facility_id == facility_id, model.received_date >= start_date, model.received_date <= end_date]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if supplier_id:
            conditions.append(model.supplier_id == supplier_id)
        if status:
            conditions.append(model.status == status)
    elif report == "patient-returns":
        model = PatientReturn
        conditions = [model.tenant_id == tenant_id, model.facility_id == facility_id, model.requested_at >= start, model.requested_at < end]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if status:
            conditions.append(model.status == status)
    elif report == "supplier-returns":
        model = SupplierReturn
        conditions = [model.tenant_id == tenant_id, model.facility_id == facility_id, model.requested_at >= start, model.requested_at < end]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if supplier_id:
            conditions.append(model.supplier_id == supplier_id)
        if status:
            conditions.append(model.status == status)
    elif report in {"current-stock", "inventory-valuation", "reorder", "expiry", "inventory-movement"}:
        model = InventoryBatch
        conditions = [model.tenant_id == tenant_id, model.facility_id == facility_id]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if medicine_id:
            conditions.append(model.medicine_id == medicine_id)
        if batch_number:
            conditions.append(model.batch_number.ilike(f"%{batch_number}%"))
        if supplier_id:
            conditions.append(model.supplier_id == supplier_id)
        if status:
            conditions.append(model.status == status)
        if report == "expiry":
            conditions.extend((model.expiry_date <= end_date, model.available_quantity + model.reserved_quantity > 0))
    elif report in {"stock-ledger", "stock-adjustments"}:
        model = StockTransaction
        conditions = [model.tenant_id == tenant_id, model.facility_id == facility_id, model.created_at >= start, model.created_at < end]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if medicine_id:
            conditions.append(model.medicine_id == medicine_id)
        if status:
            conditions.append(model.transaction_type == status)
        if report == "stock-adjustments":
            conditions.append(model.transaction_type.in_(("STOCK_ADJUSTMENT", "ADJUSTMENT_IN", "ADJUSTMENT_OUT")))
    elif report == "stock-count-variance":
        model = CountDetail
        conditions = [
            CountDetail.count_id == StockCount.id,
            StockCount.tenant_id == tenant_id,
            StockCount.facility_id == facility_id,
            StockCount.created_at >= start,
            StockCount.created_at < end,
            CountDetail.variance_quantity.is_not(None),
        ]
        if pharmacy_location_id:
            conditions.append(StockCount.pharmacy_location_id == pharmacy_location_id)
        if medicine_id:
            conditions.append(CountDetail.medicine_id == medicine_id)
        if batch_number:
            conditions.append(CountDetail.batch_number.ilike(f"%{batch_number}%"))
    elif report == "alerts":
        model = PharmacyAlert
        conditions = [model.tenant_id == tenant_id, model.facility_id == facility_id, model.first_detected_at >= start, model.first_detected_at < end]
        if pharmacy_location_id:
            conditions.append(model.pharmacy_location_id == pharmacy_location_id)
        if alert_type:
            conditions.append(model.alert_type == alert_type)
        if status:
            conditions.append(model.status == status)
    else:
        model = AuditLog
        conditions = [
            model.timestamp >= start, model.timestamp < end,
            model.resource_type.ilike("%pharmacy%"),
            or_(
                model.new_value["facility_id"].as_string() == str(facility_id),
                model.request_metadata["facility_id"].as_string() == str(facility_id),
            ),
        ]
        if pharmacy_location_id:
            conditions.append(or_(
                model.new_value["pharmacy_location_id"].as_string() == str(pharmacy_location_id),
                model.request_metadata["pharmacy_location_id"].as_string() == str(pharmacy_location_id),
            ))

    base = select(model).where(*conditions)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    timestamp_column = getattr(model, "created_at", None) or getattr(model, "timestamp", None) or getattr(model, "id")
    rows = (await session.execute(base.order_by(timestamp_column.desc(), model.id).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "report": report,
        "metadata": {
            "business_date": datetime.now(_resolved_timezone(timezone_name)).date(),
            "timezone": resolved_timezone,
            "facility_id": facility_id,
            "pharmacy_location_id": pharmacy_location_id,
            "generated_at": datetime.now(timezone.utc),
            "currencies": ["INR"],
        },
        "filters": applied_filters,
        "items": [_record(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
