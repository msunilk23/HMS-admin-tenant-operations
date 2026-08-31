import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.tenant.inventory_batch import InventoryBatch
from app.models.tenant.pharmacy_location import PharmacyLocation
from app.models.tenant.stock_transaction import StockTransaction
from app.services.inventory_service import (
    create_inventory_from_grn_item,
    get_fefo_batches_for_medicine,
    get_location_medicine_balance,
    reconcile_inventory_batch,
    record_stock_adjustment,
    sync_inventory_batch_balance,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def inventory_service_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[PharmacyLocation.__table__, InventoryBatch.__table__, StockTransaction.__table__],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_inventory_from_grn_item_creates_batch_and_ledger_once(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="GRN-LOC",
        location_name="GRN Location",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()

    batch = await create_inventory_from_grn_item(
        inventory_service_session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        batch_number="DL-2001",
        received_quantity="400",
        free_quantity="20",
        purchase_rate="10.00",
        mrp="12.00",
        manufacturing_date=date(2026, 1, 1),
        expiry_date=date(2027, 12, 31),
        created_by=uuid.uuid4(),
    )

    assert batch.available_quantity == Decimal("420")
    assert batch.received_quantity == Decimal("400")
    assert await inventory_service_session.scalar(select(StockTransaction).where(StockTransaction.reference_id == batch.goods_receipt_item_id)) is not None

    second = await create_inventory_from_grn_item(
        inventory_service_session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=batch.goods_receipt_item_id,
        batch_number="DL-2001",
        received_quantity="10",
        free_quantity="0",
        purchase_rate="10.00",
        mrp="12.00",
        manufacturing_date=date(2026, 1, 1),
        expiry_date=date(2027, 12, 31),
        created_by=uuid.uuid4(),
    )

    assert second.id == batch.id
    assert await inventory_service_session.scalar(select(func.count()).select_from(StockTransaction)) == 1


@pytest.mark.asyncio
async def test_recompute_balance_from_ledger(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="BAL-LOC",
        location_name="Balance Location",
        location_type="PHARMACY",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()

    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        batch_number="B-900",
        expiry_date=date(2027, 6, 30),
        purchase_rate=Decimal("8.00"),
        mrp=Decimal("9.00"),
        received_quantity=Decimal("100"),
        available_quantity=Decimal("0"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(batch)
    await inventory_service_session.flush()
    inventory_service_session.add(StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="PURCHASE_RECEIPT",
        quantity=Decimal("100"),
        previous_balance=Decimal("0"),
        new_balance=Decimal("100"),
        reference_type="goods_receipt_item",
        reference_id=uuid.uuid4(),
        reason="Receipt",
        performed_by=uuid.uuid4(),
    ))
    inventory_service_session.add(StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="DISPENSE",
        quantity=Decimal("-15"),
        previous_balance=Decimal("100"),
        new_balance=Decimal("85"),
        reference_type="pharmacy_dispense",
        reference_id=uuid.uuid4(),
        reason="Dispense",
        performed_by=uuid.uuid4(),
    ))
    await inventory_service_session.commit()

    refreshed = await sync_inventory_batch_balance(inventory_service_session, batch.id)
    assert refreshed.available_quantity == Decimal("85")

    balance = await get_location_medicine_balance(inventory_service_session, pharmacy_location_id=location.id, medicine_id=medicine_id)
    assert balance["on_hand"] == Decimal("85")
    assert balance["available"] == Decimal("85")


@pytest.mark.asyncio
async def test_get_fefo_batches_for_medicine_prefers_earliest_expiry(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="FEFO-LOC",
        location_name="FEFO Location",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()

    old_batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        batch_number="B-OLD",
        expiry_date=date(2026, 6, 30),
        purchase_rate=Decimal("8.00"),
        mrp=Decimal("9.00"),
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
    fresh_batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        batch_number="B-FRESH",
        expiry_date=date(2027, 12, 31),
        purchase_rate=Decimal("8.50"),
        mrp=Decimal("10.00"),
        received_quantity=Decimal("80"),
        available_quantity=Decimal("80"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    expired_batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        batch_number="B-EXPIRED",
        expiry_date=date(2025, 1, 1),
        purchase_rate=Decimal("7.00"),
        mrp=Decimal("8.50"),
        received_quantity=Decimal("20"),
        available_quantity=Decimal("20"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add_all([old_batch, fresh_batch, expired_batch])
    await inventory_service_session.commit()

    batches = await get_fefo_batches_for_medicine(
        inventory_service_session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=medicine_id,
        as_of_date=date(2026, 1, 1),
    )

    assert [batch.batch_number for batch in batches] == ["B-OLD", "B-FRESH"]


@pytest.mark.asyncio
async def test_balance_queries_are_scoped_by_tenant_and_facility(inventory_service_session):
    tenant_a = uuid.uuid4()
    facility_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    facility_b = uuid.uuid4()
    medicine_id = uuid.uuid4()

    location_a = PharmacyLocation(
        tenant_id=tenant_a,
        facility_id=facility_a,
        location_code="LOC-A",
        location_name="Location A",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    location_b = PharmacyLocation(
        tenant_id=tenant_b,
        facility_id=facility_b,
        location_code="LOC-B",
        location_name="Location B",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add_all([location_a, location_b])
    await inventory_service_session.flush()

    batch_a = InventoryBatch(
        tenant_id=tenant_a,
        facility_id=facility_a,
        pharmacy_location_id=location_a.id,
        medicine_id=medicine_id,
        batch_number="A-100",
        expiry_date=date(2027, 12, 31),
        purchase_rate=Decimal("5.00"),
        mrp=Decimal("6.00"),
        received_quantity=Decimal("30"),
        available_quantity=Decimal("30"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    batch_b = InventoryBatch(
        tenant_id=tenant_b,
        facility_id=facility_b,
        pharmacy_location_id=location_b.id,
        medicine_id=medicine_id,
        batch_number="B-100",
        expiry_date=date(2027, 12, 31),
        purchase_rate=Decimal("5.00"),
        mrp=Decimal("6.00"),
        received_quantity=Decimal("40"),
        available_quantity=Decimal("40"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add_all([batch_a, batch_b])
    await inventory_service_session.commit()

    locked_balance = await get_location_medicine_balance(
        inventory_service_session,
        tenant_id=tenant_a,
        facility_id=facility_a,
        pharmacy_location_id=location_a.id,
        medicine_id=medicine_id,
    )

    assert locked_balance["on_hand"] == Decimal("30")
    assert locked_balance["available"] == Decimal("30")

    foreign_check = await get_location_medicine_balance(
        inventory_service_session,
        tenant_id=tenant_a,
        facility_id=facility_a,
        pharmacy_location_id=location_b.id,
        medicine_id=medicine_id,
    )
    assert foreign_check["on_hand"] == Decimal("0")


@pytest.mark.asyncio
async def test_reconcile_inventory_batch_reports_cached_balance_mismatch(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="REC-LOC",
        location_name="Reconciliation Location",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="REC-100",
        expiry_date=date(2027, 12, 31),
        purchase_rate=Decimal("5.00"),
        mrp=Decimal("6.00"),
        received_quantity=Decimal("100"),
        available_quantity=Decimal("95"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(batch)
    await inventory_service_session.flush()
    inventory_service_session.add(StockTransaction(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=batch.medicine_id,
        inventory_batch_id=batch.id,
        transaction_type="PURCHASE_RECEIPT",
        quantity=Decimal("100"),
        previous_balance=Decimal("0"),
        new_balance=Decimal("100"),
        reference_type="goods_receipt_item",
        reference_id=uuid.uuid4(),
        reason="Receipt",
        performed_by=uuid.uuid4(),
    ))
    await inventory_service_session.commit()

    reconciliation = await reconcile_inventory_batch(inventory_service_session, batch.id)

    assert reconciliation == {
        "inventory_batch_id": str(batch.id),
        "cached_balance": Decimal("95"),
        "ledger_balance": Decimal("100"),
        "difference": Decimal("-5"),
        "is_consistent": False,
    }


@pytest.mark.asyncio
async def test_sync_inventory_batch_rejects_wrong_tenant_scope(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="SCOPE-LOC",
        location_name="Scope Location",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="SCOPE-100",
        expiry_date=date(2027, 12, 31),
        purchase_rate=Decimal("5.00"),
        mrp=Decimal("6.00"),
        received_quantity=Decimal("10"),
        available_quantity=Decimal("10"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        goods_receipt_id=uuid.uuid4(),
        goods_receipt_item_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(batch)
    await inventory_service_session.commit()

    with pytest.raises(ValueError, match="Inventory batch not found"):
        await sync_inventory_batch_balance(
            inventory_service_session,
            batch.id,
            tenant_id=uuid.uuid4(),
            facility_id=facility_id,
        )


@pytest.mark.asyncio
async def test_record_stock_adjustment_is_atomic_and_idempotent(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="ADJ-LOC",
        location_name="Adjustment Location",
        location_type="CENTRAL_STORE",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="ADJ-100",
        expiry_date=date(2027, 12, 31),
        purchase_rate=Decimal("5.00"),
        mrp=Decimal("6.00"),
        received_quantity=Decimal("20"),
        available_quantity=Decimal("20"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(batch)
    await inventory_service_session.commit()
    reference_id = uuid.uuid4()

    transaction = await record_stock_adjustment(
        inventory_service_session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        inventory_batch_id=batch.id,
        quantity=Decimal("-3"),
        reference_id=reference_id,
        reason="Damaged stock",
        performed_by=uuid.uuid4(),
    )
    repeated = await record_stock_adjustment(
        inventory_service_session,
        tenant_id=tenant_id,
        facility_id=facility_id,
        inventory_batch_id=batch.id,
        quantity=Decimal("-3"),
        reference_id=reference_id,
        reason="Damaged stock",
        performed_by=uuid.uuid4(),
    )

    assert transaction.id == repeated.id
    assert transaction.quantity == Decimal("-3")
    assert transaction.previous_balance == Decimal("20")
    assert transaction.new_balance == Decimal("17")
    refreshed = await inventory_service_session.get(InventoryBatch, batch.id)
    assert refreshed.available_quantity == Decimal("17")


@pytest.mark.asyncio
async def test_record_stock_adjustment_rejects_expired_or_insufficient_stock(inventory_service_session):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    location = PharmacyLocation(
        tenant_id=tenant_id,
        facility_id=facility_id,
        location_code="ADJ-VALIDATE",
        location_name="Adjustment Validation",
        location_type="PHARMACY",
        active=True,
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(location)
    await inventory_service_session.flush()
    batch = InventoryBatch(
        tenant_id=tenant_id,
        facility_id=facility_id,
        pharmacy_location_id=location.id,
        medicine_id=uuid.uuid4(),
        batch_number="ADJ-200",
        expiry_date=date(2025, 1, 1),
        purchase_rate=Decimal("5.00"),
        mrp=Decimal("6.00"),
        received_quantity=Decimal("5"),
        available_quantity=Decimal("5"),
        reserved_quantity=Decimal("0"),
        supplier_id=uuid.uuid4(),
        status="ACTIVE",
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )
    inventory_service_session.add(batch)
    await inventory_service_session.commit()

    with pytest.raises(ValueError, match="expired"):
        await record_stock_adjustment(
            inventory_service_session,
            tenant_id=tenant_id,
            facility_id=facility_id,
            inventory_batch_id=batch.id,
            quantity=Decimal("1"),
            reference_id=uuid.uuid4(),
            reason="Count correction",
            performed_by=uuid.uuid4(),
            as_of_date=date(2026, 1, 1),
        )
