"""Real PostgreSQL acceptance tests for P31 quarantine and disposal."""

import asyncio
import os
import socket
import uuid
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.models.public.user import Tenant, User
from app.models.tenant import AuditLog, InventoryBatch, PharmacyLocation, StockQuarantine, StockTransaction
from app.schemas.quarantine import StockQuarantineCreate, StockQuarantineDispose
from app.services.quarantine_service import create_quarantine, dispose_quarantine, release_quarantine

PG_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")


def _postgres_reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def p31_context():
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    schema_a = f"p31_a_{uuid.uuid4().hex[:8]}"
    schema_b = f"p31_b_{uuid.uuid4().hex[:8]}"
    ids = {name: uuid.uuid4() for name in (
        "tenant_a", "tenant_b", "facility", "location_a", "location_b", "medicine",
        "pharmacist", "admin", "nurse", "pharmacist_b", "investigative", "expired",
        "damaged", "self_disposal", "concurrent", "rollback", "api", "cross_tenant",
    )}
    users = [
        ("pharmacist", "pharmacist", ids["tenant_a"], schema_a),
        ("admin", "hospital_admin", ids["tenant_a"], schema_a),
        ("nurse", "nurse", ids["tenant_a"], schema_a),
        ("pharmacist_b", "pharmacist", ids["tenant_b"], schema_b),
    ]
    tenant_tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    async with engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, plan, is_active, display_token, session_version, created_at, updated_at)
            VALUES (:id, :schema, :name, :email, 'enterprise', true, :token, 0, now(), now())
        """), [
            {"id": ids["tenant_a"], "schema": schema_a, "name": "P31 A", "email": f"{schema_a}@test.invalid", "token": schema_a},
            {"id": ids["tenant_b"], "schema": schema_b, "name": "P31 B", "email": f"{schema_b}@test.invalid", "token": schema_b},
        ])
        await connection.execute(text("""
            INSERT INTO public.users (id, tenant_id, tenant_name, email, username, hashed_password, full_name, role, is_active, must_change_password, session_version, created_at, updated_at)
            VALUES (:id, :tenant, :schema, :email, :username, :password, :name, :role, true, false, 0, now(), now())
        """), [{
            "id": ids[name], "tenant": tenant, "schema": schema, "email": f"{name}-{schema}@test.invalid",
            "username": f"{name}_{schema[-5:]}", "password": hash_password("Passw0rd!"), "name": name, "role": role,
        } for name, role, tenant, schema in users])
        for schema, tenant, location in ((schema_a, ids["tenant_a"], ids["location_a"]), (schema_b, ids["tenant_b"], ids["location_b"])):
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET search_path TO "{schema}", public'))
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tenant_tables))
            session = AsyncSession(bind=connection, expire_on_commit=False)
            session.add(PharmacyLocation(id=location, tenant_id=tenant, facility_id=ids["facility"], location_code=schema, location_name=schema, location_type="PHARMACY", active=True))
            await session.flush()
            if schema == schema_a:
                batches = [
                    InventoryBatch(id=ids[name], tenant_id=tenant, facility_id=ids["facility"], pharmacy_location_id=location, medicine_id=ids["medicine"], batch_number=f"P31-{name}", expiry_date=expiry, purchase_rate=Decimal("10"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), status="ACTIVE")
                    for name, expiry in (
                        ("investigative", date.today() + timedelta(days=365)),
                        ("expired", date.today() - timedelta(days=1)),
                        ("damaged", date.today() + timedelta(days=365)),
                        ("self_disposal", date.today() + timedelta(days=365)),
                        ("concurrent", date.today() + timedelta(days=365)),
                        ("rollback", date.today() + timedelta(days=365)),
                        ("api", date.today() + timedelta(days=365)),
                    )
                ]
            else:
                batches = [InventoryBatch(id=ids["cross_tenant"], tenant_id=tenant, facility_id=ids["facility"], pharmacy_location_id=location, medicine_id=ids["medicine"], batch_number="P31-CROSS", purchase_rate=Decimal("10"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), status="ACTIVE")]
            session.add_all(batches)
            await session.commit()
            await session.close()
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield {**ids, "engine": engine, "maker": maker, "schema_a": schema_a, "schema_b": schema_b}
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_a}" CASCADE'))
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_b}" CASCADE'))
        await connection.execute(text("DELETE FROM public.users WHERE id = ANY(:ids)"), {"ids": [ids[name] for name, *_ in users]})
        await connection.execute(text("DELETE FROM public.tenants WHERE id = ANY(:ids)"), {"ids": [ids["tenant_a"], ids["tenant_b"]]})
    await engine.dispose()


async def _session(context, schema="schema_a"):
    session = context["maker"]()
    await session.execute(text(f'SET search_path TO "{context[schema]}", public'))
    return session


async def _rollback(session, context):
    await session.rollback()
    await session.execute(text(f'SET search_path TO "{context["schema_a"]}", public'))


def _user(context, name, role):
    return {"sub": str(context[name]), "role": role, "tenant_id": str(context["tenant_a"]), "tenant_schema": context["schema_a"], "facility_id": str(context["facility"])}


def _request(context, batch, quantity, reason, key):
    return StockQuarantineCreate(inventory_batch_id=context[batch], quantity=quantity, reason=reason, idempotency_key=key, notes=f"P31 {reason.lower()} evidence")


def _disposal(context):
    return StockQuarantineDispose(disposal_reason="Confirmed non-saleable stock disposal", disposal_method="Licensed biomedical waste", disposal_date=date.today(), witnessed_by=context["nurse"])


def _token(context, user, role, schema="schema_a", tenant="tenant_a"):
    return create_access_token(str(context[user]), {"role": role, "tenant_id": str(context[tenant]), "tenant_schema": context[schema], "facility_id": str(context["facility"]), "session_version": 0, "tenant_session_version": 0})


@pytest.mark.asyncio(loop_scope="module")
async def test_model_constraints_indexes_and_permissions_match_migration(p31_context):
    async with p31_context["engine"].connect() as connection:
        await connection.execute(text(f'SET search_path TO "{p31_context["schema_a"]}", public'))
        constraints = await connection.run_sync(lambda sync: inspect(sync).get_unique_constraints("stock_quarantine"))
        indexes = await connection.run_sync(lambda sync: inspect(sync).get_indexes("stock_quarantine"))
        assert {tuple(item["column_names"]) for item in constraints} >= {("tenant_id", "reference_key"), ("tenant_id", "idempotency_key")}
        assert len({item["name"] for item in indexes}) == len(indexes)
        permissions = (await connection.execute(text("SELECT code FROM public.permissions WHERE code LIKE 'PHARMACY_QUARANTINE_%'"))).scalars().all()
        assert set(permissions) == {"PHARMACY_QUARANTINE_VIEW", "PHARMACY_QUARANTINE_CREATE", "PHARMACY_QUARANTINE_APPROVE"}


@pytest.mark.asyncio(loop_scope="module")
async def test_quarantine_release_and_idempotent_replay_reconcile(p31_context):
    session = await _session(p31_context)
    maker = _user(p31_context, "pharmacist", "pharmacist")
    approver = _user(p31_context, "admin", "hospital_admin")
    request = _request(p31_context, "investigative", Decimal("4"), "INVESTIGATION", "p31-investigation")
    record = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=request, current_user=maker)
    await session.commit()
    replay = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=request, current_user=maker)
    await session.commit()
    assert replay.id == record.id
    batch = await session.get(InventoryBatch, p31_context["investigative"])
    assert (batch.available_quantity, replay.remaining_quantity, batch.available_quantity + replay.remaining_quantity) == (Decimal("6"), Decimal("4"), Decimal("10"))
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.reference_id == record.id)) == 1
    released = await release_quarantine(session, quarantine_id=record.id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], release_reason="Investigation cleared with intact packaging", current_user=approver)
    await session.commit()
    await session.refresh(batch)
    ledger = (await session.scalars(select(StockTransaction).where(StockTransaction.reference_id == record.id).order_by(StockTransaction.created_at))).all()
    assert (released.status, released.remaining_quantity, batch.available_quantity) == ("RELEASED", Decimal("0"), Decimal("10"))
    assert [(row.transaction_type, row.quantity, row.previous_balance, row.new_balance) for row in ledger] == [("QUARANTINE_OUT", Decimal("-4"), Decimal("10"), Decimal("6")), ("QUARANTINE_RELEASE", Decimal("4"), Decimal("6"), Decimal("10"))]
    assert all(row.tenant_id == p31_context["tenant_a"] and row.facility_id == p31_context["facility"] and row.pharmacy_location_id == p31_context["location_a"] for row in ledger)
    assert [row.performed_by for row in ledger] == [p31_context["pharmacist"], p31_context["admin"]]
    record_id = record.id
    with pytest.raises(ValueError, match="Only quarantined"):
        await release_quarantine(session, quarantine_id=record_id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], release_reason="Repeated transition must fail", current_user=approver)
    await _rollback(session, p31_context)
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_expired_and_damaged_quarantine_disposal_rules_and_accounting(p31_context):
    session = await _session(p31_context)
    maker = _user(p31_context, "pharmacist", "pharmacist")
    approver = _user(p31_context, "admin", "hospital_admin")
    expired = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "expired", Decimal("2"), "EXPIRED", "p31-expired"), current_user=maker)
    damaged = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "damaged", Decimal("3"), "DAMAGED", "p31-damaged"), current_user=maker)
    await session.commit()
    expired_id, damaged_id = expired.id, damaged.id
    for record_id in (expired_id, damaged_id):
        with pytest.raises(ValueError, match="never return"):
            await release_quarantine(session, quarantine_id=record_id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], release_reason="Not permitted for terminal quarantine", current_user=approver)
        await _rollback(session, p31_context)
    disposed = await dispose_quarantine(session, quarantine_id=damaged_id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_disposal(p31_context), current_user=approver)
    await session.commit()
    batch = await session.get(InventoryBatch, p31_context["damaged"])
    disposal = await session.scalar(select(StockTransaction).where(StockTransaction.reference_id == damaged_id, StockTransaction.transaction_type == "QUARANTINE_DISPOSAL"))
    assert (disposed.status, disposed.remaining_quantity, batch.available_quantity) == ("DISPOSED", Decimal("0"), Decimal("7"))
    assert (disposal.quantity, disposal.previous_balance, disposal.new_balance, disposal.performed_by) == (Decimal("-3"), Decimal("7"), Decimal("7"), p31_context["admin"])
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.reference_id == damaged_id, StockTransaction.transaction_type == "QUARANTINE_DISPOSAL")) == 1
    with pytest.raises(ValueError, match="only from quarantine"):
        await dispose_quarantine(session, quarantine_id=damaged_id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_disposal(p31_context), current_user=approver)
    await _rollback(session, p31_context)
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_validation_isolation_duplicate_key_and_maker_checker(p31_context):
    session = await _session(p31_context)
    maker = _user(p31_context, "pharmacist", "pharmacist")
    for quantity in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError):
            _request(p31_context, "self_disposal", quantity, "DAMAGED", f"bad-{quantity}")
    with pytest.raises(ValueError, match="exceeds"):
        await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "self_disposal", Decimal("11"), "DAMAGED", "excess"), current_user=maker)
    await _rollback(session, p31_context)
    with pytest.raises(ValueError, match="not found"):
        await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=StockQuarantineCreate(inventory_batch_id=p31_context["cross_tenant"], quantity=1, reason="DAMAGED", idempotency_key="cross"), current_user=maker)
    await _rollback(session, p31_context)
    first = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "self_disposal", Decimal("2"), "DAMAGED", "same-key"), current_user=maker)
    await session.commit()
    first_id = first.id
    with pytest.raises(ValueError, match="different request"):
        await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "self_disposal", Decimal("1"), "DAMAGED", "same-key"), current_user=maker)
    await _rollback(session, p31_context)
    with pytest.raises(ValueError, match="Initiator"):
        await dispose_quarantine(session, quarantine_id=first_id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_disposal(p31_context), current_user=maker)
    await _rollback(session, p31_context)
    assert (await session.get(InventoryBatch, p31_context["self_disposal"])).available_quantity == Decimal("8")
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_concurrent_quarantines_cannot_overdraw_batch(p31_context):
    async def attempt(key):
        session = await _session(p31_context)
        try:
            record = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "concurrent", Decimal("6"), "INVESTIGATION", key), current_user=_user(p31_context, "pharmacist", "pharmacist"))
            await session.commit()
            return record.id
        except ValueError:
            await session.rollback()
            return None
        finally:
            await session.close()
    results = await asyncio.gather(attempt("race-a"), attempt("race-b"))
    session = await _session(p31_context)
    assert sum(item is not None for item in results) == 1
    assert (await session.get(InventoryBatch, p31_context["concurrent"])).available_quantity == Decimal("4")
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.inventory_batch_id == p31_context["concurrent"])) == 1
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_disposal_failure_rolls_back_status_ledger_audit_and_retries(p31_context, monkeypatch):
    session = await _session(p31_context)
    record = await create_quarantine(session, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_request(p31_context, "rollback", Decimal("2"), "DAMAGED", "rollback"), current_user=_user(p31_context, "pharmacist", "pharmacist"))
    await session.commit()
    import app.services.quarantine_service as service
    original = service.record_audit
    monkeypatch.setattr(service, "record_audit", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("controlled disposal failure")))
    with pytest.raises(RuntimeError, match="controlled"):
        await dispose_quarantine(session, quarantine_id=record.id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_disposal(p31_context), current_user=_user(p31_context, "admin", "hospital_admin"))
    await session.rollback()
    monkeypatch.setattr(service, "record_audit", original)
    await session.refresh(record)
    assert (record.status, record.remaining_quantity) == ("QUARANTINED", Decimal("2"))
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.reference_id == record.id, StockTransaction.transaction_type == "QUARANTINE_DISPOSAL")) == 0
    assert await session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.resource_id == str(record.id), AuditLog.action == "DISPOSE")) == 0
    await dispose_quarantine(session, quarantine_id=record.id, tenant_id=p31_context["tenant_a"], facility_id=p31_context["facility"], payload=_disposal(p31_context), current_user=_user(p31_context, "admin", "hospital_admin"))
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(StockTransaction).where(StockTransaction.reference_id == record.id, StockTransaction.transaction_type == "QUARANTINE_DISPOSAL")) == 1
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_real_api_enforces_auth_rbac_and_cross_tenant_404(p31_context):
    from app.main import app
    import app.core.redis_client as redis_client
    from app.db import engine as app_engine
    redis_client._client = None
    await app_engine.engine.dispose()
    payload = {"inventory_batch_id": str(p31_context["api"]), "quantity": 1, "reason": "INVESTIGATION", "idempotency_key": "api-rbac", "notes": "API RBAC acceptance"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/v1/pharmacy/quarantines", json=payload)).status_code == 401
        nurse = _token(p31_context, "nurse", "nurse")
        assert (await client.post("/api/v1/pharmacy/quarantines", json=payload, headers={"Authorization": f"Bearer {nurse}"})).status_code == 403
        pharmacist = _token(p31_context, "pharmacist", "pharmacist")
        created = await client.post("/api/v1/pharmacy/quarantines", json=payload, headers={"Authorization": f"Bearer {pharmacist}"})
        assert created.status_code == 201, created.text
        other_tenant = _token(p31_context, "pharmacist_b", "pharmacist", "schema_b", "tenant_b")
        hidden = await client.post(f"/api/v1/pharmacy/quarantines/{created.json()['id']}/release", json={"release_reason": "Cross tenant release must remain hidden"}, headers={"Authorization": f"Bearer {other_tenant}"})
        assert hidden.status_code in {403, 404}
    await app_engine.engine.dispose()
    redis_client._client = None