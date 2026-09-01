"""
Lab Release A (RA-3) regression tests — controlled Lab Test Master ordering,
Doctor visit_id scoping, Lab Technician worklist visibility, and the
missing-price billing data-contract guard.

Real PostgreSQL, full ASGI stack for the API-level checks; direct service
calls for the billing pricing-contract unit check.

Run:
    docker compose -f infra/docker-compose.yml up -d postgres redis
    cd backend
    $env:DATABASE_URL="postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital"
    $env:SECRET_KEY="test-secret-key"
    python -m pytest tests/test_lab_release_a.py -v
"""
import os
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.models.tenant import Department, Doctor, Patient, Visit
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.lab_test_master import LabTestMaster
from app.services.lab_billing_service import LabPricingError, create_lab_invoice_if_needed

PG_URL = os.environ["DATABASE_URL"]
SCHEMA = f"test_lab_ra3_{uuid.uuid4().hex[:10]}"


def _postgres_reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable")


def _get_app():
    from app.main import app
    return app


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ctx():
    import app.core.redis_client as redis_client_module
    redis_client_module._client = None
    from app.db.engine import engine as app_engine
    await app_engine.dispose()

    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    doctor_a_user_id = uuid.uuid4()
    doctor_b_user_id = uuid.uuid4()
    lab_tech_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await conn.execute(text("""
            INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, plan, is_active, display_token, created_at, updated_at)
            VALUES (:id, :schema, 'Lab RA3', :email, 'enterprise', true, :token, now(), now())
        """), {"id": tenant_id, "schema": SCHEMA, "email": f"{SCHEMA}@test.invalid", "token": SCHEMA})
        await conn.execute(text("""
            INSERT INTO public.users (id, tenant_id, tenant_name, email, username, hashed_password, full_name, role, is_active, must_change_password, created_at, updated_at)
            VALUES (:id, :tenant_id, :tenant_name, :email, :username, :password, :name, :role, true, false, now(), now())
        """), [
            {"id": admin_id, "tenant_id": tenant_id, "tenant_name": SCHEMA, "email": f"admin-{SCHEMA}@test.invalid", "username": f"admin{SCHEMA[-6:]}", "password": hash_password("Passw0rd!"), "name": "Admin", "role": "hospital_admin"},
            {"id": doctor_a_user_id, "tenant_id": tenant_id, "tenant_name": SCHEMA, "email": f"doca-{SCHEMA}@test.invalid", "username": f"doca{SCHEMA[-6:]}", "password": hash_password("Passw0rd!"), "name": "Doctor A", "role": "doctor"},
            {"id": doctor_b_user_id, "tenant_id": tenant_id, "tenant_name": SCHEMA, "email": f"docb-{SCHEMA}@test.invalid", "username": f"docb{SCHEMA[-6:]}", "password": hash_password("Passw0rd!"), "name": "Doctor B", "role": "doctor"},
            {"id": lab_tech_id, "tenant_id": tenant_id, "tenant_name": SCHEMA, "email": f"lab-{SCHEMA}@test.invalid", "username": f"lab{SCHEMA[-6:]}", "password": hash_password("Passw0rd!"), "name": "Lab Tech", "role": "lab_technician"},
        ])
        await conn.execute(text("""
            INSERT INTO public.tenant_features (id, tenant_id, feature, enabled, created_at, updated_at)
            VALUES (:id, :tenant_id, 'lab', true, now(), now())
        """), {"id": uuid.uuid4(), "tenant_id": tenant_id})

    tenant_tables = [t for t in Base.metadata.sorted_tables if t.schema is None]
    department_id = uuid.uuid4()
    doctor_a_id = uuid.uuid4()
    doctor_b_id = uuid.uuid4()
    patient_a_id = uuid.uuid4()
    patient_b_id = uuid.uuid4()
    visit_a_id = uuid.uuid4()
    visit_b_id = uuid.uuid4()
    active_test_id = uuid.uuid4()
    inactive_test_id = uuid.uuid4()
    no_price_test_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tenant_tables, checkfirst=False))

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    session = maker()
    await session.execute(text(f'SET search_path TO "{SCHEMA}", public'))
    session.add_all([
        Department(id=department_id, name="General"),
        Doctor(id=doctor_a_id, user_id=doctor_a_user_id, full_name="Doctor A", specialization="General", department_id=department_id, is_active=True),
        Doctor(id=doctor_b_id, user_id=doctor_b_user_id, full_name="Doctor B", specialization="General", department_id=department_id, is_active=True),
        Patient(id=patient_a_id, uhid="LABRA3-A", first_name="Alpha", last_name="Patient", gender="male", phone="9000000001"),
        Patient(id=patient_b_id, uhid="LABRA3-B", first_name="Beta", last_name="Patient", gender="female", phone="9000000002"),
        LabTestMaster(id=active_test_id, code="CBC-RA3", name="Complete Blood Count", category="Hematology", sample_type="Blood", price=250.0, unit="cells/uL", reference_range="4.5-11.0", is_active=True),
        LabTestMaster(id=inactive_test_id, code="OLD-RA3", name="Deprecated Test", price=100.0, is_active=False),
        LabTestMaster(id=no_price_test_id, code="ZERO-RA3", name="Zero Price Test", price=0.0, is_active=True),
    ])
    await session.flush()
    session.add_all([
        Visit(id=visit_a_id, patient_id=patient_a_id, uhid="LABRA3-A", doctor_id=doctor_a_id, department_id=department_id, status="CONSULTATION_COMPLETED"),
        Visit(id=visit_b_id, patient_id=patient_b_id, uhid="LABRA3-B", doctor_id=doctor_b_id, department_id=department_id, status="CONSULTATION_COMPLETED"),
    ])
    await session.commit()
    await session.close()

    transport = ASGITransport(app=_get_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client, "tenant_id": tenant_id, "admin_id": admin_id,
            "doctor_a_user_id": doctor_a_user_id, "doctor_b_user_id": doctor_b_user_id, "lab_tech_id": lab_tech_id,
            "visit_a_id": visit_a_id, "visit_b_id": visit_b_id,
            "active_test_id": active_test_id, "inactive_test_id": inactive_test_id, "no_price_test_id": no_price_test_id,
            "maker": maker,
        }

    cleanup_engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with cleanup_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text("DELETE FROM public.tenant_features WHERE tenant_id = :id"), {"id": tenant_id})
        await conn.execute(text("DELETE FROM public.users WHERE id = ANY(:ids)"), {"ids": [admin_id, doctor_a_user_id, doctor_b_user_id, lab_tech_id]})
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
    await cleanup_engine.dispose()
    await engine.dispose()


def _token(ctx, user_key: str, role: str) -> str:
    return create_access_token(str(ctx[user_key]), {"role": role, "tenant_id": str(ctx["tenant_id"]), "tenant_schema": SCHEMA})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio(loop_scope="module")
async def test_doctor_orders_active_controlled_test_and_server_snapshots_it(ctx):
    token = _token(ctx, "doctor_a_user_id", "doctor")
    resp = await ctx["client"].post("/api/v1/prescriptions", json={
        "visit_id": str(ctx["visit_a_id"]),
        "lab_tests": [{"test_id": str(ctx["active_test_id"]), "notes": "fasting required"}],
    }, headers=_auth(token))
    assert resp.status_code in (200, 201), resp.text

    get_resp = await ctx["client"].get(f"/api/v1/prescriptions/{ctx['visit_a_id']}", headers=_auth(token))
    assert get_resp.status_code == 200, get_resp.text
    test = get_resp.json()["lab_tests"][0]
    assert test["test_code"] == "CBC-RA3"
    assert test["test_name"] == "Complete Blood Count"
    assert test["price"] == 250.0
    assert test["notes"] == "fasting required"


@pytest.mark.asyncio(loop_scope="module")
async def test_client_supplied_price_is_ignored_not_authoritative(ctx):
    token = _token(ctx, "doctor_a_user_id", "doctor")
    resp = await ctx["client"].post("/api/v1/prescriptions", json={
        "visit_id": str(ctx["visit_a_id"]),
        "lab_tests": [{"test_id": str(ctx["active_test_id"]), "notes": "n", "price": 999999}],
    }, headers=_auth(token))
    assert resp.status_code in (200, 201), resp.text

    get_resp = await ctx["client"].get(f"/api/v1/prescriptions/{ctx['visit_a_id']}", headers=_auth(token))
    assert get_resp.json()["lab_tests"][0]["price"] == 250.0


@pytest.mark.asyncio(loop_scope="module")
async def test_inactive_test_is_rejected(ctx):
    token = _token(ctx, "doctor_a_user_id", "doctor")
    resp = await ctx["client"].post("/api/v1/prescriptions", json={
        "visit_id": str(ctx["visit_a_id"]),
        "lab_tests": [{"test_id": str(ctx["inactive_test_id"])}],
    }, headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio(loop_scope="module")
async def test_duplicate_test_in_one_order_is_rejected(ctx):
    token = _token(ctx, "doctor_a_user_id", "doctor")
    resp = await ctx["client"].post("/api/v1/prescriptions", json={
        "visit_id": str(ctx["visit_a_id"]),
        "lab_tests": [
            {"test_id": str(ctx["active_test_id"])},
            {"test_id": str(ctx["active_test_id"])},
        ],
    }, headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio(loop_scope="module")
async def test_free_text_lab_test_is_no_longer_accepted(ctx):
    token = _token(ctx, "doctor_a_user_id", "doctor")
    resp = await ctx["client"].post("/api/v1/prescriptions", json={
        "visit_id": str(ctx["visit_a_id"]),
        "lab_tests": [{"test_name": "CBC (free text)"}],
    }, headers=_auth(token))
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="module")
async def test_doctor_is_restricted_to_their_own_visit_lab_orders(ctx):
    # Doctor A's own order (created above) exists on visit_a; Doctor B has no order yet.
    token_a = _token(ctx, "doctor_a_user_id", "doctor")
    resp = await ctx["client"].get("/api/v1/lab", params={"visit_id": str(ctx["visit_a_id"])}, headers=_auth(token_a))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) >= 1

    # Doctor B must not see Doctor A's visit orders, even when explicitly
    # passing visit_id — the doctor scope is enforced server-side, not by
    # trusting the query parameter alone.
    token_b = _token(ctx, "doctor_b_user_id", "doctor")
    resp2 = await ctx["client"].get("/api/v1/lab", params={"visit_id": str(ctx["visit_a_id"])}, headers=_auth(token_b))
    assert resp2.status_code == 200, resp2.text
    assert resp2.json() == []


@pytest.mark.asyncio(loop_scope="module")
async def test_lab_technician_sees_result_ready_orders_in_default_worklist(ctx):
    maker = ctx["maker"]
    session = maker()
    await session.execute(text(f'SET search_path TO "{SCHEMA}", public'))
    order = LabOrder(id=uuid.uuid4(), visit_id=ctx["visit_a_id"], uhid="LABRA3-A", tests=[{"test_code": "CBC-RA3", "price": 250.0}], status="result_ready", result_ready_at=datetime.now(timezone.utc))
    completed_order = LabOrder(id=uuid.uuid4(), visit_id=ctx["visit_a_id"], uhid="LABRA3-A", tests=[{"test_code": "CBC-RA3", "price": 250.0}], status="completed", completed_at=datetime.now(timezone.utc))
    session.add_all([order, completed_order])
    await session.commit()
    order_id, completed_id = order.id, completed_order.id
    await session.close()

    token = _token(ctx, "lab_tech_id", "lab_technician")
    resp = await ctx["client"].get("/api/v1/lab", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()}
    assert str(order_id) in ids, "result_ready order must remain visible to the verifier"
    assert str(completed_id) not in ids, "completed orders are excluded from the default worklist"


@pytest.mark.asyncio(loop_scope="module")
async def test_missing_snapshotted_price_is_a_data_contract_error_not_silently_zero(ctx):
    maker = ctx["maker"]
    session = maker()
    await session.execute(text(f'SET search_path TO "{SCHEMA}", public'))
    with pytest.raises(LabPricingError):
        await create_lab_invoice_if_needed(
            session,
            lab_order_id=uuid.uuid4(),
            visit_id=ctx["visit_a_id"],
            tests=[{"test_code": "LEGACY", "test": "Legacy free-text order, no price ever snapshotted"}],
            patient_id=None,
            current_user={"sub": str(uuid.uuid4()), "role": "lab_technician", "tenant_schema": SCHEMA},
        )
    await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_explicit_zero_price_from_master_is_a_valid_zero_charge(ctx):
    maker = ctx["maker"]
    session = maker()
    await session.execute(text(f'SET search_path TO "{SCHEMA}", public'))
    order_id = uuid.uuid4()
    invoice = await create_lab_invoice_if_needed(
        session,
        lab_order_id=order_id,
        visit_id=ctx["visit_a_id"],
        tests=[{"test_code": "ZERO-RA3", "test_name": "Zero Price Test", "price": 0.0}],
        patient_id=None,
        current_user={"sub": str(uuid.uuid4()), "role": "lab_technician", "tenant_schema": SCHEMA},
    )
    assert invoice is not None
    assert invoice.total == 0.0
    await session.rollback()
    await session.close()
