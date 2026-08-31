import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.tenant.route import Route
from app.models.tenant.supplier import Supplier


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Supplier.__table__,
                GenericMedicine.__table__,
                DosageForm.__table__,
                Route.__table__,
                MedicineProduct.__table__,
                PurchaseOrder.__table__,
                PurchaseOrderItem.__table__,
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        supplier = Supplier(supplier_code="CIPLA", supplier_name="Cipla")
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol")
        form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        current.add_all([supplier, generic, form])
        await current.flush()
        product = MedicineProduct(
            code="DOLO-500",
            generic_medicine_id=generic.id,
            brand_name="Dolo",
            strength="500",
            unit="mg",
            dosage_form_id=form.id,
        )
        current.add(product)
        await current.flush()
        yield current, supplier, product
    await engine.dispose()


@pytest.mark.asyncio
async def test_purchase_order_header_item_relationship_and_decimal_fields(session):
    current, supplier, product = session
    order = PurchaseOrder(
        po_number="PO-2026-000001",
        supplier_id=supplier.id,
        po_date=date(2026, 8, 26),
        required_by_date=date(2026, 9, 2),
        subtotal=Decimal("1000.00"),
        discount_amount=Decimal("50.00"),
        tax_amount=Decimal("171.00"),
        total_amount=Decimal("1121.00"),
        notes="Initial pharmacy order",
    )
    order.items.append(PurchaseOrderItem(
        medicine_product_id=product.id,
        ordered_quantity=Decimal("100.000"),
        free_quantity=Decimal("5.000"),
        unit_of_measure="tablet",
        unit_purchase_price=Decimal("10.00"),
        mrp=Decimal("12.00"),
        discount_percent=Decimal("5.00"),
        gst_percent=Decimal("18.00"),
        taxable_amount=Decimal("950.00"),
        tax_amount=Decimal("171.00"),
        line_total=Decimal("1121.00"),
    ))
    current.add(order)
    await current.commit()

    stored = (await current.execute(select(PurchaseOrder))).scalar_one()
    assert stored.status == "DRAFT"
    assert stored.supplier_id == supplier.id
    assert len(stored.items) == 1
    assert stored.items[0].medicine_product_id == product.id
    assert stored.items[0].ordered_quantity == Decimal("100.000")
    assert stored.items[0].line_total == Decimal("1121.00")


@pytest.mark.asyncio
async def test_purchase_order_number_is_unique(session):
    current, supplier, _ = session
    current.add(PurchaseOrder(po_number="PO-2026-000001", supplier_id=supplier.id))
    await current.commit()
    current.add(PurchaseOrder(po_number="PO-2026-000001", supplier_id=supplier.id))
    with pytest.raises(Exception):
        await current.commit()
    await current.rollback()


def test_purchase_order_foreign_keys_and_scope_contract():
    order_fks = {
        fk.target_fullname
        for fk in PurchaseOrder.__table__.c.supplier_id.foreign_keys
    }
    item_fks = {
        fk.target_fullname
        for fk in PurchaseOrderItem.__table__.c.medicine_product_id.foreign_keys
    }
    assert order_fks == {"suppliers.id"}
    assert item_fks == {"medicine_products.id"}
    assert "facility_id" not in PurchaseOrder.__table__.c
    assert "inventory" not in PurchaseOrderItem.__table__.c
    assert "batch_number" not in PurchaseOrderItem.__table__.c
    assert any(constraint.name == "uq_purchase_orders_po_number" for constraint in PurchaseOrder.__table__.constraints)
