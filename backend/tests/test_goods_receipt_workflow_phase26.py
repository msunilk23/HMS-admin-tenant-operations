import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.pharmacy import (
    create_goods_receipt,
    create_purchase_order,
    finalize_goods_receipt,
    receive_goods_receipt_item,
    reject_goods_receipt,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.goods_receipt import GoodsReceipt, GoodsReceiptItem
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.tenant.supplier import Supplier
from app.schemas.goods_receipt import GoodsReceiptCreate, GoodsReceiptItemCreate
from app.schemas.purchase_order import PurchaseOrderCreate, PurchaseOrderItemCreate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


ADMIN = {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": "tenant_a"}
STORE = {"sub": str(uuid.uuid4()), "role": "store_manager", "tenant_schema": "tenant_a"}


@pytest_asyncio.fixture
async def grn_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            Supplier.__table__, GenericMedicine.__table__, DosageForm.__table__, MedicineProduct.__table__,
            PurchaseOrder.__table__, PurchaseOrderItem.__table__, GoodsReceipt.__table__, GoodsReceiptItem.__table__, AuditLog.__table__,
        ])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        supplier = Supplier(supplier_code="SUP-1", supplier_name="Supplier One")
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol")
        form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        session.add_all([supplier, generic, form])
        await session.flush()
        product = MedicineProduct(code="DOLO-500", generic_medicine_id=generic.id, brand_name="Dolo", strength="500", unit="mg", dosage_form_id=form.id)
        session.add(product)
        await session.commit()
        yield session, supplier, product
    await engine.dispose()


async def sent_order(session, supplier, product, quantity=Decimal("100")):
    order = PurchaseOrder(
        po_number=f"PO-{uuid.uuid4().hex[:8].upper()}", supplier_id=supplier.id, status="SENT",
        subtotal=quantity * Decimal("10"), total_amount=quantity * Decimal("10"),
    )
    order.items.append(PurchaseOrderItem(
        medicine_product_id=product.id, ordered_quantity=quantity, unit_of_measure="tablet",
        unit_purchase_price=Decimal("10.00"), gst_percent=Decimal("18"),
    ))
    session.add(order)
    await session.commit()
    return order


@pytest.mark.asyncio
async def test_grn_receipt_calculates_totals_and_finalizes_full_po(grn_context):
    session, supplier, product = grn_context
    order = await sent_order(session, supplier, product)
    receipt = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id, received_date=date.today()), session, STORE)
    po_item = order.items[0]
    item = await receive_goods_receipt_item(
        receipt.id,
        GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("100"), free_quantity=Decimal("5"), batch_number="B-1", expiry_date=date(2027, 1, 31)),
        session,
        STORE,
    )
    assert item.purchase_rate == Decimal("10.00")
    assert item.taxable_amount == Decimal("1000.00")
    assert item.tax_amount == Decimal("180.00")
    assert item.line_total == Decimal("1180.00")
    finalized = await finalize_goods_receipt(receipt.id, session, STORE)
    assert finalized.status == "FULLY_RECEIVED"
    refreshed_order = await session.get(PurchaseOrder, order.id)
    assert refreshed_order.status == "FULLY_RECEIVED"
    assert refreshed_order.items[0].received_quantity == Decimal("100.000")


@pytest.mark.asyncio
async def test_partial_receipt_allows_a_later_grn_for_remaining_quantity(grn_context):
    session, supplier, product = grn_context
    order = await sent_order(session, supplier, product)
    first = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, STORE)
    po_item = order.items[0]
    await receive_goods_receipt_item(first.id, GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("40"), batch_number="B-PART-1", expiry_date=date(2027, 1, 31)), session, STORE)
    first_final = await finalize_goods_receipt(first.id, session, STORE)
    assert first_final.status == "PARTIALLY_RECEIVED"
    assert (await session.get(PurchaseOrder, order.id)).status == "PARTIALLY_RECEIVED"
    second = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, STORE)
    await receive_goods_receipt_item(second.id, GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("60"), batch_number="B-PART-2", expiry_date=date(2027, 1, 31)), session, STORE)
    second_final = await finalize_goods_receipt(second.id, session, STORE)
    assert second_final.status == "FULLY_RECEIVED"
    assert (await session.get(PurchaseOrder, order.id)).status == "FULLY_RECEIVED"


@pytest.mark.asyncio
async def test_receiving_rejects_over_receipt_and_active_duplicate_grn(grn_context):
    session, supplier, product = grn_context
    order = await sent_order(session, supplier, product)
    first = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, STORE)
    with pytest.raises(Exception) as active_error:
        await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, STORE)
    assert "active goods receipt" in str(active_error.value)
    po_item = order.items[0]
    with pytest.raises(Exception) as over_error:
        await receive_goods_receipt_item(first.id, GoodsReceiptItemCreate(purchase_order_item_id=po_item.id, received_quantity=Decimal("101"), batch_number="B-OVER", expiry_date=date(2027, 1, 31)), session, STORE)
    assert "exceeds" in str(over_error.value)


@pytest.mark.asyncio
async def test_rejected_grn_is_terminal_and_audited(grn_context):
    session, supplier, product = grn_context
    order = await sent_order(session, supplier, product)
    receipt = await create_goods_receipt(GoodsReceiptCreate(purchase_order_id=order.id), session, STORE)
    rejected = await reject_goods_receipt(receipt.id, "Shipment damaged", session, ADMIN)
    assert rejected.status == "REJECTED"
    with pytest.raises(Exception):
        await finalize_goods_receipt(receipt.id, session, STORE)
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(receipt.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "REJECT"]
