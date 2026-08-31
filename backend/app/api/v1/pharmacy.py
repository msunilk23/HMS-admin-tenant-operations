"""
Pharmacy Queue API — dispense prescribed medicines to patients.
"""
import json
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_facility_id
from app.core.config import settings
from app.core.dependencies import ensure_feature_enabled, require_permission, require_role, require_feature
from app.core.pdf_service import generate_and_upload_prescription_pdf
from app.core.razorpay_service import create_razorpay_order
from app.core.sms import send_prescription_whatsapp
from app.db.engine import get_session
from app.models.tenant.consultation import Consultation
from app.models.tenant.department import Department
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.doctor import Doctor
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.goods_receipt import GoodsReceipt, GoodsReceiptItem
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.invoice import Invoice
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_dispense import PharmacyDispense, PharmacyDispenseItem
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.prescription import Prescription
from app.models.tenant.route import Route
from app.models.tenant.supplier import Supplier
from app.models.tenant.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.invoice import InvoiceRead, PharmacyBillCreate
from app.schemas.pharmacy import FormularyMedicineSearchResult, OutsidePurchaseCreate, PharmacyAllocationRequest, PharmacyDispenseConfirm, PharmacyDispenseItemRead, PharmacyDispenseRead, PharmacyDispenseStart, PharmacyQueueRead, PharmacyReservationRead, PharmacyReservationRelease, PharmacyStatusUpdate, PharmacySubstitutionCreate, SupplierCreate, SupplierImportItem, SupplierRead, SupplierUpdate
from app.schemas.purchase_order import PurchaseOrderCreate, PurchaseOrderRead, PurchaseOrderUpdate
from app.schemas.goods_receipt import GoodsReceiptCreate, GoodsReceiptItemCreate, GoodsReceiptItemRead, GoodsReceiptRead
from app.schemas.inventory import InventoryBalanceRead, InventoryBatchRead, InventoryReconciliationRead, PharmacyLocationRead, StockAdjustmentCreate, StockTransactionRead
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.stock_transaction import StockTransaction
from app.services.inventory_service import get_fefo_batches_for_medicine, get_location_medicine_balance, reconcile_inventory_batch
from app.services.inventory_service import create_inventory_from_grn_item, record_stock_adjustment
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.websocket.manager import ws_manager
from app.services.audit_service import record_audit
from app.services.pharmacy_dispensing import approve_pharmacy_substitution, authorize_pharmacy_billing, confirm_dispense_stock_consumption, confirm_full_internal_fulfillment, confirm_outside_purchase_fulfillment, confirm_partial_internal_fulfillment, create_stock_reservations, prepare_billable_pharmacy_line_items, propose_pharmacy_allocations, release_dispense_reservations, release_stock_reservation, resolve_billable_pharmacy_line_items, start_pharmacy_dispense, validate_billable_dispense_quantities, validate_pharmacy_dispense

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_feature("pharmacy"))])

_PO_TRANSITIONS = {
    "DRAFT": {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"APPROVED", "REJECTED", "CANCELLED"},
    "APPROVED": {"SENT", "CANCELLED"},
    "SENT": {"PARTIALLY_RECEIVED", "FULLY_RECEIVED", "CANCELLED"},
    "PARTIALLY_RECEIVED": {"FULLY_RECEIVED", "CANCELLED"},
    "FULLY_RECEIVED": {"CLOSED"},
    "REJECTED": set(),
    "CANCELLED": set(),
    "CLOSED": set(),
}

_GRN_TRANSITIONS = {
    "DRAFT": {"PARTIALLY_RECEIVED", "FULLY_RECEIVED", "REJECTED", "CANCELLED"},
    "PARTIALLY_RECEIVED": set(),
    "FULLY_RECEIVED": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _validate_po_references(session: AsyncSession, payload: PurchaseOrderCreate | PurchaseOrderUpdate) -> Supplier:
    supplier = await session.get(Supplier, payload.supplier_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(status_code=422, detail="Supplier is missing or inactive")
    if payload.items is not None:
        for item in payload.items:
            product = await session.get(MedicineProduct, item.medicine_product_id)
            if not product or not product.is_active:
                raise HTTPException(status_code=422, detail="Medicine product is missing or inactive")
    return supplier


def _calculate_po_items(items) -> tuple[list[dict], Decimal, Decimal, Decimal, Decimal]:
    calculated = []
    subtotal = Decimal("0")
    discount_amount = Decimal("0")
    tax_amount = Decimal("0")
    for item in items:
        base = item.ordered_quantity * item.unit_purchase_price
        discount = _money(base * item.discount_percent / Decimal("100"))
        taxable = _money(base - discount)
        tax = _money(taxable * item.gst_percent / Decimal("100"))
        line_total = _money(taxable + tax)
        subtotal += base
        discount_amount += discount
        tax_amount += tax
        calculated.append({
            **item.model_dump(),
            "taxable_amount": taxable,
            "tax_amount": tax,
            "line_total": line_total,
            "received_quantity": Decimal("0"),
        })
    return calculated, _money(subtotal), _money(discount_amount), _money(tax_amount), _money(subtotal - discount_amount + tax_amount)


def _po_values(order: PurchaseOrder) -> dict:
    return {
        "po_number": order.po_number,
        "supplier_id": str(order.supplier_id),
        "status": order.status,
        "subtotal": str(order.subtotal),
        "discount_amount": str(order.discount_amount),
        "tax_amount": str(order.tax_amount),
        "total_amount": str(order.total_amount),
    }


@router.get("/purchase-orders", response_model=List[PurchaseOrderRead])
async def list_purchase_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    supplier_id: Optional[uuid.UUID] = None,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_PO_VIEW")),
):
    stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).order_by(PurchaseOrder.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(PurchaseOrder.status == status_filter.upper())
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    return (await session.execute(stmt)).scalars().all()


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderRead)
async def get_purchase_order(po_id: uuid.UUID, session: AsyncSession = Depends(get_session), _: dict = Depends(require_permission("PHARMACY_PO_VIEW"))):
    order = (await session.execute(select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).where(PurchaseOrder.id == po_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return order


@router.post("/purchase-orders", response_model=PurchaseOrderRead, status_code=201)
async def create_purchase_order(payload: PurchaseOrderCreate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_CREATE"))):
    if payload.required_by_date and payload.required_by_date < payload.po_date:
        raise HTTPException(status_code=422, detail="required_by_date cannot be before po_date")
    if payload.po_date > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="po_date cannot be in the future")
    await _validate_po_references(session, payload)
    calculated, subtotal, discount, tax, total = _calculate_po_items(payload.items)
    now = datetime.now(timezone.utc)
    order = PurchaseOrder(
        po_number=f"PO-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        supplier_id=payload.supplier_id,
        po_date=payload.po_date,
        required_by_date=payload.required_by_date,
        notes=payload.notes,
        status="DRAFT",
        subtotal=subtotal,
        discount_amount=discount,
        tax_amount=tax,
        total_amount=total,
        created_by_user_id=uuid.UUID(current_user["sub"]),
        updated_by_user_id=uuid.UUID(current_user["sub"]),
    )
    order.items = [PurchaseOrderItem(**item) for item in calculated]
    session.add(order)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="purchase_order", resource_id=order.id, new_value=_po_values(order))
    await session.commit()
    loaded = await session.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .where(PurchaseOrder.id == order.id)
    )
    return loaded.scalar_one()


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderRead)
async def update_purchase_order(po_id: uuid.UUID, payload: PurchaseOrderUpdate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_EDIT"))):
    order = (await session.execute(select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).where(PurchaseOrder.id == po_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only draft purchase orders can be edited")
    if payload.po_date and payload.po_date > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="po_date cannot be in the future")
    if payload.po_date and payload.required_by_date and payload.required_by_date < payload.po_date:
        raise HTTPException(status_code=422, detail="required_by_date cannot be before po_date")
    supplier_id = payload.supplier_id or order.supplier_id
    if payload.items is not None:
        await _validate_po_references(session, payload)
        calculated, subtotal, discount, tax, total = _calculate_po_items(payload.items)
        order.items = [PurchaseOrderItem(**item) for item in calculated]
        order.subtotal, order.discount_amount, order.tax_amount, order.total_amount = subtotal, discount, tax, total
    else:
        await _validate_po_references(session, PurchaseOrderUpdate(supplier_id=supplier_id))
    old_value = _po_values(order)
    order.supplier_id = supplier_id
    for field in ("po_date", "required_by_date", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(order, field, value)
    order.updated_by_user_id = uuid.UUID(current_user["sub"])
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="purchase_order", resource_id=order.id, old_value=old_value, new_value=_po_values(order))
    await session.commit()
    return order


async def _transition_purchase_order(po_id: uuid.UUID, target: str, session: AsyncSession, current_user: dict, reason: Optional[str] = None):
    order = (await session.execute(select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).where(PurchaseOrder.id == po_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if target not in _PO_TRANSITIONS.get(order.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot transition purchase order from {order.status} to {target}")
    if target == "SUBMITTED" and not order.items:
        raise HTTPException(status_code=422, detail="Purchase order must contain at least one item")
    old_value = _po_values(order)
    order.status = target
    if target == "APPROVED":
        order.approved_by_user_id = uuid.UUID(current_user["sub"])
        order.approved_at = datetime.now(timezone.utc)
    if target == "SENT":
        order.sent_at = datetime.now(timezone.utc)
    record_audit(session, current_user=current_user, action=target, resource_type="purchase_order", resource_id=order.id, old_value=old_value, new_value=_po_values(order), reason=reason)
    await session.commit()
    return order


@router.post("/purchase-orders/{po_id}/submit", response_model=PurchaseOrderRead)
async def submit_purchase_order(po_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_SUBMIT"))):
    return await _transition_purchase_order(po_id, "SUBMITTED", session, current_user)


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderRead)
async def approve_purchase_order(po_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_APPROVE"))):
    return await _transition_purchase_order(po_id, "APPROVED", session, current_user)


@router.post("/purchase-orders/{po_id}/send", response_model=PurchaseOrderRead)
async def send_purchase_order(po_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_SEND"))):
    return await _transition_purchase_order(po_id, "SENT", session, current_user)


@router.post("/purchase-orders/{po_id}/reject", response_model=PurchaseOrderRead)
async def reject_purchase_order(po_id: uuid.UUID, reason: Optional[str] = None, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_APPROVE"))):
    if not reason or not reason.strip():
        raise HTTPException(status_code=422, detail="Rejection reason is required")
    return await _transition_purchase_order(po_id, "REJECTED", session, current_user, reason.strip())


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderRead)
async def cancel_purchase_order(po_id: uuid.UUID, reason: Optional[str] = None, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_permission("PHARMACY_PO_CANCEL"))):
    if not reason or not reason.strip():
        raise HTTPException(status_code=422, detail="Cancellation reason is required")
    return await _transition_purchase_order(po_id, "CANCELLED", session, current_user, reason.strip())


def _goods_receipt_values(receipt: GoodsReceipt) -> dict:
    return {
        "grn_number": receipt.grn_number,
        "purchase_order_id": str(receipt.purchase_order_id),
        "supplier_id": str(receipt.supplier_id),
        "facility_id": str(receipt.facility_id) if receipt.facility_id else None,
        "pharmacy_location_id": str(receipt.pharmacy_location_id) if receipt.pharmacy_location_id else None,
        "status": receipt.status,
        "subtotal": str(receipt.subtotal),
        "tax_amount": str(receipt.tax_amount),
        "total_amount": str(receipt.total_amount),
    }


async def _load_goods_receipt(session: AsyncSession, grn_id: uuid.UUID) -> GoodsReceipt:
    receipt = (await session.execute(
        select(GoodsReceipt)
        .options(selectinload(GoodsReceipt.items))
        .where(GoodsReceipt.id == grn_id)
    )).scalar_one_or_none()
    if not receipt:
        raise HTTPException(status_code=404, detail="Goods receipt not found")
    return receipt


def _calculate_grn_totals(items: list[GoodsReceiptItem]) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = Decimal("0")
    tax = Decimal("0")
    for item in items:
        subtotal += item.taxable_amount
        tax += item.tax_amount
    return _money(subtotal), _money(tax), _money(subtotal + tax)


async def _posted_received_quantity(session: AsyncSession, po_item_id: uuid.UUID) -> Decimal:
    result = await session.scalar(
        select(func.coalesce(func.sum(GoodsReceiptItem.received_quantity), 0))
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.goods_receipt_id)
        .where(
            GoodsReceiptItem.purchase_order_item_id == po_item_id,
            GoodsReceipt.status.in_(("PARTIALLY_RECEIVED", "FULLY_RECEIVED")),
        )
    )
    return Decimal(str(result or 0))


@router.get("/grn", response_model=List[GoodsReceiptRead])
async def list_goods_receipts(
    status_filter: Optional[str] = Query(None, alias="status"),
    purchase_order_id: Optional[uuid.UUID] = None,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_GRN_VIEW")),
):
    stmt = select(GoodsReceipt).options(selectinload(GoodsReceipt.items)).order_by(GoodsReceipt.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(GoodsReceipt.status == status_filter.upper())
    if purchase_order_id:
        stmt = stmt.where(GoodsReceipt.purchase_order_id == purchase_order_id)
    return (await session.execute(stmt)).scalars().all()


@router.get("/grn/{grn_id}", response_model=GoodsReceiptRead)
async def get_goods_receipt(
    grn_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_GRN_VIEW")),
):
    return await _load_goods_receipt(session, grn_id)


@router.post("/grn", response_model=GoodsReceiptRead, status_code=201)
async def create_goods_receipt(
    payload: GoodsReceiptCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_GRN_CREATE")),
):
    order = await session.get(PurchaseOrder, payload.purchase_order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.status not in {"SENT", "PARTIALLY_RECEIVED"}:
        raise HTTPException(status_code=409, detail="Goods receipt requires a sent or partially received purchase order")
    if payload.received_date > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="received_date cannot be in the future")
    supplier = await session.get(Supplier, order.supplier_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(status_code=422, detail="Purchase order supplier is missing or inactive")
    if payload.supplier_invoice_number:
        duplicate_invoice = await session.scalar(
            select(GoodsReceipt.id).where(
                GoodsReceipt.supplier_id == order.supplier_id,
                GoodsReceipt.supplier_invoice_number == payload.supplier_invoice_number.strip(),
                GoodsReceipt.supplier_invoice_date == payload.supplier_invoice_date,
                GoodsReceipt.status.not_in(("REJECTED", "CANCELLED")),
            )
        )
        if duplicate_invoice:
            raise HTTPException(status_code=409, detail="Supplier invoice has already been received")
    active_grn = await session.scalar(
        select(GoodsReceipt.id).where(
            GoodsReceipt.purchase_order_id == order.id,
            GoodsReceipt.status == "DRAFT",
        )
    )
    if active_grn:
        raise HTTPException(status_code=409, detail="An active goods receipt already exists for this purchase order")
    now = datetime.now(timezone.utc)
    receipt = GoodsReceipt(
        grn_number=f"GRN-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        purchase_order_id=order.id,
        supplier_id=order.supplier_id,
        facility_id=payload.facility_id,
        pharmacy_location_id=payload.pharmacy_location_id,
        supplier_invoice_number=payload.supplier_invoice_number,
        supplier_invoice_date=payload.supplier_invoice_date,
        received_date=payload.received_date,
        received_by_user_id=uuid.UUID(current_user["sub"]),
        status="DRAFT",
        notes=payload.notes,
        created_by_user_id=uuid.UUID(current_user["sub"]),
        updated_by_user_id=uuid.UUID(current_user["sub"]),
    )
    session.add(receipt)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="goods_receipt", resource_id=receipt.id, new_value=_goods_receipt_values(receipt))
    await session.commit()
    return await _load_goods_receipt(session, receipt.id)


@router.post("/grn/{grn_id}/items", response_model=GoodsReceiptItemRead, status_code=201)
async def receive_goods_receipt_item(
    grn_id: uuid.UUID,
    payload: GoodsReceiptItemCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_GRN_RECEIVE")),
):
    receipt = await _load_goods_receipt(session, grn_id)
    if receipt.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only draft goods receipts can receive items")
    po_item = await session.get(PurchaseOrderItem, payload.purchase_order_item_id)
    if not po_item or po_item.purchase_order_id != receipt.purchase_order_id:
        raise HTTPException(status_code=422, detail="Purchase order item does not belong to this purchase order")
    product = await session.get(MedicineProduct, po_item.medicine_product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=422, detail="Medicine product is missing or inactive")
    if payload.manufacturing_date and payload.manufacturing_date > receipt.received_date:
        raise HTTPException(status_code=422, detail="Manufacturing date cannot be after the received date")
    if payload.expiry_date <= receipt.received_date:
        raise HTTPException(status_code=422, detail="Expiry date must be after the received date")
    if payload.manufacturing_date and payload.expiry_date <= payload.manufacturing_date:
        raise HTTPException(status_code=422, detail="Expiry date must be after the manufacturing date")
    duplicate_batch = await session.scalar(
        select(GoodsReceiptItem.id).where(
            GoodsReceiptItem.medicine_product_id == po_item.medicine_product_id,
            GoodsReceiptItem.batch_number == payload.batch_number.strip(),
            GoodsReceiptItem.expiry_date == payload.expiry_date,
        )
    )
    if duplicate_batch:
        raise HTTPException(status_code=409, detail="This batch and expiry already exists for the medicine product")
    already_received = await _posted_received_quantity(session, po_item.id)
    draft_received = sum((item.received_quantity for item in receipt.items if item.purchase_order_item_id == po_item.id), Decimal("0"))
    remaining = po_item.ordered_quantity - already_received - draft_received
    if payload.received_quantity > remaining:
        raise HTTPException(status_code=409, detail="Received quantity exceeds the remaining purchase order quantity")
    base = _money(payload.received_quantity * po_item.unit_purchase_price)
    tax = _money(base * po_item.gst_percent / Decimal("100"))
    item = GoodsReceiptItem(
        goods_receipt_id=receipt.id,
        purchase_order_item_id=po_item.id,
        medicine_product_id=po_item.medicine_product_id,
        batch_number=payload.batch_number.strip(),
        manufacturing_date=payload.manufacturing_date,
        expiry_date=payload.expiry_date,
        received_quantity=payload.received_quantity,
        free_quantity=payload.free_quantity,
        purchase_rate=po_item.unit_purchase_price,
        mrp=po_item.mrp,
        gst_percent=po_item.gst_percent,
        taxable_amount=base,
        tax_amount=tax,
        line_total=_money(base + tax),
        receiving_notes=payload.receiving_notes,
    )
    session.add(item)
    receipt.subtotal, receipt.tax_amount, receipt.total_amount = _calculate_grn_totals([*receipt.items, item])
    receipt.updated_by_user_id = uuid.UUID(current_user["sub"])
    await session.flush()
    record_audit(session, current_user=current_user, action="RECEIVE", resource_type="goods_receipt_item", resource_id=item.id, new_value={"grn_id": str(receipt.id), "po_item_id": str(po_item.id), "received_quantity": str(item.received_quantity)})
    await session.commit()
    return item


@router.post("/grn/{grn_id}/finalize", response_model=GoodsReceiptRead)
async def finalize_goods_receipt(
    grn_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_GRN_FINALIZE")),
):
    receipt = await _load_goods_receipt(session, grn_id)
    if receipt.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only draft goods receipts can be finalized")
    receipt_items = (await session.execute(
        select(GoodsReceiptItem).where(GoodsReceiptItem.goods_receipt_id == receipt.id)
    )).scalars().all()
    if not receipt_items:
        raise HTTPException(status_code=422, detail="Goods receipt must contain at least one item")
    if bool(receipt.facility_id) != bool(receipt.pharmacy_location_id):
        raise HTTPException(status_code=422, detail="facility_id and pharmacy_location_id must be provided together")
    tenant_id = current_user.get("tenant_id")
    if receipt.facility_id and not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context is required for inventory posting")
    if receipt.facility_id:
        location = await session.scalar(
            select(PharmacyLocation).where(
                PharmacyLocation.id == receipt.pharmacy_location_id,
                PharmacyLocation.tenant_id == uuid.UUID(str(tenant_id)),
                PharmacyLocation.facility_id == receipt.facility_id,
                PharmacyLocation.active == True,  # noqa: E712
            )
        )
        if location is None:
            raise HTTPException(status_code=422, detail="Pharmacy location is missing, inactive, or outside the tenant facility")
    order = (await session.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .where(PurchaseOrder.id == receipt.purchase_order_id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    grouped: dict[uuid.UUID, Decimal] = {}
    for item in receipt_items:
        grouped[item.purchase_order_item_id] = grouped.get(item.purchase_order_item_id, Decimal("0")) + item.received_quantity
    complete = True
    po_items = (await session.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order.id)
    )).scalars().all()
    po_items_by_id = {item.id: item for item in po_items}
    for po_item_id, received_now in grouped.items():
        po_item = po_items_by_id.get(po_item_id)
        if not po_item:
            raise HTTPException(status_code=422, detail="Goods receipt item is not linked to this purchase order")
        prior = await _posted_received_quantity(session, po_item_id)
        total_received = prior + received_now
        po_item.received_quantity = total_received
        complete = complete and total_received >= po_item.ordered_quantity
    receipt.status = "FULLY_RECEIVED" if complete and len(grouped) == len(order.items) else "PARTIALLY_RECEIVED"
    order.status = "FULLY_RECEIVED" if receipt.status == "FULLY_RECEIVED" else "PARTIALLY_RECEIVED"
    receipt.updated_by_user_id = uuid.UUID(current_user["sub"])
    if receipt.facility_id:
        for item in receipt_items:
            await create_inventory_from_grn_item(
                session,
                tenant_id=uuid.UUID(str(tenant_id)),
                facility_id=receipt.facility_id,
                pharmacy_location_id=receipt.pharmacy_location_id,
                medicine_id=item.medicine_product_id,
                supplier_id=receipt.supplier_id,
                goods_receipt_id=receipt.id,
                goods_receipt_item_id=item.id,
                batch_number=item.batch_number,
                received_quantity=item.received_quantity,
                free_quantity=item.free_quantity,
                purchase_rate=item.purchase_rate,
                mrp=item.mrp,
                manufacturing_date=item.manufacturing_date,
                expiry_date=item.expiry_date,
                created_by=uuid.UUID(current_user["sub"]),
                commit=False,
            )
    record_audit(session, current_user=current_user, action="FINALIZE", resource_type="goods_receipt", resource_id=receipt.id, new_value=_goods_receipt_values(receipt))
    await session.commit()
    return await _load_goods_receipt(session, receipt.id)


@router.post("/grn/{grn_id}/reject", response_model=GoodsReceiptRead)
async def reject_goods_receipt(
    grn_id: uuid.UUID,
    reason: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_GRN_CANCEL")),
):
    receipt = await _load_goods_receipt(session, grn_id)
    if receipt.status not in {"DRAFT", "PARTIALLY_RECEIVED"}:
        raise HTTPException(status_code=409, detail="Goods receipt cannot be rejected in its current state")
    if not reason or not reason.strip():
        raise HTTPException(status_code=422, detail="Rejection reason is required")
    receipt.status = "REJECTED"
    record_audit(session, current_user=current_user, action="REJECT", resource_type="goods_receipt", resource_id=receipt.id, reason=reason.strip(), new_value=_goods_receipt_values(receipt))
    await session.commit()
    return await _load_goods_receipt(session, receipt.id)


@router.post("/grn/{grn_id}/cancel", response_model=GoodsReceiptRead)
async def cancel_goods_receipt(
    grn_id: uuid.UUID,
    reason: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_GRN_CANCEL")),
):
    receipt = await _load_goods_receipt(session, grn_id)
    if receipt.status not in {"DRAFT", "PARTIALLY_RECEIVED"}:
        raise HTTPException(status_code=409, detail="Goods receipt cannot be cancelled in its current state")
    if not reason or not reason.strip():
        raise HTTPException(status_code=422, detail="Cancellation reason is required")
    receipt.status = "CANCELLED"
    record_audit(session, current_user=current_user, action="CANCEL", resource_type="goods_receipt", resource_id=receipt.id, reason=reason.strip(), new_value=_goods_receipt_values(receipt))
    await session.commit()
    return await _load_goods_receipt(session, receipt.id)


def _supplier_values(item: Supplier | None) -> dict | None:
    if item is None:
        return None
    return {
        "supplier_code": item.supplier_code,
        "supplier_name": item.supplier_name,
        "gstin": item.gstin,
        "drug_license_no": item.drug_license_no,
        "address_line1": item.address_line1,
        "address_line2": item.address_line2,
        "city": item.city,
        "state": item.state,
        "postal_code": item.postal_code,
        "country": item.country,
        "contact_person": item.contact_person,
        "phone": item.phone,
        "email": item.email,
        "payment_terms": item.payment_terms,
        "credit_days": item.credit_days,
        "is_active": item.is_active,
        "notes": item.notes,
    }


@router.get("/suppliers", response_model=List[SupplierRead])
async def list_suppliers(
    q: str = Query("", max_length=100),
    include_inactive: bool = False,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_SUPPLIER_VIEW")),
):
    stmt = select(Supplier)
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active == True)  # noqa: E712
    term = q.strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(or_(Supplier.supplier_code.ilike(like), Supplier.supplier_name.ilike(like)))
    return (await session.execute(stmt.order_by(Supplier.supplier_name).limit(limit))).scalars().all()


@router.get("/suppliers/{supplier_id}", response_model=SupplierRead)
async def get_supplier(
    supplier_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_SUPPLIER_VIEW")),
):
    item = await session.get(Supplier, supplier_id)
    if not item:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return item


@router.post("/suppliers", response_model=SupplierRead, status_code=201)
async def create_supplier(
    payload: SupplierCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_SUPPLIER_MANAGE")),
):
    code = payload.supplier_code.strip().upper()
    name = payload.supplier_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Supplier name is required")
    if await session.scalar(select(Supplier).where(Supplier.supplier_code == code)):
        raise HTTPException(status_code=409, detail="Supplier code already exists")
    if payload.credit_days is not None and payload.credit_days < 0:
        raise HTTPException(status_code=422, detail="credit_days cannot be negative")
    item = Supplier(supplier_code=code, supplier_name=name, **payload.model_dump(exclude={"supplier_code", "supplier_name"}))
    session.add(item)
    await session.flush()
    record_audit(session, current_user=current_user, action="CREATE", resource_type="supplier", resource_id=item.id, new_value=_supplier_values(item))
    await session.commit()
    return item


@router.put("/suppliers/{supplier_id}", response_model=SupplierRead)
async def update_supplier(
    supplier_id: uuid.UUID,
    payload: SupplierUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_SUPPLIER_MANAGE")),
):
    item = await session.get(Supplier, supplier_id)
    if not item:
        raise HTTPException(status_code=404, detail="Supplier not found")
    changes = payload.model_dump(exclude_unset=True)
    if "supplier_name" in changes and not (changes["supplier_name"] or "").strip():
        raise HTTPException(status_code=422, detail="Supplier name is required")
    if changes.get("credit_days") is not None and changes["credit_days"] < 0:
        raise HTTPException(status_code=422, detail="credit_days cannot be negative")
    old_value = _supplier_values(item)
    for field, value in changes.items():
        setattr(item, field, value.strip() if isinstance(value, str) and field == "supplier_name" else value)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="supplier", resource_id=item.id, old_value=old_value, new_value=_supplier_values(item))
    await session.commit()
    return item


def _current_tenant_id(current_user: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(current_user["tenant_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Tenant context is required") from exc


@router.get("/inventory/locations", response_model=List[PharmacyLocationRead])
async def list_inventory_locations(
    facility_id: uuid.UUID = Depends(get_facility_id),
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_INVENTORY_VIEW")),
):
    stmt = select(PharmacyLocation).where(
        PharmacyLocation.tenant_id == _current_tenant_id(current_user),
        PharmacyLocation.facility_id == facility_id,
    )
    if not include_inactive:
        stmt = stmt.where(PharmacyLocation.active == True)  # noqa: E712
    return (await session.execute(stmt.order_by(PharmacyLocation.location_name))).scalars().all()


@router.get("/inventory/batches", response_model=List[InventoryBatchRead])
async def list_inventory_batches(
    pharmacy_location_id: uuid.UUID,
    facility_id: uuid.UUID = Depends(get_facility_id),
    medicine_id: Optional[uuid.UUID] = None,
    dispensable_only: bool = True,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_INVENTORY_VIEW")),
):
    tenant_id = _current_tenant_id(current_user)
    if medicine_id is not None:
        return await get_fefo_batches_for_medicine(
            session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            pharmacy_location_id=pharmacy_location_id,
            medicine_id=medicine_id,
            as_of_date=datetime.now(timezone.utc).date() if dispensable_only else None,
            limit=limit,
        )

    stmt = select(InventoryBatch).where(
        InventoryBatch.tenant_id == tenant_id,
        InventoryBatch.facility_id == facility_id,
        InventoryBatch.pharmacy_location_id == pharmacy_location_id,
    )
    if dispensable_only:
        stmt = stmt.where(
            InventoryBatch.status == "ACTIVE",
            InventoryBatch.available_quantity > Decimal("0"),
            InventoryBatch.expiry_date.is_(None) | (InventoryBatch.expiry_date >= datetime.now(timezone.utc).date()),
        )
    return (await session.execute(stmt.order_by(InventoryBatch.expiry_date.asc().nulls_last()).limit(limit))).scalars().all()


@router.get("/inventory/balance", response_model=InventoryBalanceRead)
async def inventory_balance(
    facility_id: uuid.UUID,
    pharmacy_location_id: uuid.UUID,
    medicine_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_INVENTORY_VIEW")),
):
    return await get_location_medicine_balance(
        session,
        tenant_id=_current_tenant_id(current_user),
        facility_id=facility_id,
        pharmacy_location_id=pharmacy_location_id,
        medicine_id=medicine_id,
    )


@router.get("/inventory/ledger", response_model=List[StockTransactionRead])
async def list_inventory_ledger(
    facility_id: uuid.UUID,
    pharmacy_location_id: uuid.UUID,
    medicine_id: Optional[uuid.UUID] = None,
    inventory_batch_id: Optional[uuid.UUID] = None,
    transaction_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_STOCK_LEDGER_VIEW")),
):
    filters = [
        StockTransaction.tenant_id == _current_tenant_id(current_user),
        StockTransaction.facility_id == facility_id,
        StockTransaction.pharmacy_location_id == pharmacy_location_id,
    ]
    if medicine_id is not None:
        filters.append(StockTransaction.medicine_id == medicine_id)
    if inventory_batch_id is not None:
        filters.append(StockTransaction.inventory_batch_id == inventory_batch_id)
    if transaction_type:
        filters.append(StockTransaction.transaction_type == transaction_type.upper())
    stmt = select(StockTransaction).where(*filters).order_by(StockTransaction.created_at.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()


@router.get("/inventory/batches/{inventory_batch_id}/reconciliation", response_model=InventoryReconciliationRead)
async def inventory_batch_reconciliation(
    inventory_batch_id: uuid.UUID,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_INVENTORY_RECONCILE")),
):
    return await reconcile_inventory_batch(
        session,
        inventory_batch_id,
        tenant_id=_current_tenant_id(current_user),
        facility_id=facility_id,
    )


@router.post("/inventory/adjustments", response_model=StockTransactionRead, status_code=201)
async def create_inventory_adjustment(
    payload: StockAdjustmentCreate,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_STOCK_ADJUST")),
):
    try:
        return await record_stock_adjustment(
            session,
            tenant_id=_current_tenant_id(current_user),
            facility_id=facility_id,
            inventory_batch_id=payload.inventory_batch_id,
            quantity=payload.quantity,
            reference_id=payload.reference_id,
            reason=payload.reason,
            performed_by=uuid.UUID(str(current_user["sub"])),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/suppliers/{supplier_id}/deactivate", response_model=SupplierRead)
async def deactivate_supplier(
    supplier_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_SUPPLIER_MANAGE")),
):
    item = await session.get(Supplier, supplier_id)
    if not item:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if item.is_active:
        item.is_active = False
        record_audit(session, current_user=current_user, action="DEACTIVATE", resource_type="supplier", resource_id=item.id, old_value={"is_active": True}, new_value={"is_active": False})
        await session.commit()
    return item


@router.post("/suppliers/import", response_model=List[SupplierRead])
async def import_suppliers(
    items: list[SupplierImportItem],
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_SUPPLIER_MANAGE")),
):
    result = []
    for payload in items:
        code = payload.supplier_code.strip().upper()
        if not payload.supplier_name.strip():
            raise HTTPException(status_code=422, detail="Supplier name is required")
        if payload.credit_days is not None and payload.credit_days < 0:
            raise HTTPException(status_code=422, detail="credit_days cannot be negative")
        item = await session.scalar(select(Supplier).where(Supplier.supplier_code == code))
        old_value = _supplier_values(item)
        values = payload.model_dump(exclude={"supplier_code", "supplier_name"})
        if item:
            item.supplier_name = payload.supplier_name.strip()
            for field, value in values.items():
                setattr(item, field, value)
            item.is_active = True
            action = "UPDATE"
        else:
            item = Supplier(supplier_code=code, supplier_name=payload.supplier_name.strip(), **values)
            session.add(item)
            await session.flush()
            action = "CREATE"
        record_audit(session, current_user=current_user, action=action, resource_type="supplier", resource_id=item.id, old_value=old_value, new_value=_supplier_values(item))
        result.append(item)
    await session.commit()
    return result


@router.get("/medicines/search", response_model=List[FormularyMedicineSearchResult])
async def search_formulary_medicines(
    q: str = Query("", max_length=100),
    department_id: Optional[uuid.UUID] = None,
    prescribable_only: bool = True,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "pharmacist", "hospital_admin")),
):
    today = datetime.now(timezone.utc).date()
    stmt = (
        select(HospitalFormulary, MedicineProduct, GenericMedicine, DosageForm, Route)
        .join(MedicineProduct, MedicineProduct.id == HospitalFormulary.medicine_product_id)
        .join(GenericMedicine, GenericMedicine.id == MedicineProduct.generic_medicine_id)
        .join(DosageForm, DosageForm.id == MedicineProduct.dosage_form_id)
        .outerjoin(
            Route,
            and_(
                Route.id == MedicineProduct.default_route_id,
                Route.is_active == True,  # noqa: E712
            ),
        )
        .where(
            HospitalFormulary.is_active == True,  # noqa: E712
            HospitalFormulary.is_approved == True,  # noqa: E712
            MedicineProduct.is_active == True,  # noqa: E712
            GenericMedicine.is_active == True,  # noqa: E712
            DosageForm.is_active == True,  # noqa: E712
            or_(HospitalFormulary.effective_date.is_(None), HospitalFormulary.effective_date <= today),
            or_(HospitalFormulary.expiry_date.is_(None), HospitalFormulary.expiry_date >= today),
        )
    )
    if department_id is not None:
        stmt = stmt.where(HospitalFormulary.department_id == department_id)
    if prescribable_only:
        stmt = stmt.where(HospitalFormulary.is_prescribable == True)  # noqa: E712
    term = q.strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                MedicineProduct.code.ilike(like),
                MedicineProduct.brand_name.ilike(like),
                GenericMedicine.name.ilike(like),
                MedicineProduct.composition.ilike(like),
            )
        )
    rows = (await session.execute(stmt.order_by(MedicineProduct.brand_name, MedicineProduct.code).limit(limit))).all()
    return [
        FormularyMedicineSearchResult(
            medicine_product_id=product.id,
            code=product.code,
            brand_name=product.brand_name,
            generic_name=generic.name,
            strength=product.strength,
            unit=product.unit,
            dosage_form_name=dosage_form.name,
            default_route_name=route.name if route else None,
            composition=product.composition,
            is_controlled_drug=product.is_controlled_drug,
            requires_prescription=product.requires_prescription,
            is_approved=formulary.is_approved,
            is_preferred=formulary.is_preferred,
            is_prescribable=formulary.is_prescribable,
            effective_date=formulary.effective_date,
            expiry_date=formulary.expiry_date,
        )
        for formulary, product, generic, dosage_form, route in rows
    ]


@router.get("", response_model=List[PharmacyQueueRead])
async def list_pharmacy_queue(
    status_filter: Optional[str] = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_QUEUE_VIEW")),
):
    """Returns pharmacy queue items, optionally filtered by status."""
    stmt = select(PharmacyQueue).order_by(PharmacyQueue.updated_at.asc())
    if status_filter:
        stmt = stmt.where(PharmacyQueue.status == status_filter)
    rows = (await session.execute(stmt)).scalars().all()

    items = []
    for pq in rows:
        item = PharmacyQueueRead.model_validate(pq)
        rx = await session.get(Prescription, pq.prescription_id)
        if rx:
            item.visit_id = rx.visit_id
            item.medicines = rx.medicines
            visit = await session.get(Visit, rx.visit_id)
            if visit:
                item.patient_id = visit.patient_id
                patient = await session.get(Patient, visit.patient_id)
                if patient:
                    item.patient_name = f"{patient.first_name} {patient.last_name}"
        items.append(item)
    return items


@router.patch("/{pq_id}/status", response_model=PharmacyQueueRead)
async def update_pharmacy_status(
    pq_id: uuid.UUID,
    payload: PharmacyStatusUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_QUEUE_STATUS_UPDATE")),
):
    pq = await session.get(PharmacyQueue, pq_id)
    if not pq:
        raise HTTPException(status_code=404, detail="Pharmacy queue item not found")

    allowed_statuses = {"pending", "called", "dispensing", "dispensed", "partially_dispensed", "out_of_stock", "cancelled"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Unsupported pharmacy status: {payload.status}")

    old_status = pq.status
    now = datetime.now(timezone.utc)
    pq.status = payload.status
    if payload.status == "called":
        pq.called_at = pq.called_at or now
    elif payload.status == "dispensing":
        pq.dispensing_started_at = pq.dispensing_started_at or now
    elif payload.status == "dispensed":
        pq.dispensed_at = pq.dispensed_at or now
    if payload.notes is not None:
        pq.notes = payload.notes

    rx = await session.get(Prescription, pq.prescription_id)
    visit = await session.get(Visit, rx.visit_id) if rx else None
    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="pharmacy_dispense",
        resource_id=pq.id,
        patient_id=visit.patient_id if visit else None,
        visit_id=rx.visit_id if rx else None,
        old_value={"status": old_status},
        new_value={"status": pq.status, "notes": pq.notes},
    )

    await session.commit()
    await session.refresh(pq)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "pharmacy:update", {
        "event": "pharmacy_status_updated",
        "pq_id": str(pq.id),
        "status": pq.status,
    })

    item = PharmacyQueueRead.model_validate(pq)
    rx = await session.get(Prescription, pq.prescription_id)
    if rx:
        item.visit_id = rx.visit_id
        item.medicines = rx.medicines
        visit = await session.get(Visit, rx.visit_id)
        if visit:
            item.patient_id = visit.patient_id
            patient = await session.get(Patient, visit.patient_id)
            if patient:
                item.patient_name = f"{patient.first_name} {patient.last_name}"
    return item


@router.post("/{pq_id}/start", response_model=PharmacyQueueRead)
async def start_pharmacy_queue_item(
    pq_id: uuid.UUID,
    payload: PharmacyDispenseStart,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_START")),
):
    try:
        dispense = await start_pharmacy_dispense(
            session,
            queue_id=pq_id,
            tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=payload.facility_id,
            pharmacy_location_id=payload.pharmacy_location_id,
            started_by=uuid.UUID(str(current_user["sub"])),
        )
        record_audit(
            session,
            current_user=current_user,
            action="START",
            resource_type="pharmacy_dispense",
            resource_id=dispense.id,
            patient_id=dispense.patient_id,
            visit_id=dispense.visit_id,
            new_value={"status": dispense.status, "pharmacy_queue_id": str(pq_id)},
        )
        await session.commit()
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    queue = await session.get(PharmacyQueue, pq_id)
    result = PharmacyQueueRead.model_validate(queue)
    result.dispense_id = dispense.id
    return result


@router.post("/dispenses/{dispense_id}/validate", response_model=PharmacyDispenseRead)
async def validate_pharmacy_dispense_route(
    dispense_id: uuid.UUID,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_VALIDATE")),
):
    try:
        dispense = await validate_pharmacy_dispense(
            session,
            dispense_id=dispense_id,
            tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id,
            validated_by=uuid.UUID(str(current_user["sub"])),
        )
        record_audit(
            session,
            current_user=current_user,
            action="VALIDATE",
            resource_type="pharmacy_dispense",
            resource_id=dispense.id,
            patient_id=dispense.patient_id,
            visit_id=dispense.visit_id,
            new_value={"status": dispense.status, "prescription_version": dispense.prescription_version},
        )
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispenses/{dispense_id}/outside-purchase", response_model=PharmacyDispenseRead)
async def record_outside_purchase(
    dispense_id: uuid.UUID,
    payload: OutsidePurchaseCreate,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_OUTSIDE_PURCHASE")),
):
    try:
        dispense = await confirm_outside_purchase_fulfillment(
            session,
            dispense_id=dispense_id,
            tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id,
            quantities={item.dispense_item_id: item.quantity for item in payload.items},
            confirmed_by=uuid.UUID(str(current_user["sub"])),
        )
        record_audit(
            session,
            current_user=current_user,
            action="OUTSIDE_PURCHASE",
            resource_type="pharmacy_dispense",
            resource_id=dispense.id,
            patient_id=dispense.patient_id,
            visit_id=dispense.visit_id,
            new_value={"status": dispense.status, "fulfillment_mode": dispense.fulfillment_mode},
        )
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispenses/{dispense_id}/substitution", response_model=PharmacyDispenseRead)
async def approve_substitution(
    dispense_id: uuid.UUID,
    payload: PharmacySubstitutionCreate,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_SUBSTITUTE")),
):
    try:
        item = await approve_pharmacy_substitution(
            session,
            dispense_id=dispense_id,
            dispense_item_id=payload.dispense_item_id,
            tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id,
            dispensed_medicine_product_id=payload.dispensed_medicine_product_id,
            substitution_reason=payload.substitution_reason,
            approved_by=uuid.UUID(str(current_user["sub"])),
        )
        dispense = await session.get(PharmacyDispense, dispense_id)
        record_audit(
            session,
            current_user=current_user,
            action="SUBSTITUTION_APPROVED",
            resource_type="pharmacy_dispense_item",
            resource_id=item.id,
            patient_id=dispense.patient_id if dispense else None,
            visit_id=dispense.visit_id if dispense else None,
            new_value={"dispensed_medicine_product_id": str(item.dispensed_medicine_product_id), "reason": item.substitution_reason},
        )
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispenses/{dispense_id}/confirm", response_model=PharmacyDispenseRead)
async def confirm_pharmacy_dispense(
    dispense_id: uuid.UUID,
    payload: PharmacyDispenseConfirm,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_CONFIRM")),
):
    try:
        dispense = await confirm_dispense_stock_consumption(
            session,
            dispense_id=dispense_id,
            tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id,
            confirmed_by=uuid.UUID(str(current_user["sub"])),
            billing_authorized=payload.billing_authorized,
        )
        record_audit(
            session,
            current_user=current_user,
            action="CONFIRM",
            resource_type="pharmacy_dispense",
            resource_id=dispense.id,
            patient_id=dispense.patient_id,
            visit_id=dispense.visit_id,
            new_value={"status": dispense.status, "billing_authorized": payload.billing_authorized},
        )
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dispenses/{dispense_id}/items", response_model=List[PharmacyDispenseItemRead])
async def list_pharmacy_dispense_items(
    dispense_id: uuid.UUID,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_permission("PHARMACY_BILLING_VIEW")),
):
    dispense = await session.scalar(select(PharmacyDispense).where(
        PharmacyDispense.id == dispense_id,
        PharmacyDispense.tenant_id == uuid.UUID(str(_["tenant_id"])),
        PharmacyDispense.facility_id == facility_id,
    ))
    if dispense is None:
        raise HTTPException(status_code=404, detail="Pharmacy dispense not found")
    return (await session.execute(select(PharmacyDispenseItem).where(
        PharmacyDispenseItem.dispense_id == dispense.id,
    ).order_by(PharmacyDispenseItem.created_at))).scalars().all()


@router.post("/dispenses/{dispense_id}/cancel", response_model=PharmacyDispenseRead)
async def cancel_pharmacy_dispense(
    dispense_id: uuid.UUID,
    payload: PharmacyReservationRelease,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_BILLING_CANCEL")),
):
    try:
        dispense = await release_dispense_reservations(
            session,
            dispense_id=dispense_id,
            tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id,
            released_by=uuid.UUID(str(current_user["sub"])),
            reason=payload.reason,
        )
        record_audit(session, current_user=current_user, action="CANCEL", resource_type="pharmacy_dispense", resource_id=dispense.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"status": dispense.status, "reason": payload.reason})
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispenses/{dispense_id}/allocation-proposal", response_model=PharmacyDispenseRead)
async def propose_dispense_allocation(
    dispense_id: uuid.UUID,
    payload: PharmacyAllocationRequest,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_ALLOCATE")),
):
    try:
        dispense = await propose_pharmacy_allocations(
            session, dispense_id=dispense_id, tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id, proposed_by=uuid.UUID(str(current_user["sub"])),
            requested_quantities=payload.requested_quantities,
        )
        record_audit(session, current_user=current_user, action="ALLOCATE", resource_type="pharmacy_dispense", resource_id=dispense.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"status": dispense.status})
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispenses/{dispense_id}/reserve", response_model=List[PharmacyReservationRead])
async def reserve_dispense_stock(
    dispense_id: uuid.UUID,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_STOCK_RESERVE")),
):
    try:
        reservations = await create_stock_reservations(
            session, dispense_id=dispense_id, tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id, reserved_by=uuid.UUID(str(current_user["sub"])),
        )
        dispense = await session.get(PharmacyDispense, dispense_id)
        record_audit(session, current_user=current_user, action="RESERVE", resource_type="pharmacy_dispense", resource_id=dispense_id, patient_id=dispense.patient_id if dispense else None, visit_id=dispense.visit_id if dispense else None, new_value={"reservation_count": len(reservations)})
        await session.commit()
        return reservations
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reservations/{reservation_id}/release", response_model=PharmacyReservationRead)
async def release_dispense_reservation(
    reservation_id: uuid.UUID,
    payload: PharmacyReservationRelease,
    facility_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_STOCK_RESERVATION_RELEASE")),
):
    try:
        reservation = await release_stock_reservation(
            session, reservation_id=reservation_id, tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id, released_by=uuid.UUID(str(current_user["sub"])), reason=payload.reason,
        )
        record_audit(session, current_user=current_user, action="RESERVATION_RELEASE", resource_type="pharmacy_stock_reservation", resource_id=reservation.id, new_value={"status": reservation.status, "reason": reservation.release_reason})
        await session.commit()
        return reservation
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispenses/{dispense_id}/fulfill-internally", response_model=PharmacyDispenseRead)
async def fulfill_dispense_internally(
    dispense_id: uuid.UUID,
    partial: bool = False,
    facility_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_DISPENSE_FULFILL")),
):
    try:
        service = confirm_partial_internal_fulfillment if partial else confirm_full_internal_fulfillment
        dispense = await service(
            session, dispense_id=dispense_id, tenant_id=uuid.UUID(str(current_user["tenant_id"])),
            facility_id=facility_id, confirmed_by=uuid.UUID(str(current_user["sub"])),
        )
        record_audit(session, current_user=current_user, action="FULFILL", resource_type="pharmacy_dispense", resource_id=dispense.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"status": dispense.status, "fulfillment_mode": dispense.fulfillment_mode})
        await session.commit()
        return dispense
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Background task ───────────────────────────────────────────────────────────

def _send_prescription_pdf_task(
    *,
    hospital_name: str,
    patient_name: str,
    uhid: str,
    gender: str,
    age: Optional[int],
    dob: Optional[str],
    phone: str,
    visit_date: str,
    department_name: Optional[str],
    doctor_name: Optional[str],
    doctor_specialization: Optional[str],
    chief_complaint: Optional[str],
    diagnosis: Optional[list],
    notes: Optional[str],
    medicines: Optional[list],
    lab_tests: Optional[list],
    follow_up_date: Optional[str],
) -> None:
    """Synchronous background task: generate PDF, upload, send WhatsApp."""
    try:
        pdf_url = generate_and_upload_prescription_pdf(
            hospital_name=hospital_name,
            patient_name=patient_name,
            uhid=uhid,
            gender=gender,
            age=age,
            dob=dob,
            phone=phone,
            visit_date=visit_date,
            department_name=department_name,
            doctor_name=doctor_name,
            doctor_specialization=doctor_specialization,
            chief_complaint=chief_complaint,
            diagnosis=diagnosis,
            notes=notes,
            medicines=medicines,
            lab_tests=lab_tests,
            follow_up_date=follow_up_date,
        )
        send_prescription_whatsapp(
            to_phone=phone,
            patient_name=patient_name,
            uhid=uhid,
            hospital_name=hospital_name,
            doctor_name=doctor_name,
            pdf_url=pdf_url,
        )
    except Exception:
        logger.exception("Failed to send prescription PDF WhatsApp for UHID=%s", uhid)


# ── Bill endpoint ─────────────────────────────────────────────────────────────

@router.post("/{pq_id}/bill", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def bill_pharmacy_dispense(
    pq_id: uuid.UUID,
    payload: PharmacyBillCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_BILLING_CREATE")),
):
    """
    Create an invoice for pharmacy dispense and optionally trigger Razorpay order.
    - payment_method=cash   → marks invoice paid immediately, advances queue to dispensed,
                              sends prescription PDF via WhatsApp to patient
    - payment_method=online → creates Razorpay order, returns razorpay_order_id for frontend checkout
    """
    logger.info(
        "Pharmacy bill: Start - pq_id=%s, payment_method=%s, discount=%.2f",
        pq_id, payload.payment_method, payload.discount,
    )

    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    dispense = (await session.execute(
        select(PharmacyDispense).where(
            PharmacyDispense.pharmacy_queue_id == pq_id,
            PharmacyDispense.tenant_id == tenant_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if dispense is not None and dispense.invoice_id is not None:
        existing_invoice = await session.get(Invoice, dispense.invoice_id)
        if existing_invoice is not None:
            record_audit(session, current_user=current_user, action="PHARMACY_INVOICE_REUSED", resource_type="invoice", resource_id=existing_invoice.id, new_value={"invoice_id": str(existing_invoice.id), "pharmacy_dispense_id": str(dispense.id), "reason": "idempotent retry"})
            await session.commit()
            return existing_invoice
    
    pq = await session.get(PharmacyQueue, pq_id)
    if not pq:
        raise HTTPException(status_code=404, detail="Pharmacy queue item not found")
    allowed_billable_statuses = {"pending", "called", "dispensing"}
    if pq.status not in allowed_billable_statuses:
        raise HTTPException(status_code=400, detail=f"Queue item is not billable in status {pq.status}")

    if dispense is None:
        raise HTTPException(status_code=400, detail="Pharmacy dispense is required before billing")
    if dispense.status not in {"READY_FOR_BILLING", "PARTIALLY_FULFILLED"}:
        raise HTTPException(status_code=400, detail=f"Pharmacy dispense is not ready for billing in status {dispense.status}")

    rx = await session.get(Prescription, pq.prescription_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    visit = await session.get(Visit, rx.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    patient = await session.get(Patient, visit.patient_id) if visit else None

    # Fetch supplementary data for PDF/WhatsApp (best-effort)
    consultation = (await session.execute(
        select(Consultation).where(Consultation.visit_id == rx.visit_id)
    )).scalar_one_or_none()

    doctor: Optional[Doctor] = None
    if visit.doctor_id:
        doctor = await session.get(Doctor, visit.doctor_id)

    department: Optional[Department] = None
    if visit.department_id:
        department = await session.get(Department, visit.department_id)

    # Fetch tenant info for hospital name
    from sqlalchemy import text as sql_text
    hospital_name_row = await session.execute(
        sql_text("SELECT hospital_name FROM public.tenants WHERE schema_name = current_schema() LIMIT 1")
    )
    hospital_name = (hospital_name_row.scalar() or "Hospital")

    dispense_items = list((await session.execute(
        select(PharmacyDispenseItem).where(PharmacyDispenseItem.dispense_id == dispense.id)
    )).scalars().all())
    previous_invoices = (await session.execute(
        select(Invoice).where(
            Invoice.visit_id == rx.visit_id,
            Invoice.source == "pharmacy_dispense",
            Invoice.status.not_in(("cancelled", "refunded")),
        )
    )).scalars().all()
    already_billed_quantities: dict[uuid.UUID, Decimal] = {}
    for previous_invoice in previous_invoices:
        for previous_line in previous_invoice.line_items or []:
            prescription_item_id = previous_line.get("prescription_item_id")
            if prescription_item_id:
                key = uuid.UUID(str(prescription_item_id))
                already_billed_quantities[key] = already_billed_quantities.get(key, Decimal("0")) + Decimal(str(previous_line.get("qty", 0)))
    try:
        li_dicts = prepare_billable_pharmacy_line_items(
            [line_item.model_dump() for line_item in payload.line_items],
            dispense_items,
            already_billed_quantities,
        )
        li_dicts = await resolve_billable_pharmacy_line_items(
            session,
            line_items=li_dicts,
            dispense_items=dispense_items,
            tenant_id=tenant_id,
            facility_id=dispense.facility_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Compute totals from server-filtered hospital-supplied quantities.
    requested_total_quantity = sum(Decimal(str(li["qty"])) for li in li_dicts)
    subtotal = sum(Decimal(str(li["total"])) for li in li_dicts)
    gst_total = sum((
        Decimal(str(li["qty"])) * Decimal(str(li["mrp"])) * (Decimal(str(li["gst_pct"])) / 100) * (1 - Decimal(str(li["dis_pct"])) / 100)
        for li in li_dicts
    ), Decimal("0"))
    if payload.discount != 0:
        raise HTTPException(status_code=400, detail="Pharmacy discounts require an approved server-side billing policy")
    total = subtotal

    try:
        await validate_billable_dispense_quantities(
            session,
            dispense_id=dispense.id,
            tenant_id=tenant_id,
            facility_id=dispense.facility_id,
            requested_total_quantity=requested_total_quantity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    invoice = Invoice(
        id=uuid.uuid4(),
        visit_id=rx.visit_id,
        uhid=patient.uhid if patient else None,
        line_items=li_dicts,
        subtotal=float(subtotal),
        discount=payload.discount,
        tax=float(gst_total.quantize(Decimal("0.01"))),
        total=float(total),
        source="pharmacy_dispense" if dispense else "pharmacy",
        pharmacy_queue_id=pq_id,
        pharmacy_dispense_id=dispense.id,
        status="draft",
    )
    dispense.invoice_id = invoice.id
    session.add(invoice)
    record_audit(session, current_user=current_user, action="PHARMACY_INVOICE_CREATED", resource_type="invoice", resource_id=invoice.id, patient_id=visit.patient_id, visit_id=visit.id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(dispense.id), "queue_id": str(pq_id), "total": float(total), "line_count": len(li_dicts)})

    tenant = current_user.get("tenant_schema", "public")
    
    logger.info(
        "Pharmacy bill: Created invoice %s - payment_method=%s, total=%.2f, tenant=%s",
        invoice.id, payload.payment_method, total, tenant,
    )

    if payload.payment_method == "cash":
        logger.info("Pharmacy bill: Processing CASH payment for invoice %s", invoice.id)
        
        invoice.payment_method = "cash"
        invoice.status = "paid"
        invoice.paid_amount = float(total)
        invoice.paid_at = datetime.now(timezone.utc)
        invoice.billing_completed_at = invoice.paid_at
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_INITIATED", resource_type="invoice", resource_id=invoice.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(dispense.id), "payment_method": "cash", "amount": float(invoice.total)})
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_COMPLETED", resource_type="invoice", resource_id=invoice.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(dispense.id), "payment_method": "cash", "amount": float(invoice.total)})
        
        logger.info(
            "Pharmacy bill: Set invoice to paid - status=%s, payment_method=%s, paid_at=%s",
            invoice.status, invoice.payment_method, invoice.paid_at,
        )
        try:
            authorized = await authorize_pharmacy_billing(
                session,
                dispense_id=dispense.id,
                tenant_id=tenant_id,
                facility_id=dispense.facility_id,
                confirmed_by=uuid.UUID(str(current_user["sub"])),
                invoice_id=invoice.id,
            )
            record_audit(session, current_user=current_user, action="PHARMACY_DISPENSE_AUTHORIZED", resource_type="pharmacy_dispense", resource_id=authorized.id, patient_id=authorized.patient_id, visit_id=authorized.visit_id, new_value={"invoice_id": str(invoice.id), "billing_status": authorized.billing_status, "status": authorized.status})
            confirmed = await confirm_dispense_stock_consumption(
                session,
                dispense_id=authorized.id,
                tenant_id=tenant_id,
                facility_id=authorized.facility_id,
                confirmed_by=uuid.UUID(str(current_user["sub"])),
                billing_authorized=True,
            )
            record_audit(session, current_user=current_user, action="PHARMACY_DISPENSE_CONFIRMED", resource_type="pharmacy_dispense", resource_id=confirmed.id, patient_id=confirmed.patient_id, visit_id=confirmed.visit_id, new_value={"invoice_id": str(invoice.id), "billing_status": confirmed.billing_status, "status": confirmed.status})
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        await session.commit()
        await session.refresh(invoice)
        await ws_manager.broadcast(tenant, "pharmacy:update", {
            "event": "pharmacy_status_updated",
            "pq_id": str(pq_id),
            "status": "dispensed",
        })

        # Schedule WhatsApp prescription PDF (non-blocking)
        if patient and patient.phone:
            dob_str = patient.dob.isoformat() if patient.dob else None
            follow_up_str = consultation.follow_up_date.isoformat() if consultation and consultation.follow_up_date else None
            visit_date_str = visit.created_at.strftime("%d %b %Y") if hasattr(visit, "created_at") and visit.created_at else datetime.now(timezone.utc).strftime("%d %b %Y")
            # Fetch lab orders for this visit (best-effort)
            lab_order = (await session.execute(
                select(LabOrder).where(LabOrder.visit_id == rx.visit_id)
            )).scalar_one_or_none()
            # LabOrder.tests keys are {test, notes}; PDF helper expects {test_name, notes}
            lab_tests_for_pdf = None
            if lab_order and lab_order.tests:
                lab_tests_for_pdf = [
                    {"test_name": t.get("test", t.get("test_name", "")), "notes": t.get("notes")}
                    for t in lab_order.tests
                ]
            background_tasks.add_task(
                _send_prescription_pdf_task,
                hospital_name=hospital_name,
                patient_name=f"{patient.first_name} {patient.last_name}",
                uhid=patient.uhid,
                gender=patient.gender,
                age=patient.age,
                dob=dob_str,
                phone=patient.phone,
                visit_date=visit_date_str,
                department_name=department.name if department else None,
                doctor_name=doctor.full_name if doctor else None,
                doctor_specialization=doctor.specialization if doctor else None,
                chief_complaint=consultation.chief_complaint if consultation else None,
                diagnosis=consultation.diagnosis_icd10 if consultation else None,
                notes=consultation.notes if consultation else None,
                medicines=rx.medicines,
                lab_tests=lab_tests_for_pdf,
                follow_up_date=follow_up_str,
            )
    else:
        # online — create Razorpay order and broadcast payment request to POS kiosk
        await ensure_feature_enabled("razorpay", current_user, session)
        logger.info("Pharmacy bill: Processing ONLINE payment for invoice %s", invoice.id)
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_INITIATED", resource_type="invoice", resource_id=invoice.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(dispense.id), "payment_method": "online", "amount": float(invoice.total)})
        
        await session.commit()
        await session.refresh(invoice)
        logger.info("Pharmacy bill: Committed invoice to DB, now creating Razorpay order")
        
        rz_order = create_razorpay_order(
            amount_rupees=float(total),
            receipt=str(invoice.id)[:40],
            notes={"tenant_schema": tenant, "source": "pharmacy"},
        )
        logger.info("Pharmacy bill: Razorpay order created: %s", rz_order)
        
        if rz_order:
            invoice.razorpay_order_id = rz_order["id"]
            logger.info("Pharmacy bill: Set razorpay_order_id=%s on invoice", rz_order["id"])
            
            await session.commit()
            logger.info("Pharmacy bill: Committed razorpay_order_id to DB")
            
            await session.refresh(invoice)
            logger.info(
                "Pharmacy bill: Refreshed invoice - razorpay_order_id=%s, status=%s",
                invoice.razorpay_order_id, invoice.status,
            )

            # Validate Razorpay is configured before broadcasting
            if not settings.RAZORPAY_KEY_ID:
                logger.error("❌ Razorpay online payment requested but RAZORPAY_KEY_ID not configured in environment!")
                raise HTTPException(
                    status_code=500, 
                    detail="Razorpay payment gateway is not configured. Contact administrator."
                )

            # Broadcast payment request to POS screen (kiosk)
            broadcast_payload = {
                "event": "payment_request",
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                "razorpay_order_id": rz_order["id"],
                "invoice_id": str(invoice.id),
                "amount": int(float(total) * 100),  # paise
                "amount_display": f"₹{float(total):.0f}",
                "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Patient",
                "uhid": patient.uhid if patient else "",
                "description": f"Pharmacy Dispense — {patient.first_name} {patient.last_name}" if patient else "Patient",
            }
            
            # Log exactly what's being broadcast
            logger.info(
                "Pharmacy bill: Broadcasting payload - %s",
                json.dumps({
                    "event": broadcast_payload.get("event"),
                    "razorpay_key_id": broadcast_payload.get("razorpay_key_id"),
                    "razorpay_order_id": broadcast_payload.get("razorpay_order_id"),
                    "invoice_id": broadcast_payload.get("invoice_id"),
                    "tenant": tenant,
                })
            )
            
            await ws_manager.broadcast(tenant, "pos:payment", broadcast_payload)
            logger.info("Pharmacy bill: Broadcasted payment_request to POS")
        else:
            logger.error("Pharmacy bill: Failed to create Razorpay order for invoice %s", invoice.id)

    logger.info(
        "Pharmacy bill: Returning invoice %s - status=%s, razorpay_order_id=%s, payment_method=%s",
        invoice.id, invoice.status, invoice.razorpay_order_id, invoice.payment_method,
    )
    return invoice

@router.patch("/{pq_id}/verify-payment", response_model=dict)
async def verify_pharmacy_payment(
    pq_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_permission("PHARMACY_BILLING_VERIFY")),
):
    """
    Verify if Razorpay payment was captured for a pharmacy dispense.
    Used as fallback when webhook misses or modal needs to confirm payment status.
    
    Returns:
    - {success: true, status: "dispensed"} if payment captured and queue advanced
    - {success: false, status: "pending", reason: "..."} if payment not yet captured
    """
    pq = await session.get(PharmacyQueue, pq_id)
    if not pq:
        raise HTTPException(status_code=404, detail="Pharmacy queue item not found")

    # Find the invoice for this pharmacy queue
    invoice = (await session.execute(
        select(Invoice).where(Invoice.pharmacy_queue_id == pq_id)
    )).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found for this pharmacy order")
    record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_VERIFICATION_ATTEMPTED", resource_type="invoice", resource_id=invoice.id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(invoice.pharmacy_dispense_id), "queue_id": str(pq_id)})

    # If already dispensed, no need to verify
    if pq.status == "dispensed":
        return {"success": True, "status": "dispensed"}

    # If invoice already paid, just advance the queue (shouldn't happen but check)
    if invoice.status == "paid":
        dispense = await session.get(PharmacyDispense, invoice.pharmacy_dispense_id) if invoice.pharmacy_dispense_id else None
        if dispense is not None:
            try:
                await authorize_pharmacy_billing(
                    session,
                    dispense_id=dispense.id,
                    tenant_id=dispense.tenant_id,
                    facility_id=dispense.facility_id,
                    confirmed_by=uuid.UUID(str(current_user["sub"])),
                    invoice_id=invoice.id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        if pq.status != "dispensed":
            pq.status = "dispensed"
        await session.commit()
        return {"success": True, "status": "dispensed"}

    # Check if Razorpay order exists and has payment
    if not invoice.razorpay_order_id:
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_VERIFICATION_FAILED", resource_type="invoice", resource_id=invoice.id, new_value={"invoice_id": str(invoice.id), "reason": "No Razorpay order created"})
        await session.commit()
        return {"success": False, "status": "pending", "reason": "No Razorpay order created"}

    payment = fetch_order_payments(invoice.razorpay_order_id)
    if not payment:
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_VERIFICATION_FAILED", resource_type="invoice", resource_id=invoice.id, new_value={"invoice_id": str(invoice.id), "reason": "No captured payment found"})
        await session.commit()
        return {"success": False, "status": "pending", "reason": "No captured payment found on Razorpay"}

    # Payment captured! Mark invoice and queue as paid/dispensed
    invoice.razorpay_payment_id = payment.get("id")
    invoice.payment_method = payment.get("method", "razorpay")
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    dispense = await session.get(PharmacyDispense, invoice.pharmacy_dispense_id) if invoice.pharmacy_dispense_id else None
    if dispense is not None:
        try:
            await authorize_pharmacy_billing(
                session,
                dispense_id=dispense.id,
                tenant_id=dispense.tenant_id,
                facility_id=dispense.facility_id,
                confirmed_by=uuid.UUID(str(current_user["sub"])),
                invoice_id=invoice.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_VERIFICATION_SUCCEEDED", resource_type="invoice", resource_id=invoice.id, patient_id=dispense.patient_id, visit_id=dispense.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(dispense.id), "payment_id": invoice.razorpay_payment_id})
    pq.status = "dispensed"

    # Pharmacy queue is treated as a domain-specific workflow, not a visit-state mutation.
    rx = await session.get(Prescription, pq.prescription_id)

    await session.commit()
    await session.refresh(invoice)
    await session.refresh(pq)

    # Send prescription PDF in background (same as cash flow)
    if rx:
        visit = await session.get(Visit, rx.visit_id)
        patient = await session.get(Patient, visit.patient_id) if visit else None

        if patient and patient.phone:
            consultation = (await session.execute(
                select(Consultation).where(Consultation.visit_id == rx.visit_id)
            )).scalar_one_or_none()
            doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
            department = await session.get(Department, visit.department_id) if visit.department_id else None

            hospital_name_row = await session.execute(
                sql_text("SELECT hospital_name FROM public.tenants WHERE schema_name = current_schema() LIMIT 1")
            )
            hospital_name = (hospital_name_row.scalar() or "Hospital")

            dob_str = patient.dob.isoformat() if patient.dob else None
            follow_up_str = consultation.follow_up_date.isoformat() if consultation and consultation.follow_up_date else None
            visit_date_str = visit.created_at.strftime("%d %b %Y") if hasattr(visit, "created_at") and visit.created_at else datetime.now(timezone.utc).strftime("%d %b %Y")

            lab_order = (await session.execute(
                select(LabOrder).where(LabOrder.visit_id == rx.visit_id)
            )).scalar_one_or_none()
            lab_tests_for_pdf = None
            if lab_order and lab_order.tests:
                lab_tests_for_pdf = [
                    {"test_name": t.get("test", t.get("test_name", "")), "notes": t.get("notes")}
                    for t in lab_order.tests
                ]

            # Note: BackgroundTasks not available in this context, so run inline
            try:
                pdf_url = generate_and_upload_prescription_pdf(
                    hospital_name=hospital_name,
                    patient_name=f"{patient.first_name} {patient.last_name}",
                    uhid=patient.uhid,
                    gender=patient.gender,
                    age=patient.age,
                    dob=dob_str,
                    phone=patient.phone,
                    visit_date=visit_date_str,
                    department_name=department.name if department else None,
                    doctor_name=doctor.full_name if doctor else None,
                    doctor_specialization=doctor.specialization if doctor else None,
                    chief_complaint=consultation.chief_complaint if consultation else None,
                    diagnosis=consultation.diagnosis_icd10 if consultation else None,
                    notes=consultation.notes if consultation else None,
                    medicines=rx.medicines,
                    lab_tests=lab_tests_for_pdf,
                    follow_up_date=follow_up_str,
                )
                send_prescription_whatsapp(
                    to_phone=patient.phone,
                    patient_name=f"{patient.first_name} {patient.last_name}",
                    uhid=patient.uhid,
                    hospital_name=hospital_name,
                    doctor_name=doctor.full_name if doctor else None,
                    pdf_url=pdf_url,
                )
            except Exception:
                logger.exception("Failed to send prescription PDF WhatsApp for UHID=%s after payment verify", patient.uhid)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "pharmacy:update", {
        "event": "pharmacy_status_updated",
        "pq_id": str(pq_id),
        "status": "dispensed",
    })

    return {"success": True, "status": "dispensed"}