import uuid
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.stock_transaction import StockTransaction


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def transaction_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[PharmacyLocation.__table__, StockTransaction.__table__],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


def test_stock_transaction_table_contract():
    columns = StockTransaction.__table__.c
    assert {"tenant_id", "facility_id", "pharmacy_location_id", "medicine_id", "inventory_batch_id", "transaction_type", "quantity", "previous_balance", "new_balance", "reference_type", "reference_id", "reason", "performed_by", "created_at"} <= set(columns.keys())
    assert "updated_at" not in columns.keys()


@pytest.mark.asyncio
async def test_signed_quantity_and_ledger_metadata_are_persisted(transaction_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="TEST-STORE",
        location_name="Test Store",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    transaction_session.add(location)
    await transaction_session.flush()

    tx = StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        inventory_batch_id=uuid.uuid4(),
        transaction_type="PURCHASE_RECEIPT",
        quantity=Decimal("100"),
        previous_balance=Decimal("0"),
        new_balance=Decimal("100"),
        reference_type="goods_receipt",
        reference_id=uuid.uuid4(),
        reason="Initial receipt",
        performed_by=uuid.uuid4(),
    )
    transaction_session.add(tx)
    await transaction_session.commit()

    saved = await transaction_session.scalar(select(StockTransaction).where(StockTransaction.reference_id == tx.reference_id))
    assert saved is not None
    assert saved.quantity == Decimal("100")
    assert saved.transaction_type == "PURCHASE_RECEIPT"
    assert saved.new_balance == Decimal("100")
    assert saved.created_at is not None


@pytest.mark.asyncio
async def test_negative_quantity_is_supported_for_for_stock_out_and_adjustment(transaction_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="TEST-STORE-2",
        location_name="Test Store 2",
        location_type="PHARMACY",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    transaction_session.add(location)
    await transaction_session.flush()

    tx = StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        inventory_batch_id=uuid.uuid4(),
        transaction_type="DISPENSE",
        quantity=Decimal("-10"),
        previous_balance=Decimal("25"),
        new_balance=Decimal("15"),
        reference_type="pharmacy_dispense",
        reference_id=uuid.uuid4(),
        reason="Dispense",
        performed_by=uuid.uuid4(),
    )
    transaction_session.add(tx)
    await transaction_session.commit()

    saved = await transaction_session.scalar(select(StockTransaction).where(StockTransaction.transaction_type == "DISPENSE"))
    assert saved.quantity == Decimal("-10")
    assert saved.previous_balance == Decimal("25")
    assert saved.new_balance == Decimal("15")
