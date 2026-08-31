import asyncio
import os
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.api.v1.p33 import _commit
from app.models.tenant import AuditLog, CountDetail, CountRecount, CountRecountDetail, InventoryBatch, PharmacyLocation, StockCount, StockCountOperation, StockTransaction
from app.schemas.p33 import CountCreate
from app.services.inventory_service import record_stock_adjustment
from app.services.p33_service import (
    P33ConflictError, P33NotFoundError, P33ValidationError, add_unexpected_stock, apply_count, approve_count,
    cancel_count, create_count, record_detail, record_recount_detail, request_recount,
    resubmit_recount, start_count, start_recount, submit_count,
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
    schema = f"p33_{uuid.uuid4().hex[:8]}"
    ids = {name: uuid.uuid4() for name in ("tenant", "other_tenant", "facility", "other_facility", "location", "medicine", "counter", "manager", "recounter")}
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}", public'))
        tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        session = AsyncSession(bind=connection, expire_on_commit=False)
        session.add(PharmacyLocation(id=ids["location"], tenant_id=ids["tenant"], facility_id=ids["facility"], location_code="P33", location_name="P33 Count Store", location_type="PHARMACY", active=True))
        await session.commit()
        await session.close()
    value = {**ids, "engine": engine, "schema": schema, "session_factory": async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession), "sessions": []}
    yield value
    for session in value["sessions"]:
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
    return {"sub": str(context[name]), "role": role, "tenant_id": str(context["tenant"]), "facility_id": str(context["facility"]), "tenant_schema": context["schema"]}


async def _batch(context, name: str, *, available="100", reserved="10", cost="20", location_id=None):
    session = await _session(context)
    batch = InventoryBatch(
        tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=location_id or context["location"],
        medicine_id=context["medicine"], batch_number=name, expiry_date=date.today() + timedelta(days=365),
        purchase_rate=Decimal(cost), received_quantity=Decimal(available), available_quantity=Decimal(available),
        reserved_quantity=Decimal(reserved), status="ACTIVE",
    )
    session.add(batch)
    await session.commit()
    return batch


async def _started_count(context, batch, prefix: str):
    session = await _session(context)
    created = await create_count(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=CountCreate(
        pharmacy_location_id=context["location"], count_type="PARTIAL", selected_batch_ids=[batch.id],
    ), idempotency_key=f"{prefix}-create", current_user=_user(context, "counter"))
    await session.commit()
    started = await start_count(session, count_id=uuid.UUID(created["id"]), tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key=f"{prefix}-start", current_user=_user(context, "counter"))
    await session.commit()
    detail = await session.scalar(select(CountDetail).where(CountDetail.count_id == uuid.UUID(started["id"])))
    return session, uuid.UUID(started["id"]), detail


@pytest.mark.asyncio(loop_scope="module")
async def test_full_workflow_snapshot_freeze_approval_and_signed_apply(context):
    batch = await _batch(context, "P33-MAIN")
    session, count_id, detail = await _started_count(context, batch, "main")
    detail_id = detail.id
    assert (detail.available_quantity, detail.reserved_quantity, detail.system_quantity) == (Decimal("100.000"), Decimal("10.000"), Decimal("110.000"))
    with pytest.raises(ValueError, match="frozen"):
        await record_stock_adjustment(session, tenant_id=context["tenant"], facility_id=context["facility"], inventory_batch_id=batch.id, quantity="1", reference_id=uuid.uuid4(), reason="blocked", commit=False)
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    detail = await session.get(CountDetail, detail_id)
    result = await record_detail(session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("105"), version=1, variance_reason="Five units short", evidence=None, idempotency_key="main-record", current_user=_user(context, "counter"))
    await session.commit()
    assert result["variance_quantity"] == "-5.000" and result["classifications"] == ["OUTSIDE_TOLERANCE"]
    with pytest.raises(P33ConflictError, match="version"):
        await record_detail(session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("104"), version=1, variance_reason=None, evidence=None, idempotency_key="main-stale", current_user=_user(context, "counter"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    await submit_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="main-submit", current_user=_user(context, "counter")); await session.commit()
    await approve_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Variance reviewed", idempotency_key="main-approve", current_user=_user(context, "manager", "store_manager")); await session.commit()
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.reference_type == "STOCK_COUNT_DETAIL")) == 0
    applied = await apply_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Approved physical correction", idempotency_key="main-apply", current_user=_user(context, "manager", "store_manager")); await session.commit()
    replay = await apply_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Approved physical correction", idempotency_key="main-apply", current_user=_user(context, "manager", "store_manager"))
    assert applied == replay and applied["status"] == "APPLIED"
    refreshed = await session.get(InventoryBatch, batch.id)
    ledger = await session.scalar(select(StockTransaction).where(StockTransaction.reference_type == "STOCK_COUNT_DETAIL"))
    assert (refreshed.available_quantity, refreshed.reserved_quantity, refreshed.frozen_by_count_id) == (Decimal("95.000"), Decimal("10.000"), None)
    assert (ledger.transaction_type, ledger.quantity, ledger.correlation_reference) == ("ADJUSTMENT_OUT", Decimal("-5.000"), applied["reference_key"])
    assert await session.scalar(select(func.count()).select_from(StockCountOperation).where(StockCountOperation.action == "APPLY")) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_idempotency_payload_conflict_and_scope(context):
    batch = await _batch(context, "P33-IDEMP", reserved="0")
    session = await _session(context)
    payload = CountCreate(pharmacy_location_id=context["location"], count_type="PARTIAL", selected_batch_ids=[batch.id])
    first = await create_count(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=payload, idempotency_key="shared-key", current_user=_user(context, "counter")); await session.commit()
    replay = await create_count(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=payload, idempotency_key="shared-key", current_user=_user(context, "counter"))
    assert replay == first
    with pytest.raises(P33ConflictError, match="different payload"):
        await create_count(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=CountCreate(pharmacy_location_id=context["location"], count_type="FULL"), idempotency_key="shared-key", current_user=_user(context, "counter"))


@pytest.mark.asyncio(loop_scope="module")
async def test_recount_history_separation_and_limit(context):
    batch = await _batch(context, "P33-RECOUNT", available="20", reserved="0")
    session, count_id, detail = await _started_count(context, batch, "recount")
    await record_detail(session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("18"), version=1, variance_reason="Initial shortage", evidence=None, idempotency_key="recount-record", current_user=_user(context, "counter")); await session.commit()
    await submit_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="recount-submit", current_user=_user(context, "counter")); await session.commit()
    with pytest.raises(P33ValidationError, match="differ"):
        await request_recount(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Verify shortage", assigned_to=context["counter"], idempotency_key="bad-recount", current_user=_user(context, "manager", "store_manager"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    await request_recount(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Verify shortage", assigned_to=context["recounter"], idempotency_key="recount-request-1", current_user=_user(context, "manager", "store_manager")); await session.commit()
    await start_recount(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="recount-start-1", current_user=_user(context, "recounter")); await session.commit()
    value = await session.scalar(select(CountRecountDetail).join(CountRecount).where(CountRecount.count_id == count_id))
    await record_recount_detail(session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("19"), version=1, variance_reason="One unit short", idempotency_key="recount-value-1", current_user=_user(context, "recounter")); await session.commit()
    await resubmit_recount(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="recount-resubmit-1", current_user=_user(context, "recounter")); await session.commit()
    original = await session.get(CountDetail, detail.id)
    count = await session.get(StockCount, count_id)
    assert (original.physical_quantity, original.variance_quantity, original.classifications) == (Decimal("18.000"), Decimal("-2.000"), ["OUTSIDE_TOLERANCE"])
    assert value.physical_quantity == Decimal("19.000")
    assert (count.physical_total_quantity, count.variance_quantity) == (Decimal("19.000"), Decimal("-1.000"))
    with pytest.raises(P33ConflictError, match="Maker-checker"):
        await approve_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason=None, idempotency_key="recount-self-approve", current_user=_user(context, "recounter", "store_manager"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    await request_recount(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Final verification", assigned_to=context["manager"], idempotency_key="recount-request-2", current_user=_user(context, "manager", "store_manager")); await session.commit()
    count = await session.get(StockCount, count_id)
    count.status = "RESUBMITTED"
    await session.commit()
    with pytest.raises(P33ConflictError, match="Maximum"):
        await request_recount(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Forbidden third attempt", assigned_to=context["recounter"], idempotency_key="recount-request-3", current_user=_user(context, "manager", "store_manager"))


@pytest.mark.asyncio(loop_scope="module")
async def test_reservation_invariant_snapshot_drift_cancel_and_isolation(context):
    batch = await _batch(context, "P33-GUARDS", available="10", reserved="4")
    session, count_id, detail = await _started_count(context, batch, "guards")
    await record_detail(session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("3"), version=1, variance_reason="Severe shortage", evidence=None, idempotency_key="guards-record", current_user=_user(context, "counter")); await session.commit()
    await submit_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="guards-submit", current_user=_user(context, "counter")); await session.commit()
    await approve_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason=None, idempotency_key="guards-approve", current_user=_user(context, "manager", "store_manager")); await session.commit()
    with pytest.raises(P33ConflictError, match="reserved"):
        await apply_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason=None, idempotency_key="guards-apply", current_user=_user(context, "manager", "store_manager"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    assert (await session.get(InventoryBatch, batch.id)).available_quantity == Decimal("10.000")
    with pytest.raises(P33NotFoundError):
        await start_count(session, count_id=count_id, tenant_id=context["other_tenant"], facility_id=context["facility"], idempotency_key="cross-tenant", current_user=_user(context, "counter"))

    cancel_batch = await _batch(context, "P33-CANCEL", available="5", reserved="0")
    cancel_session, cancel_id, _ = await _started_count(context, cancel_batch, "cancel")
    cancelled = await cancel_count(cancel_session, count_id=cancel_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Count interrupted", idempotency_key="cancel-action", current_user=_user(context, "counter")); await cancel_session.commit()
    assert cancelled["status"] == "CANCELLED" and (await cancel_session.get(InventoryBatch, cancel_batch.id)).frozen_by_count_id is None


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_duplicate_start_creates_one_snapshot(context):
    batch = await _batch(context, "P33-CONCURRENT", available="7", reserved="0")
    setup = await _session(context)
    created = await create_count(setup, tenant_id=context["tenant"], facility_id=context["facility"], payload=CountCreate(pharmacy_location_id=context["location"], count_type="PARTIAL", selected_batch_ids=[batch.id]), idempotency_key="concurrent-create", current_user=_user(context, "counter")); await setup.commit()
    count_id = uuid.UUID(created["id"])

    async def start_once():
        session = await _session(context)
        result = await start_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="same-start", current_user=_user(context, "counter"))
        await session.commit()
        return result

    first, second = await asyncio.gather(start_once(), start_once())
    verify = await _session(context)
    assert first == second
    assert await verify.scalar(select(func.count()).select_from(CountDetail).where(CountDetail.count_id == count_id)) == 1
    assert await verify.scalar(select(func.count()).select_from(StockCountOperation).where(StockCountOperation.count_id == count_id, StockCountOperation.action == "START")) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_unexpected_stock_is_separate_flagged_and_frozen(context):
    counted = await _batch(context, "P33-EXPECTED", available="5", reserved="0")
    unexpected = await _batch(context, "P33-UNEXPECTED", available="0", reserved="0")
    unexpected_session = await _session(context)
    await unexpected_session.execute(text("UPDATE inventory_batches SET status = 'INACTIVE' WHERE id = :id"), {"id": unexpected.id})
    await unexpected_session.commit()
    session, count_id, original = await _started_count(context, counted, "unexpected")
    result = await add_unexpected_stock(
        session, count_id=count_id, inventory_batch_id=unexpected.id,
        tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("2"),
        evidence="Two sealed packs found on upper shelf", variance_reason="Unrecorded stock",
        idempotency_key="unexpected-add", current_user=_user(context, "counter"),
    )
    await session.commit()
    assert result["is_unexpected"] is True
    assert (result["system_quantity"], result["variance_quantity"], result["classifications"]) == ("0", "2", ["UNEXPECTED_STOCK"])
    assert (await session.get(InventoryBatch, unexpected.id)).frozen_by_count_id == count_id
    assert (await session.get(CountDetail, original.id)).is_unexpected is False


@pytest.mark.asyncio(loop_scope="module")
async def test_apply_failure_rolls_back_all_lines_status_and_freeze(context):
    first = await _batch(context, "P33-ROLLBACK-A", available="10", reserved="0")
    second = await _batch(context, "P33-ROLLBACK-Z", available="10", reserved="4")
    session = await _session(context)
    created = await create_count(session, tenant_id=context["tenant"], facility_id=context["facility"], payload=CountCreate(
        pharmacy_location_id=context["location"], count_type="PARTIAL", selected_batch_ids=[first.id, second.id],
    ), idempotency_key="rollback-create", current_user=_user(context, "counter"))
    await session.commit()
    count_id = uuid.UUID(created["id"])
    await start_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="rollback-start", current_user=_user(context, "counter")); await session.commit()
    details = list((await session.execute(select(CountDetail).where(CountDetail.count_id == count_id).order_by(CountDetail.batch_number))).scalars().all())
    detail_ids = [detail.id for detail in details]
    await record_detail(session, count_id=count_id, detail_id=details[0].id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("11"), version=1, variance_reason="One extra", evidence=None, idempotency_key="rollback-record-a", current_user=_user(context, "counter"))
    await record_detail(session, count_id=count_id, detail_id=details[1].id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("3"), version=1, variance_reason="Below reservations", evidence=None, idempotency_key="rollback-record-z", current_user=_user(context, "counter")); await session.commit()
    await submit_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="rollback-submit", current_user=_user(context, "counter")); await session.commit()
    await approve_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Review complete", idempotency_key="rollback-approve", current_user=_user(context, "manager", "store_manager")); await session.commit()
    with pytest.raises(P33ConflictError, match="reserved"):
        await apply_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Must rollback", idempotency_key="rollback-apply", current_user=_user(context, "manager", "store_manager"))
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    refreshed = [await session.get(InventoryBatch, first.id), await session.get(InventoryBatch, second.id)]
    assert [(item.available_quantity, item.frozen_by_count_id) for item in refreshed] == [(Decimal("10.000"), count_id), (Decimal("10.000"), count_id)]
    assert (await session.get(StockCount, count_id)).status == "APPROVED"
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.reference_id.in_(detail_ids))) == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_full_and_sample_require_complete_scope_and_reject_illegal_transitions(context):
    for count_type in ("FULL", "SAMPLE"):
        location_id = uuid.uuid4()
        setup = await _session(context)
        setup.add(PharmacyLocation(
            id=location_id, tenant_id=context["tenant"], facility_id=context["facility"],
            location_code=f"P33-{count_type}", location_name=f"P33 {count_type} Store",
            location_type="PHARMACY", active=True,
        ))
        await setup.commit()
        batches = [
            await _batch(context, f"P33-{count_type}-{index}", available="10", reserved="0", location_id=location_id)
            for index in range(2)
        ]
        session = await _session(context)
        payload = CountCreate(
            pharmacy_location_id=location_id, count_type=count_type,
            selected_batch_ids=[] if count_type == "FULL" else [batch.id for batch in batches],
        )
        created = await create_count(
            session, tenant_id=context["tenant"], facility_id=context["facility"], payload=payload,
            idempotency_key=f"{count_type}-create", current_user=_user(context, "counter"),
        )
        await session.commit()
        count_id = uuid.UUID(created["id"])
        await start_count(
            session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"],
            idempotency_key=f"{count_type}-start", current_user=_user(context, "counter"),
        )
        await session.commit()
        with pytest.raises(P33ConflictError, match="Only CREATED"):
            await start_count(
                session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"],
                idempotency_key=f"{count_type}-illegal-start", current_user=_user(context, "counter"),
            )
        await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
        details = list((await session.execute(select(CountDetail).where(CountDetail.count_id == count_id).order_by(CountDetail.id))).scalars().all())
        assert len(details) == 2
        await record_detail(
            session, count_id=count_id, detail_id=details[0].id, tenant_id=context["tenant"], facility_id=context["facility"],
            physical_quantity=Decimal("10"), version=1, variance_reason=None, evidence=None,
            idempotency_key=f"{count_type}-record-1", current_user=_user(context, "counter"),
        )
        await session.commit()
        with pytest.raises(P33ValidationError, match="Every count detail"):
            await submit_count(
                session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"],
                idempotency_key=f"{count_type}-incomplete", current_user=_user(context, "counter"),
            )
        await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
        details = list((await session.execute(select(CountDetail).where(CountDetail.count_id == count_id).order_by(CountDetail.id))).scalars().all())
        await record_detail(
            session, count_id=count_id, detail_id=details[1].id, tenant_id=context["tenant"], facility_id=context["facility"],
            physical_quantity=Decimal("10"), version=1, variance_reason=None, evidence=None,
            idempotency_key=f"{count_type}-record-2", current_user=_user(context, "counter"),
        )
        await session.commit()
        submitted = await submit_count(
            session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"],
            idempotency_key=f"{count_type}-submit", current_user=_user(context, "counter"),
        )
        await session.commit()
        assert submitted["status"] == "SUBMITTED"


@pytest.mark.asyncio(loop_scope="module")
async def test_variance_classification_boundaries_and_ledger_directions(context):
    location_id = uuid.uuid4()
    setup = await _session(context)
    setup.add(PharmacyLocation(
        id=location_id, tenant_id=context["tenant"], facility_id=context["facility"],
        location_code="P33-CLASS", location_name="P33 Classification Store", location_type="PHARMACY", active=True,
    ))
    await setup.commit()
    cases = [
        ("ZERO", "20", Decimal("100"), ["ZERO"]),
        ("POSITIVE", "20", Decimal("102"), ["OUTSIDE_TOLERANCE"]),
        ("TOLERATED", "20", Decimal("100.5"), ["WITHIN_TOLERANCE"]),
        ("HIGH", "5000", Decimal("101"), ["OUTSIDE_TOLERANCE", "HIGH_VALUE"]),
        ("REPEATED", "20", Decimal("99"), ["OUTSIDE_TOLERANCE", "REPEATED"]),
    ]
    batches = [await _batch(context, f"P33-{name}", available="100", reserved="0", cost=cost, location_id=location_id) for name, cost, _, _ in cases]
    for attempt in range(2):
        prior = StockCount(
            tenant_id=context["tenant"], facility_id=context["facility"], pharmacy_location_id=location_id,
            status="APPLIED", count_type="PARTIAL", reference_key=f"P33-PRIOR-{attempt}",
            selected_batch_ids=[str(batches[-1].id)], initiated_by=context["counter"],
            applied_by=context["manager"], applied_at=datetime.now(timezone.utc),
        )
        setup.add(prior); await setup.flush()
        setup.add(CountDetail(
            count_id=prior.id, inventory_batch_id=batches[-1].id, medicine_id=batches[-1].medicine_id,
            batch_number=batches[-1].batch_number, system_quantity=Decimal("100"), available_quantity=Decimal("100"),
            reserved_quantity=Decimal("0"), unit_cost=Decimal("20"), physical_quantity=Decimal("99"),
            variance_quantity=Decimal("-1"), classifications=["OUTSIDE_TOLERANCE"], counted_by=context["counter"],
        ))
    await setup.commit()
    session = await _session(context)
    created = await create_count(
        session, tenant_id=context["tenant"], facility_id=context["facility"],
        payload=CountCreate(pharmacy_location_id=location_id, count_type="PARTIAL", selected_batch_ids=[batch.id for batch in batches]),
        idempotency_key="class-create", current_user=_user(context, "counter"),
    )
    await session.commit(); count_id = uuid.UUID(created["id"])
    await start_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="class-start", current_user=_user(context, "counter")); await session.commit()
    details = list((await session.execute(select(CountDetail).where(CountDetail.count_id == count_id))).scalars().all())
    by_batch = {detail.batch_number: detail for detail in details}
    for name, _, physical, expected_flags in cases:
        result = await record_detail(
            session, count_id=count_id, detail_id=by_batch[f"P33-{name}"].id,
            tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=physical,
            version=1, variance_reason="Classification evidence", evidence=None,
            idempotency_key=f"class-{name}", current_user=_user(context, "counter"),
        )
        assert result["classifications"] == expected_flags
    await session.commit()
    await submit_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="class-submit", current_user=_user(context, "counter")); await session.commit()
    await approve_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Boundaries reviewed", idempotency_key="class-approve", current_user=_user(context, "manager", "store_manager")); await session.commit()
    await apply_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Apply classification matrix", idempotency_key="class-apply", current_user=_user(context, "manager", "store_manager")); await session.commit()
    ledger = list((await session.execute(select(StockTransaction).where(StockTransaction.reference_id.in_([detail.id for detail in details])))).scalars().all())
    assert sorted((row.transaction_type, row.quantity) for row in ledger) == [
        ("ADJUSTMENT_IN", Decimal("0.500")), ("ADJUSTMENT_IN", Decimal("1.000")),
        ("ADJUSTMENT_IN", Decimal("2.000")), ("ADJUSTMENT_OUT", Decimal("-1.000")),
    ]


@pytest.mark.asyncio(loop_scope="module")
async def test_cross_facility_isolation_and_snapshot_drift_audit_persistence(context):
    batch = await _batch(context, "P33-DRIFT", available="8", reserved="0")
    session, count_id, detail = await _started_count(context, batch, "drift")
    with pytest.raises(P33NotFoundError):
        await record_detail(
            session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["other_facility"],
            physical_quantity=Decimal("8"), version=1, variance_reason=None, evidence=None,
            idempotency_key="cross-facility", current_user=_user(context, "counter"),
        )
    await session.rollback(); await session.execute(text(f'SET search_path TO "{context["schema"]}", public'))
    detail = await session.scalar(select(CountDetail).where(CountDetail.count_id == count_id))
    await record_detail(session, count_id=count_id, detail_id=detail.id, tenant_id=context["tenant"], facility_id=context["facility"], physical_quantity=Decimal("8"), version=1, variance_reason=None, evidence=None, idempotency_key="drift-record", current_user=_user(context, "counter")); await session.commit()
    await submit_count(session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], idempotency_key="drift-submit", current_user=_user(context, "counter")); await session.commit()
    await session.execute(text("UPDATE inventory_batches SET available_quantity = available_quantity + 1 WHERE id = :id"), {"id": batch.id}); await session.commit()
    with pytest.raises(HTTPException) as conflict:
        await _commit(session, approve_count(
            session, count_id=count_id, tenant_id=context["tenant"], facility_id=context["facility"], reason="Detect drift",
            idempotency_key="drift-approve", current_user=_user(context, "manager", "store_manager"),
        ))
    assert conflict.value.status_code == 409
    audit = await session.scalar(select(AuditLog).where(AuditLog.resource_id == str(count_id), AuditLog.action == "SNAPSHOT_DRIFT"))
    assert audit is not None and audit.new_value["during"] == "APPROVE"
    assert (await session.get(StockCount, count_id)).status == "SUBMITTED"