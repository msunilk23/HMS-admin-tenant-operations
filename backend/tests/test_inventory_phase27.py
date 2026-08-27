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

from app.db.base import Base
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.pharmacy_location import PharmacyLocation


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def inventory_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[PharmacyLocation.__table__, InventoryBatch.__table__],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_pharmacy_location_contract_and_active_state(inventory_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="OPD-PHARMACY",
        location_name="OPD Pharmacy",
        location_type="OPD_PHARMACY",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_session.add(location)
    await inventory_session.commit()

    saved = await inventory_session.scalar(select(PharmacyLocation).where(PharmacyLocation.location_code == "OPD-PHARMACY"))
    assert saved is not None
    assert saved.location_type == "OPD_PHARMACY"
    assert saved.active is True


@pytest.mark.asyncio
async def test_inventory_batch_duplicate_for_same_location_and_medicine_is_rejected(inventory_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    location_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="CENTRAL-STORE",
        location_name="Central Store",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_session.add(location)
    await inventory_session.flush()

    first = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        batch_number="DL-001",
        expiry_date=date(2027, 1, 31),
        purchase_rate=Decimal("10.00"),
        mrp=Decimal("12.00"),
        received_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_session.add(first)
    await inventory_session.commit()

    duplicate = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        batch_number="DL-001",
        expiry_date=date(2027, 2, 28),
        purchase_rate=Decimal("10.50"),
        mrp=Decimal("12.50"),
        received_quantity=Decimal("50"),
        available_quantity=Decimal("50"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_session.add(duplicate)
    with pytest.raises(Exception):
        await inventory_session.commit()


def test_inventory_batch_table_contract():
    columns = InventoryBatch.__table__.c
    assert {"tenant_id", "facility_id", "pharmacy_location_id", "medicine_id", "batch_number", "expiry_date", "purchase_rate", "mrp", "received_quantity", "available_quantity", "reserved_quantity", "status"} <= set(columns.keys())
    active_constraint_names = {constraint.name for constraint in InventoryBatch.__table__.constraints}
    assert any(name == "uq_inventory_batches_tenant_location_medicine_batch" for name in active_constraint_names)
