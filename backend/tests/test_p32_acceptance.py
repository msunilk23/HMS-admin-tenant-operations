import asyncio
import os
import socket
import uuid
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.tenant import (
    AuditLog, InventoryBatch, PharmacyLocation, ProductRecall, RecallAffectedStock,
    StockQuarantine, StockTransaction, StockTransfer, StockTransferDiscrepancy, StockTransferItem,
)
from app.schemas.p32 import RecallCreate, TransferCreate, TransferReceive
from app.services.p32_service import (
    approve_recall, approve_transfer, create_recall, create_transfer, dispatch_transfer,
    receive_transfer, reconcile_discrepancy,
)

PG_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")


def _reachable():
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="PostgreSQL is not reachable")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def context():
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    schema = f"p32_{uuid.uuid4().hex[:8]}"
    ids = {name: uuid.uuid4() for name in ("tenant", "facility", "source", "destination", "third", "medicine", "maker", "checker", "receiver")}
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}", public'))
        tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        session = AsyncSession(bind=connection, expire_on_commit=False)
        for name in ("source", "destination", "third"):
            session.add(PharmacyLocation(id=ids[name], tenant_id=ids["tenant"], facility_id=ids["facility"], location_code=name.upper(), location_name=name.title(), location_type="PHARMACY", active=True))
        await session.flush()
        for location, suffix, quantity in ((ids["source"], "A", "20"), (ids["third"], "B", "7")):
            session.add(InventoryBatch(
                tenant_id=ids["tenant"], facility_id=ids["facility"], pharmacy_location_id=location,
                medicine_id=ids["medicine"], batch_number="P32-RECALL", manufacturing_date=date.today() - timedelta(days=30),
                expiry_date=date.today() + timedelta(days=365), purchase_rate=Decimal("10"), mrp=Decimal("12"),
                received_quantity=Decimal(quantity), available_quantity=Decimal(quantity), reserved_quantity=Decimal("0"), status="ACTIVE",
            ))
        session.add(InventoryBatch(
            id=uuid.uuid4(), tenant_id=ids["tenant"], facility_id=ids["facility"], pharmacy_location_id=ids["source"],
            medicine_id=ids["medicine"], batch_number="P32-TRANSFER", manufacturing_date=date.today() - timedelta(days=20),
            expiry_date=date.today() + timedelta(days=400), purchase_rate=Decimal("8"), mrp=Decimal("11"),
            received_quantity=Decimal("30"), available_quantity=Decimal("30"), reserved_quantity=Decimal("0"), status="ACTIVE",
        ))
        await session.commit()
        await session.close()
    test_context = {**ids, "engine": engine, "session_factory": async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession), "schema": schema, "sessions": []}
    yield test_context
    for session in test_context["sessions"]:
        await session.close()
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await engine.dispose()


async def _session(context):
    session = context["session_factory"]()
    context["sessions"].append(session)
    await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    return session


def _user(context, name, role="pharmacist"):
    return {"sub": str(context[name]), "role": role, "tenant_id": str(context["tenant"]), "facility_id": str(context["facility"])}


@pytest.mark.asyncio(loop_scope="module")
async def test_recall_maker_checker_quarantines_all_locations_and_correlates_ledger(context):
    session = await _session(context)
    recall = await create_recall(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=RecallCreate(
        medicine_id=context["medicine"], batch_number="P32-RECALL", recall_reason="Confirmed manufacturer quality recall", regulatory_reference="CDSCO-P32", idempotency_key="recall-create",
    ), current_user=_user(context, "maker"))
    await session.commit()
    recall_id = recall.id
    with pytest.raises(ValueError, match="own recall"):
        await approve_recall(session, recall_id=recall_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="recall-self", current_user=_user(context, "maker", "store_manager"))
    await session.rollback()
    await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    recall = await approve_recall(session, recall_id=recall_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="recall-approve", current_user=_user(context, "checker", "hospital_admin"))
    await session.commit()
    assert recall.status == "ACTIVE"
    batches = (await session.execute(select(InventoryBatch).where(InventoryBatch.batch_number == "P32-RECALL").order_by(InventoryBatch.id))).scalars().all()
    assert [(item.status, item.available_quantity) for item in batches] == [("RECALLED", Decimal("0.000")), ("RECALLED", Decimal("0.000"))]
    assert len((await session.execute(select(RecallAffectedStock).where(RecallAffectedStock.recall_id == recall.id))).scalars().all()) == 2
    quarantines = (await session.execute(select(StockQuarantine).where(StockQuarantine.reason == "RECALL"))).scalars().all()
    assert sum((item.total_quantity_quarantined for item in quarantines), Decimal("0")) == Decimal("27.000")
    ledger = (await session.execute(select(StockTransaction).where(StockTransaction.correlation_reference == recall.reference_key))).scalars().all()
    assert len(ledger) == 2 and sum((item.quantity for item in ledger), Decimal("0")) == Decimal("-27.000")
    assert await session.scalar(select(AuditLog.id).where(AuditLog.resource_id == str(recall.id)))
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_transfer_exact_balances_identity_and_idempotent_lifecycle(context):
    session = await _session(context)
    source = await session.scalar(select(InventoryBatch).where(InventoryBatch.batch_number == "P32-TRANSFER"))
    source_id = source.id
    transfer = await create_transfer(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferCreate(
        source_location_id=context["source"], destination_location_id=context["destination"], items=[{"inventory_batch_id": source.id, "quantity": "10"}], idempotency_key="transfer-create",
    ), current_user=_user(context, "maker"))
    await session.commit()
    transfer_id = transfer.id
    with pytest.raises(ValueError, match="own transfer"):
        await approve_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="transfer-self", current_user=_user(context, "maker", "store_manager"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    transfer = await approve_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="transfer-approve", current_user=_user(context, "checker", "hospital_admin"))
    await session.commit()
    assert (await session.get(InventoryBatch, source.id)).reserved_quantity == Decimal("10.000")
    transfer = await dispatch_transfer(session, transfer_id=transfer.id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="transfer-dispatch", current_user=_user(context, "checker"))
    await session.commit()
    item = await session.scalar(select(StockTransferItem).where(StockTransferItem.transfer_id == transfer.id))
    transfer = await receive_transfer(session, transfer_id=transfer.id, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferReceive(items=[{"transfer_item_id": item.id, "quantity_received": "10"}], idempotency_key="transfer-receive"), current_user=_user(context, "receiver"))
    await session.commit()
    replay = await receive_transfer(session, transfer_id=transfer.id, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferReceive(items=[{"transfer_item_id": item.id, "quantity_received": "10"}], idempotency_key="transfer-receive"), current_user=_user(context, "receiver"))
    assert replay.id == transfer.id and transfer.status == "RECEIVED"
    source = await session.get(InventoryBatch, source.id)
    destination = await session.get(InventoryBatch, item.destination_batch_id)
    assert (source.available_quantity, source.reserved_quantity, destination.available_quantity) == (Decimal("20.000"), Decimal("0.000"), Decimal("10.000"))
    assert (destination.batch_number, destination.expiry_date, destination.manufacturing_date) == (source.batch_number, source.expiry_date, source.manufacturing_date)
    ledger = (await session.execute(select(StockTransaction).where(StockTransaction.correlation_reference == transfer.reference_key).order_by(StockTransaction.created_at))).scalars().all()
    assert [(row.transaction_type, row.quantity) for row in ledger] == [("TRANSFER_DISPATCH", Decimal("-10.000")), ("TRANSFER_RECEIVE", Decimal("10.000"))]
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_partial_receipt_discrepancy_reconciliation_and_excess_rollback(context):
    session = await _session(context)
    source = await session.scalar(select(InventoryBatch).where(InventoryBatch.batch_number == "P32-TRANSFER"))
    source_id = source.id
    transfer = await create_transfer(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferCreate(
        source_location_id=context["source"], destination_location_id=context["third"], items=[{"inventory_batch_id": source.id, "quantity": "6"}], idempotency_key="partial-create",
    ), current_user=_user(context, "maker"))
    await session.commit()
    await approve_transfer(session, transfer_id=transfer.id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="partial-approve", current_user=_user(context, "checker", "hospital_admin"))
    await session.commit()
    await dispatch_transfer(session, transfer_id=transfer.id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="partial-dispatch", current_user=_user(context, "checker"))
    await session.commit()
    item = await session.scalar(select(StockTransferItem).where(StockTransferItem.transfer_id == transfer.id))
    transfer_id = transfer.id
    item_id = item.id
    before = await session.scalar(select(InventoryBatch.available_quantity).where(InventoryBatch.id == source_id))
    with pytest.raises(ValueError, match="exceed"):
        await receive_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferReceive(items=[{"transfer_item_id": item_id, "quantity_received": "7", "discrepancy_type": "EXCESS", "discrepancy_quantity": "1", "discrepancy_notes": "Unexpected extra unit"}], idempotency_key="partial-excess"), current_user=_user(context, "receiver"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    assert await session.scalar(select(InventoryBatch.available_quantity).where(InventoryBatch.id == source_id)) == before
    transfer = await receive_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferReceive(items=[{"transfer_item_id": item_id, "quantity_received": "4", "discrepancy_type": "SHORTAGE", "discrepancy_quantity": "2", "discrepancy_notes": "Two units missing on sealed tote"}], idempotency_key="partial-receive"), current_user=_user(context, "receiver"))
    await session.commit()
    discrepancy = await session.scalar(select(StockTransferDiscrepancy).where(StockTransferDiscrepancy.transfer_id == transfer.id))
    assert discrepancy.status == "OPEN" and discrepancy.quantity == Decimal("2.000")
    discrepancy = await reconcile_discrepancy(session, discrepancy_id=discrepancy.id, tenant_id=context["tenant"], facility_id=context["facility"], action="WRITE_OFF_SHORTAGE", notes="Manager approved carrier shortage write-off", idempotency_key="partial-reconcile", current_user=_user(context, "checker", "hospital_admin"))
    await session.commit()
    assert discrepancy.status == "RECONCILED"
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_competing_transfer_approvals_cannot_over_reserve(context):
    setup = await _session(context)
    batch = InventoryBatch(
        tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["source"],
        medicine_id=context["medicine"], batch_number="P32-COMPETING", expiry_date=date.today() + timedelta(days=500),
        purchase_rate=Decimal("7"), received_quantity=Decimal("10"), available_quantity=Decimal("10"),
        reserved_quantity=Decimal("0"), status="ACTIVE",
    )
    setup.add(batch); await setup.commit()
    transfer_ids = []
    for sequence in (1, 2):
        transfer = await create_transfer(setup, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferCreate(
            source_location_id=context["source"], destination_location_id=context["destination"],
            items=[{"inventory_batch_id": batch.id, "quantity": "8"}], idempotency_key=f"competing-create-{sequence}",
        ), current_user=_user(context, "maker"))
        await setup.commit(); transfer_ids.append(transfer.id)

    async def approve(transfer_id, sequence):
        session = await _session(context)
        try:
            await approve_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key=f"competing-approve-{sequence}", current_user=_user(context, "checker", "hospital_admin"))
            await session.commit()
            return "approved"
        except ValueError:
            await session.rollback()
            return "rejected"

    outcomes = await asyncio.gather(*(approve(transfer_id, sequence) for sequence, transfer_id in enumerate(transfer_ids, 1)))
    verify = await _session(context)
    reserved = await verify.scalar(select(InventoryBatch.reserved_quantity).where(InventoryBatch.id == batch.id))
    statuses = (await verify.execute(select(StockTransfer.status).where(StockTransfer.id.in_(transfer_ids)))).scalars().all()
    assert sorted(outcomes) == ["approved", "rejected"]
    assert reserved == Decimal("8.000")
    assert sorted(statuses) == ["APPROVED", "DRAFT"]


@pytest.mark.asyncio(loop_scope="module")
async def test_dispatch_and_receipt_mutations_roll_back_atomically(context):
    session = await _session(context)
    batch = InventoryBatch(
        tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=context["source"],
        medicine_id=context["medicine"], batch_number="P32-ROLLBACK", expiry_date=date.today() + timedelta(days=600),
        purchase_rate=Decimal("6"), received_quantity=Decimal("9"), available_quantity=Decimal("9"),
        reserved_quantity=Decimal("0"), status="ACTIVE",
    )
    session.add(batch); await session.commit()
    transfer = await create_transfer(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferCreate(
        source_location_id=context["source"], destination_location_id=context["third"],
        items=[{"inventory_batch_id": batch.id, "quantity": "3"}], idempotency_key="rollback-create",
    ), current_user=_user(context, "maker"))
    await session.commit()
    await approve_transfer(session, transfer_id=transfer.id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="rollback-approve", current_user=_user(context, "checker", "hospital_admin"))
    await session.commit()
    transfer_id = transfer.id; batch_id = batch.id

    await dispatch_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="rollback-dispatch-probe", current_user=_user(context, "checker"))
    await session.rollback()
    verify = await _session(context)
    assert await verify.scalar(select(StockTransfer.status).where(StockTransfer.id == transfer_id)) == "APPROVED"
    assert await verify.scalar(select(InventoryBatch.available_quantity).where(InventoryBatch.id == batch_id)) == Decimal("9.000")
    assert await verify.scalar(select(InventoryBatch.reserved_quantity).where(InventoryBatch.id == batch_id)) == Decimal("3.000")
    await verify.close()

    session = await _session(context)
    await dispatch_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="rollback-dispatch-commit", current_user=_user(context, "checker"))
    await session.commit()
    item = await session.scalar(select(StockTransferItem).where(StockTransferItem.transfer_id == transfer_id))
    item_id = item.id
    await receive_transfer(session, transfer_id=transfer_id, tenant_id=context["tenant"], facility_id=context["facility"], payload=TransferReceive(
        items=[{"transfer_item_id": item_id, "quantity_received": "3"}], idempotency_key="rollback-receive-probe",
    ), current_user=_user(context, "receiver"))
    await session.rollback()
    verify = await _session(context)
    assert await verify.scalar(select(StockTransfer.status).where(StockTransfer.id == transfer_id)) == "IN_TRANSIT"
    assert await verify.scalar(select(StockTransferItem.destination_batch_id).where(StockTransferItem.id == item_id)) is None
    assert await verify.scalar(select(InventoryBatch.available_quantity).where(InventoryBatch.id == batch_id)) == Decimal("6.000")
