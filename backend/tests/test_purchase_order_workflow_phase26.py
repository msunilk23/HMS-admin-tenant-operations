import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.pharmacy import (
    approve_purchase_order,
    cancel_purchase_order,
    create_purchase_order,
    reject_purchase_order,
    send_purchase_order,
    submit_purchase_order,
    update_purchase_order,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.purchase_order import PurchaseOrder
from app.models.tenant.supplier import Supplier
from app.schemas.purchase_order import PurchaseOrderCreate, PurchaseOrderItemCreate, PurchaseOrderUpdate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


ADMIN = {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": "tenant_a"}
STORE_MANAGER = {"sub": str(uuid.uuid4()), "role": "store_manager", "tenant_schema": "tenant_a"}


@pytest_asyncio.fixture
async def po_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Supplier.__table__, GenericMedicine.__table__, DosageForm.__table__,
                MedicineProduct.__table__, PurchaseOrder.__table__,
                __import__("app.models.tenant.purchase_order", fromlist=["PurchaseOrderItem"]).PurchaseOrderItem.__table__,
                AuditLog.__table__,
            ],
        )
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


def payload(supplier_id, product_id):
    return PurchaseOrderCreate(
        supplier_id=supplier_id,
        items=[PurchaseOrderItemCreate(
            medicine_product_id=product_id,
            ordered_quantity=Decimal("100"),
            free_quantity=Decimal("5"),
            unit_of_measure="tablet",
            unit_purchase_price=Decimal("10.00"),
            mrp=Decimal("12.00"),
            discount_percent=Decimal("5"),
            gst_percent=Decimal("18"),
        )],
    )


@pytest.mark.asyncio
async def test_po_creation_calculates_totals_server_side(po_context):
    session, supplier, product = po_context
    order = await create_purchase_order(payload(supplier.id, product.id), session, STORE_MANAGER)
    assert order.status == "DRAFT"
    assert order.po_number.startswith("PO-")
    assert order.subtotal == Decimal("1000.00")
    assert order.discount_amount == Decimal("50.00")
    assert order.tax_amount == Decimal("171.00")
    assert order.total_amount == Decimal("1121.00")
    assert order.items[0].taxable_amount == Decimal("950.00")
    assert order.items[0].line_total == Decimal("1121.00")


@pytest.mark.asyncio
async def test_po_draft_update_and_immutability_after_approval(po_context):
    session, supplier, product = po_context
    order = await create_purchase_order(payload(supplier.id, product.id), session, STORE_MANAGER)
    updated = await update_purchase_order(order.id, PurchaseOrderUpdate(notes="Updated draft"), session, STORE_MANAGER)
    assert updated.notes == "Updated draft"
    await submit_purchase_order(order.id, session, STORE_MANAGER)
    await approve_purchase_order(order.id, session, ADMIN)
    with pytest.raises(Exception) as error:
        await update_purchase_order(order.id, PurchaseOrderUpdate(notes="Must not change"), session, STORE_MANAGER)
    assert "Only draft" in str(error.value)


@pytest.mark.asyncio
async def test_po_lifecycle_requires_valid_transitions_and_reasons(po_context):
    session, supplier, product = po_context
    order = await create_purchase_order(payload(supplier.id, product.id), session, STORE_MANAGER)
    with pytest.raises(Exception):
        await send_purchase_order(order.id, session, STORE_MANAGER)
    await submit_purchase_order(order.id, session, STORE_MANAGER)
    await approve_purchase_order(order.id, session, ADMIN)
    await send_purchase_order(order.id, session, STORE_MANAGER)
    with pytest.raises(Exception) as error:
        await cancel_purchase_order(order.id, None, session, STORE_MANAGER)
    assert "reason is required" in str(error.value)
    cancelled = await cancel_purchase_order(order.id, "Supplier withdrew quotation", session, STORE_MANAGER)
    assert cancelled.status == "CANCELLED"
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(order.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "SUBMITTED", "APPROVED", "SENT", "CANCELLED"]


@pytest.mark.asyncio
async def test_po_rejection_requires_reason_and_is_terminal(po_context):
    session, supplier, product = po_context
    order = await create_purchase_order(payload(supplier.id, product.id), session, STORE_MANAGER)
    await submit_purchase_order(order.id, session, STORE_MANAGER)
    with pytest.raises(Exception):
        await reject_purchase_order(order.id, None, session, ADMIN)
    rejected = await reject_purchase_order(order.id, "Price exceeds approved budget", session, ADMIN)
    assert rejected.status == "REJECTED"
    with pytest.raises(Exception):
        await approve_purchase_order(order.id, session, ADMIN)


@pytest.mark.asyncio
async def test_po_rejects_inactive_supplier_or_product(po_context):
    session, supplier, product = po_context
    supplier.is_active = False
    await session.commit()
    with pytest.raises(Exception) as error:
        await create_purchase_order(payload(supplier.id, product.id), session, STORE_MANAGER)
    assert "Supplier is missing or inactive" in str(error.value)
