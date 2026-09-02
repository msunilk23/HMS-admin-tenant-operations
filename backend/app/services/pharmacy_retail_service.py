from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.public.user import User
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.p31_p34 import ProductRecall, RecallAffectedStock, StockQuarantine
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.pharmacy_retail_sale import (
    PharmacistLocationAuthorization,
    PharmacyRetailConfiguration,
    PharmacyRetailInvoice,
    PharmacyRetailPayment,
    PharmacyRetailReturn,
    PharmacyRetailReturnAllocation,
    PharmacyRetailSale,
    PharmacyRetailSaleAllocation,
    PharmacyRetailSaleItem,
)
from app.models.tenant.stock_transaction import StockTransaction
from app.schemas.pharmacy_retail import RetailReturnCreate, RetailSaleCreate, RetailSaleDispense
from app.services.audit_service import record_audit


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _request_hash(payload: RetailSaleCreate) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _payload_hash(payload) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def require_authorized_pharmacist(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    pharmacy_location_id: uuid.UUID,
) -> None:
    user = await session.scalar(select(User).where(
        User.id == user_id,
        User.tenant_id == tenant_id,
        User.role == "pharmacist",
        User.is_active.is_(True),
    ))
    authorization = await session.scalar(select(PharmacistLocationAuthorization.id).where(
        PharmacistLocationAuthorization.user_id == user_id,
        PharmacistLocationAuthorization.tenant_id == tenant_id,
        PharmacistLocationAuthorization.facility_id == facility_id,
        PharmacistLocationAuthorization.pharmacy_location_id == pharmacy_location_id,
        PharmacistLocationAuthorization.is_active.is_(True),
    ))
    if user is None or authorization is None:
        raise ValueError("Pharmacist is not active and authorized for this Pharmacy location")


async def retail_configuration(session: AsyncSession, tenant_id: uuid.UUID) -> PharmacyRetailConfiguration:
    configuration = await session.scalar(select(PharmacyRetailConfiguration).where(
        PharmacyRetailConfiguration.tenant_id == tenant_id,
    ))
    if configuration is None:
        configuration = PharmacyRetailConfiguration(tenant_id=tenant_id)
        session.add(configuration)
        await session.flush()
    return configuration


async def _active_location(
    session: AsyncSession, tenant_id: uuid.UUID, facility_id: uuid.UUID, location_id: uuid.UUID,
) -> PharmacyLocation:
    location = await session.scalar(select(PharmacyLocation).where(
        PharmacyLocation.id == location_id,
        PharmacyLocation.tenant_id == tenant_id,
        PharmacyLocation.facility_id == facility_id,
        PharmacyLocation.active.is_(True),
    ))
    if location is None:
        raise ValueError("Pharmacy location is missing, inactive, or outside the tenant facility")
    return location


def _prescribed_quantity(item) -> tuple[Decimal | None, int | None]:
    if item.prescribed_quantity is not None:
        return item.prescribed_quantity, item.duration_days
    if item.dose_units is None or item.frequency_per_day is None or item.duration_days is None:
        return None, item.duration_days
    return item.dose_units * item.frequency_per_day * Decimal(item.duration_days), item.duration_days


def _validate_external_identity(payload: RetailSaleCreate, controlled: bool) -> None:
    required = {
        "patient name": payload.patient_name,
        "patient date of birth or age": payload.patient_date_of_birth or payload.patient_age,
        "patient gender": payload.patient_gender,
        "patient mobile": payload.patient_mobile,
        "prescriber name": payload.prescriber_name,
        "prescriber registration number": payload.prescriber_registration_number,
        "prescription date": payload.prescription_date,
        "issuing facility": payload.issuing_facility,
        "prescription reference": payload.prescription_reference,
    }
    missing = [name for name, value in required.items() if value in (None, "")]
    if missing:
        raise ValueError(f"External prescription requires {', '.join(missing)}")
    if controlled:
        controlled_required = {
            "registered patient": payload.patient_id,
            "patient address": payload.patient_address,
            "government ID type": payload.government_id_type,
            "government ID last four": payload.government_id_last_four,
            "prescription attachment": payload.prescription_attachment_reference,
        }
        missing = [name for name, value in controlled_required.items() if value in (None, "")]
        if missing or not payload.original_prescription_inspected:
            details = missing + ([] if payload.original_prescription_inspected else ["original prescription inspection"])
            raise ValueError(f"Controlled external prescription requires {', '.join(details)}")


async def _eligible_batches(
    session: AsyncSession,
    *,
    product_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    location_id: uuid.UUID,
    lock: bool,
) -> list[InventoryBatch]:
    quarantined = exists(select(StockQuarantine.id).where(
        StockQuarantine.inventory_batch_id == InventoryBatch.id,
        StockQuarantine.status == "QUARANTINED",
        StockQuarantine.remaining_quantity > 0,
    ))
    recalled = exists(select(RecallAffectedStock.id).join(
        ProductRecall, ProductRecall.id == RecallAffectedStock.recall_id,
    ).where(
        RecallAffectedStock.inventory_batch_id == InventoryBatch.id,
        ProductRecall.status == "ACTIVE",
    ))
    stmt = select(InventoryBatch).where(
        InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id,
        InventoryBatch.pharmacy_location_id == location_id,
        InventoryBatch.medicine_id == product_id,
        InventoryBatch.status == "ACTIVE",
        InventoryBatch.available_quantity > 0,
        InventoryBatch.expiry_date.is_not(None),
        InventoryBatch.expiry_date >= date.today(),
        ~quarantined,
        ~recalled,
    ).order_by(InventoryBatch.expiry_date.asc(), InventoryBatch.id.asc())
    if lock:
        stmt = stmt.with_for_update()
    return list((await session.execute(stmt)).scalars().all())


async def search_retail_medicines(
    session: AsyncSession,
    *,
    query: str,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    location_id: uuid.UUID,
) -> list[dict]:
    products = list((await session.execute(
        select(MedicineProduct, GenericMedicine).join(
            GenericMedicine, GenericMedicine.id == MedicineProduct.generic_medicine_id,
        ).where(
            MedicineProduct.is_active.is_(True),
            (MedicineProduct.code.ilike(f"%{query}%") | MedicineProduct.brand_name.ilike(f"%{query}%") | GenericMedicine.name.ilike(f"%{query}%")),
        ).order_by(MedicineProduct.brand_name.asc().nulls_last(), GenericMedicine.name.asc()).limit(30)
    )).all())
    results = []
    for product, generic in products:
        batches = await _eligible_batches(
            session, product_id=product.id, tenant_id=tenant_id, facility_id=facility_id,
            location_id=location_id, lock=False,
        )
        if not batches or any(batch.mrp is None for batch in batches):
            continue
        results.append({
            "id": product.id, "code": product.code, "name": product.brand_name or generic.name,
            "strength": product.strength, "requires_prescription": product.requires_prescription,
            "is_controlled_drug": product.is_controlled_drug,
            "available_quantity": sum((batch.available_quantity for batch in batches), Decimal("0")),
            "unit_price": batches[0].mrp, "gst_rate": product.gst_rate or Decimal("0"),
        })
    return results


async def create_retail_sale(
    session: AsyncSession,
    *,
    payload: RetailSaleCreate,
    idempotency_key: str,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    current_user: dict,
) -> PharmacyRetailSale:
    await require_authorized_pharmacist(
        session, user_id=actor_id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=payload.pharmacy_location_id,
    )
    await _active_location(session, tenant_id, facility_id, payload.pharmacy_location_id)
    request_hash = _request_hash(payload)
    existing = await session.scalar(select(PharmacyRetailSale).where(
        PharmacyRetailSale.tenant_id == tenant_id,
        PharmacyRetailSale.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("Idempotency key was already used with a different retail sale request")
        return existing

    product_rows: list[tuple[MedicineProduct, object, Decimal, int | None]] = []
    controlled_sale = False
    for requested_item in payload.items:
        product = await session.get(MedicineProduct, requested_item.medicine_product_id)
        if product is None or not product.is_active:
            raise ValueError("Medicine product is missing or inactive")
        prescribed_quantity, duration_days = _prescribed_quantity(requested_item)
        if payload.classification == "OTC" and (product.requires_prescription or product.is_controlled_drug):
            raise ValueError("Prescription-only and controlled medicines cannot use the OTC path")
        if payload.classification == "EXTERNAL_PRESCRIPTION":
            if prescribed_quantity is None:
                raise ValueError("Prescribed quantity is required or must be unambiguously calculable")
            if requested_item.quantity > prescribed_quantity:
                raise ValueError("Dispensed quantity cannot exceed prescribed quantity")
            if product.is_controlled_drug and requested_item.quantity != prescribed_quantity:
                raise ValueError("Controlled medicine quantity must exactly match the prescribed quantity")
        controlled_sale = controlled_sale or product.is_controlled_drug
        product_rows.append((product, requested_item, prescribed_quantity, duration_days))

    if payload.classification == "EXTERNAL_PRESCRIPTION":
        _validate_external_identity(payload, controlled_sale)
        configuration = await retail_configuration(session, tenant_id)
        validity_days = configuration.controlled_validity_days if controlled_sale else configuration.non_controlled_validity_days
        max_supply_days = configuration.controlled_max_supply_days if controlled_sale else configuration.non_controlled_max_supply_days
        if payload.prescription_date > date.today():
            raise ValueError("Prescription date cannot be in the future")
        if (date.today() - payload.prescription_date).days > validity_days:
            raise ValueError("External prescription has expired")
        for _, _, _, duration_days in product_rows:
            if duration_days is None or duration_days > max_supply_days:
                raise ValueError(f"Prescribed duration must be explicit and no more than {max_supply_days} days")

    if payload.patient_id is not None and await session.get(Patient, payload.patient_id) is None:
        raise ValueError("Registered patient was not found")

    sale = PharmacyRetailSale(
        tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=payload.pharmacy_location_id,
        classification=payload.classification, status="PENDING_VERIFICATION" if payload.classification == "EXTERNAL_PRESCRIPTION" else "DRAFT",
        controlled_sale=controlled_sale, patient_id=payload.patient_id,
        customer_reference=f"WALKIN-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        patient_name=payload.patient_name, patient_date_of_birth=payload.patient_date_of_birth, patient_age=payload.patient_age,
        patient_gender=payload.patient_gender, patient_mobile=payload.patient_mobile, patient_address=payload.patient_address,
        government_id_type=payload.government_id_type, government_id_last_four=payload.government_id_last_four,
        prescriber_name=payload.prescriber_name, prescriber_registration_number=payload.prescriber_registration_number,
        prescription_date=payload.prescription_date, issuing_facility=payload.issuing_facility,
        prescription_reference=payload.prescription_reference,
        prescription_attachment_reference=payload.prescription_attachment_reference,
        original_prescription_inspected=payload.original_prescription_inspected,
        idempotency_key=idempotency_key, request_hash=request_hash, created_by=actor_id,
    )
    session.add(sale)
    await session.flush()
    for product, requested_item, prescribed_quantity, duration_days in product_rows:
        generic = await session.get(GenericMedicine, product.generic_medicine_id)
        batches = await _eligible_batches(
            session, product_id=product.id, tenant_id=tenant_id, facility_id=facility_id,
            location_id=payload.pharmacy_location_id, lock=False,
        )
        if not batches or sum((batch.available_quantity for batch in batches), Decimal("0")) < requested_item.quantity:
            raise ValueError("Insufficient eligible stock for the complete sale")
        if any(batch.mrp is None for batch in batches):
            raise ValueError("Eligible stock has no server-side selling price")
        unit_price = batches[0].mrp
        subtotal = _money(requested_item.quantity * unit_price)
        gst_rate = product.gst_rate or Decimal("0")
        tax = _money(subtotal * gst_rate / Decimal("100"))
        session.add(PharmacyRetailSaleItem(
            sale_id=sale.id, medicine_product_id=product.id,
            medicine_name_snapshot=product.brand_name or (generic.name if generic else product.code),
            quantity=requested_item.quantity, prescribed_quantity=prescribed_quantity,
            prescribed_duration_days=duration_days, requires_prescription=product.requires_prescription,
            is_controlled_drug=product.is_controlled_drug, unit_price=unit_price, gst_rate=gst_rate,
            line_subtotal=subtotal, line_tax=tax, line_total=subtotal + tax,
        ))
    record_audit(
        session, current_user=current_user, action="CREATE", resource_type="pharmacy_retail_sale", resource_id=sale.id,
        patient_id=sale.patient_id, new_value={"classification": sale.classification, "status": sale.status, "controlled_sale": sale.controlled_sale},
    )
    await session.commit()
    return sale


async def verify_external_sale(
    session: AsyncSession,
    *,
    sale_id: uuid.UUID,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    current_user: dict,
) -> PharmacyRetailSale:
    sale = await session.scalar(select(PharmacyRetailSale).where(
        PharmacyRetailSale.id == sale_id, PharmacyRetailSale.tenant_id == tenant_id,
        PharmacyRetailSale.facility_id == facility_id,
    ).with_for_update())
    if sale is None:
        raise ValueError("Retail sale not found")
    await require_authorized_pharmacist(
        session, user_id=actor_id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=sale.pharmacy_location_id,
    )
    if sale.classification != "EXTERNAL_PRESCRIPTION" or sale.status != "PENDING_VERIFICATION":
        raise ValueError("External prescription is not awaiting verification")
    sale.verified_by = actor_id
    sale.verified_at = datetime.now(timezone.utc)
    sale.status = "VERIFIED"
    record_audit(
        session, current_user=current_user, action="VERIFY", resource_type="pharmacy_retail_sale", resource_id=sale.id,
        patient_id=sale.patient_id, old_value={"status": "PENDING_VERIFICATION"},
        new_value={"status": "VERIFIED", "verified_by": str(actor_id), "controlled_sale": sale.controlled_sale},
    )
    await session.commit()
    return sale


async def dispense_retail_sale(
    session: AsyncSession,
    *,
    sale_id: uuid.UUID,
    payload: RetailSaleDispense,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    current_user: dict,
) -> PharmacyRetailSale:
    sale = await session.scalar(select(PharmacyRetailSale).where(
        PharmacyRetailSale.id == sale_id, PharmacyRetailSale.tenant_id == tenant_id,
        PharmacyRetailSale.facility_id == facility_id,
    ).with_for_update())
    if sale is None:
        raise ValueError("Retail sale not found")
    await require_authorized_pharmacist(
        session, user_id=actor_id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=sale.pharmacy_location_id,
    )
    if sale.status == "FULLY_DISPENSED":
        return sale
    required_status = "VERIFIED" if sale.classification == "EXTERNAL_PRESCRIPTION" else "DRAFT"
    if sale.status != required_status:
        raise ValueError("Retail sale is not eligible for dispensing")
    if sale.controlled_sale and sale.verified_by == actor_id:
        raise ValueError("Controlled external prescriptions require a different dispensing Pharmacist")
    transaction_reference = payload.payment_reference or f"CASH-{sale.id}"
    duplicate_payment = await session.scalar(select(PharmacyRetailPayment.id).where(
        PharmacyRetailPayment.tenant_id == tenant_id,
        PharmacyRetailPayment.transaction_reference == transaction_reference,
    ))
    if duplicate_payment is not None:
        raise ValueError("Payment reference has already been captured")

    items = list((await session.execute(select(PharmacyRetailSaleItem).where(
        PharmacyRetailSaleItem.sale_id == sale.id,
    ))).scalars().all())
    sale_subtotal = Decimal("0")
    sale_tax = Decimal("0")
    for item in items:
        product = await session.get(MedicineProduct, item.medicine_product_id)
        if product is None or not product.is_active:
            raise ValueError("Medicine product became inactive before dispensing")
        if sale.classification == "OTC" and (product.requires_prescription or product.is_controlled_drug):
            raise ValueError("Medicine is no longer eligible for OTC dispensing")
        batches = await _eligible_batches(
            session, product_id=product.id, tenant_id=tenant_id, facility_id=facility_id,
            location_id=sale.pharmacy_location_id, lock=True,
        )
        remaining = item.quantity
        line_subtotal = Decimal("0")
        for batch in batches:
            if remaining <= 0:
                break
            if batch.mrp is None:
                raise ValueError("Eligible stock has no server-side selling price")
            quantity = min(remaining, batch.available_quantity)
            previous_balance = batch.available_quantity
            batch.available_quantity -= quantity
            allocation_id = uuid.uuid4()
            transaction = StockTransaction(
                tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=sale.pharmacy_location_id,
                medicine_id=item.medicine_product_id, inventory_batch_id=batch.id, transaction_type="RETAIL_DISPENSE",
                quantity=-quantity, previous_balance=previous_balance, new_balance=batch.available_quantity,
                reference_type="PHARMACY_RETAIL_ALLOCATION", reference_id=allocation_id,
                correlation_reference=sale.customer_reference, reason=sale.classification, performed_by=actor_id,
            )
            session.add(transaction)
            await session.flush()
            session.add(PharmacyRetailSaleAllocation(
                id=allocation_id,
                sale_item_id=item.id, inventory_batch_id=batch.id, quantity=quantity,
                unit_price=batch.mrp, stock_transaction_id=transaction.id,
            ))
            line_subtotal += quantity * batch.mrp
            remaining -= quantity
        if remaining > 0:
            raise ValueError("Insufficient eligible stock for the complete sale")
        item.unit_price = _money(line_subtotal / item.quantity)
        item.line_subtotal = _money(line_subtotal)
        item.line_tax = _money(item.line_subtotal * item.gst_rate / Decimal("100"))
        item.line_total = item.line_subtotal + item.line_tax
        sale_subtotal += item.line_subtotal
        sale_tax += item.line_tax

    sale.subtotal = _money(sale_subtotal)
    sale.tax = _money(sale_tax)
    sale.discount = Decimal("0")
    sale.total = sale.subtotal + sale.tax
    sale.payment_method = payload.payment_method
    sale.payment_reference = payload.payment_reference
    sale.payment_status = "PAID"
    sale.dispensed_by = actor_id
    sale.dispensed_at = datetime.now(timezone.utc)
    sale.status = "FULLY_DISPENSED"
    sale.receipt_number = f"RTL-{sale.dispensed_at:%Y%m%d}-{sale.id.hex[:8].upper()}"
    invoice = PharmacyRetailInvoice(
        sale_id=sale.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=sale.pharmacy_location_id, invoice_number=sale.receipt_number,
        classification=sale.classification, subtotal=sale.subtotal, tax=sale.tax,
        discount=sale.discount, total=sale.total, status="PAID",
    )
    session.add(invoice)
    await session.flush()
    session.add(PharmacyRetailPayment(
        invoice_id=invoice.id, tenant_id=tenant_id, amount=sale.total,
        payment_method=payload.payment_method, transaction_reference=transaction_reference,
        status="CAPTURED", paid_at=sale.dispensed_at,
    ))
    record_audit(
        session, current_user=current_user, action="DISPENSE", resource_type="pharmacy_retail_sale", resource_id=sale.id,
        patient_id=sale.patient_id, old_value={"status": required_status, "payment_status": "PENDING"},
        new_value={
            "status": sale.status, "payment_status": sale.payment_status, "classification": sale.classification,
            "subtotal": str(sale.subtotal), "tax": str(sale.tax), "total": str(sale.total),
            "verified_by": str(sale.verified_by) if sale.verified_by else None, "dispensed_by": str(actor_id),
        },
    )
    await session.commit()
    return sale


async def return_retail_sale(
    session: AsyncSession,
    *,
    sale_id: uuid.UUID,
    payload: RetailReturnCreate,
    idempotency_key: str,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    current_user: dict,
) -> PharmacyRetailReturn:
    request_hash = _payload_hash(payload)
    existing = await session.scalar(select(PharmacyRetailReturn).where(
        PharmacyRetailReturn.tenant_id == tenant_id,
        PharmacyRetailReturn.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.request_hash != request_hash or existing.sale_id != sale_id:
            raise ValueError("Idempotency key was already used with a different retail return request")
        return existing

    sale = await session.scalar(select(PharmacyRetailSale).where(
        PharmacyRetailSale.id == sale_id,
        PharmacyRetailSale.tenant_id == tenant_id,
        PharmacyRetailSale.facility_id == facility_id,
    ).with_for_update())
    if sale is None or sale.status != "FULLY_DISPENSED" or sale.payment_status not in {"PAID", "REFUNDED"}:
        raise ValueError("A paid, fully dispensed retail sale is required")
    await require_authorized_pharmacist(
        session, user_id=actor_id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=sale.pharmacy_location_id,
    )
    invoice = await session.scalar(select(PharmacyRetailInvoice).where(
        PharmacyRetailInvoice.sale_id == sale.id,
        PharmacyRetailInvoice.tenant_id == tenant_id,
        PharmacyRetailInvoice.facility_id == facility_id,
    ).with_for_update())
    if invoice is None:
        raise ValueError("Retail invoice linkage was not found")
    payment = await session.scalar(select(PharmacyRetailPayment).where(
        PharmacyRetailPayment.invoice_id == invoice.id,
        PharmacyRetailPayment.tenant_id == tenant_id,
    ).with_for_update())
    if payment is None:
        raise ValueError("Captured retail payment was not found")

    requested = {item.sale_allocation_id: item.quantity for item in payload.allocations}
    if len(requested) != len(payload.allocations):
        raise ValueError("Each original sale allocation may be returned only once per request")
    rows = list((await session.execute(
        select(PharmacyRetailSaleAllocation, PharmacyRetailSaleItem)
        .join(PharmacyRetailSaleItem, PharmacyRetailSaleItem.id == PharmacyRetailSaleAllocation.sale_item_id)
        .where(
            PharmacyRetailSaleItem.sale_id == sale.id,
            PharmacyRetailSaleAllocation.id.in_(requested),
        )
        .order_by(PharmacyRetailSaleAllocation.inventory_batch_id, PharmacyRetailSaleAllocation.id)
        .with_for_update()
    )).all())
    if len(rows) != len(requested):
        raise ValueError("A return allocation does not belong to this retail sale")

    prepared = []
    total_quantity = Decimal("0")
    refund_amount = Decimal("0")
    for allocation, item in rows:
        prior = await session.scalar(
            select(func.coalesce(func.sum(PharmacyRetailReturnAllocation.quantity), Decimal("0")))
            .where(PharmacyRetailReturnAllocation.sale_allocation_id == allocation.id)
        )
        quantity = requested[allocation.id]
        if Decimal(str(prior or 0)) + quantity > allocation.quantity:
            raise ValueError("Return quantity exceeds the remaining quantity from its original batch allocation")
        line_subtotal = _money(quantity * allocation.unit_price)
        line_refund = line_subtotal + _money(line_subtotal * item.gst_rate / Decimal("100"))
        prepared.append((allocation, item, quantity, line_refund))
        total_quantity += quantity
        refund_amount += line_refund
    refund_amount = _money(refund_amount)
    if invoice.refunded_amount + refund_amount > invoice.total:
        raise ValueError("Refund amount exceeds the original retail invoice total")

    now = datetime.now(timezone.utc)
    retail_return = PharmacyRetailReturn(
        sale_id=sale.id, invoice_id=invoice.id, tenant_id=tenant_id, facility_id=facility_id,
        pharmacy_location_id=sale.pharmacy_location_id,
        return_number=f"RTR-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        classification=sale.classification, status="REFUNDED", reason=payload.reason.strip(),
        total_quantity=total_quantity, refund_amount=refund_amount,
        idempotency_key=idempotency_key, request_hash=request_hash,
        processed_by=actor_id, processed_at=now,
    )
    session.add(retail_return)
    await session.flush()
    for allocation, item, quantity, line_refund in prepared:
        batch = await session.scalar(select(InventoryBatch).where(
            InventoryBatch.id == allocation.inventory_batch_id,
            InventoryBatch.tenant_id == tenant_id,
            InventoryBatch.facility_id == facility_id,
            InventoryBatch.pharmacy_location_id == sale.pharmacy_location_id,
        ).with_for_update())
        if batch is None:
            raise ValueError("Original retail batch is outside the authenticated scope")
        previous_balance = batch.available_quantity
        batch.available_quantity += quantity
        return_allocation_id = uuid.uuid4()
        transaction = StockTransaction(
            tenant_id=tenant_id, facility_id=facility_id, pharmacy_location_id=sale.pharmacy_location_id,
            medicine_id=item.medicine_product_id, inventory_batch_id=batch.id,
            transaction_type="PATIENT_RETURN_RESTOCK", quantity=quantity,
            previous_balance=previous_balance, new_balance=batch.available_quantity,
            reference_type="PHARMACY_RETAIL_RETURN_ALLOCATION", reference_id=return_allocation_id,
            correlation_reference=retail_return.return_number, reason=payload.reason.strip(), performed_by=actor_id,
        )
        session.add(transaction)
        await session.flush()
        session.add(PharmacyRetailReturnAllocation(
            id=return_allocation_id, return_id=retail_return.id, sale_allocation_id=allocation.id,
            inventory_batch_id=batch.id, quantity=quantity, refund_amount=line_refund,
            stock_transaction_id=transaction.id,
        ))

    invoice.refunded_amount += refund_amount
    fully_refunded = invoice.refunded_amount == invoice.total
    invoice.status = "REFUNDED" if fully_refunded else "PARTIALLY_REFUNDED"
    payment.status = "REFUNDED" if fully_refunded else "PARTIALLY_REFUNDED"
    if fully_refunded:
        sale.payment_status = "REFUNDED"
    record_audit(
        session, current_user=current_user, action="REFUND", resource_type="pharmacy_retail_return",
        resource_id=retail_return.id, patient_id=sale.patient_id, reason=payload.reason.strip(),
        new_value={
            "sale_id": str(sale.id), "invoice_id": str(invoice.id), "classification": sale.classification,
            "return_number": retail_return.return_number, "quantity": str(total_quantity),
            "refund_amount": str(refund_amount), "invoice_status": invoice.status,
        },
    )
    await session.commit()
    return retail_return