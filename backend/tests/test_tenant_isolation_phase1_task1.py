"""
Task 1 — Cross-tenant isolation regression tests.

These are REAL PostgreSQL, schema-per-tenant integration tests. They exercise
the full ASGI stack (TenantMiddleware -> RBAC -> route -> DB) via httpx against
`app.main.app`, so they prove the fix at the same layer the vulnerability
existed in. SQLite-only tests are not sufficient for this requirement because
SQLite has no notion of PostgreSQL schemas / search_path.

Requires a reachable PostgreSQL instance (see infra/docker-compose.yml,
`docker compose up -d postgres`). If it isn't reachable, the whole module is
skipped rather than failing CI/local runs that don't have Postgres up.

Run:
    docker compose -f infra/docker-compose.yml up -d postgres redis
    cd backend
    $env:DATABASE_URL="postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital"
    $env:SECRET_KEY="test-secret-key"
    python -m pytest tests/test_tenant_isolation_phase1_task1.py -v
"""
import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.security import create_access_token, hash_password

PG_URL = os.environ["DATABASE_URL"]


def _postgres_reachable() -> bool:
    """Cheap synchronous TCP check so we don't need an event loop at collection time."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="PostgreSQL not reachable at DATABASE_URL — start infra/docker-compose.yml postgres service",
)


_SCHEMA_SUFFIX = uuid.uuid4().hex[:12]
HOSPITAL_A_SCHEMA = f"test_iso_a_{_SCHEMA_SUFFIX}"
HOSPITAL_B_SCHEMA = f"test_iso_b_{_SCHEMA_SUFFIX}"


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_client(monkeypatch_module):
    """
    Provision two isolated tenant schemas with one receptionist user and one
    patient each directly in PostgreSQL, then yield an httpx client wired to
    the real FastAPI app (full middleware stack included).
    """
    # The app's Redis client and SQLAlchemy engine are process-wide singletons
    # that bind their connections to whichever asyncio event loop touches them
    # first. Reset them so they attach to *this* module's event loop instead of
    # a (possibly already-closed) loop from a previously run test module.
    import app.core.redis_client as redis_client_module
    redis_client_module._client = None
    from app.db.engine import engine as app_engine
    await app_engine.dispose()

    monkeypatch = monkeypatch_module
    # Avoid real SMS/WhatsApp calls during registration.
    monkeypatch.setattr("app.api.v1.patients.send_patient_welcome", lambda **kwargs: None)

    engine = create_async_engine(PG_URL, pool_pre_ping=True)

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    super_admin_id = uuid.uuid4()

    async with engine.begin() as conn:
        for schema in (HOSPITAL_A_SCHEMA, HOSPITAL_B_SCHEMA):
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

        # public.tenants rows
        await conn.execute(
            text(
                """
                INSERT INTO public.tenants
                    (id, schema_name, hospital_name, contact_email, plan, is_active,
                     display_token, created_at, updated_at)
                VALUES
                    (:id, :schema, :name, :email, 'enterprise', true, :display_token, now(), now())
                """
            ),
            [
                {
                    "id": tenant_a_id, "schema": HOSPITAL_A_SCHEMA, "name": "Hospital A",
                    "email": f"a-{tenant_a_id}@test.com", "display_token": f"disp-a-{tenant_a_id}",
                },
                {
                    "id": tenant_b_id, "schema": HOSPITAL_B_SCHEMA, "name": "Hospital B",
                    "email": f"b-{tenant_b_id}@test.com", "display_token": f"disp-b-{tenant_b_id}",
                },
            ],
        )

        # public.users rows (receptionist per tenant)
        await conn.execute(
            text(
                """
                INSERT INTO public.users
                    (id, tenant_id, tenant_name, email, username, phone, hashed_password,
                     full_name, role, is_active, must_change_password, password_changed_at,
                     created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :tenant_name, :email, :username, NULL, :hashed_password,
                     :full_name, 'receptionist', true, false, now(), now(), now())
                """
            ),
            [
                {
                    "id": user_a_id, "tenant_id": tenant_a_id, "tenant_name": HOSPITAL_A_SCHEMA,
                    "email": f"recA-{user_a_id}@test.com", "username": f"recA{user_a_id.hex[:8]}",
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Reception A",
                },
                {
                    "id": user_b_id, "tenant_id": tenant_b_id, "tenant_name": HOSPITAL_B_SCHEMA,
                    "email": f"recB-{user_b_id}@test.com", "username": f"recB{user_b_id.hex[:8]}",
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Reception B",
                },
            ],
        )
        # A real super_admin user row — used to prove super_admin still passes
        # user-existence/active checks even though it bypasses tenant revocation.
        await conn.execute(
            text(
                """
                INSERT INTO public.users
                    (id, tenant_id, tenant_name, email, username, phone, hashed_password,
                     full_name, role, is_active, must_change_password, password_changed_at,
                     created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :tenant_name, :email, :username, NULL, :hashed_password,
                     :full_name, 'super_admin', true, false, now(), now(), now())
                """
            ),
            {
                "id": super_admin_id, "tenant_id": tenant_a_id, "tenant_name": HOSPITAL_A_SCHEMA,
                "email": f"superadmin-{super_admin_id}@test.com", "username": f"sa{super_admin_id.hex[:8]}",
                "hashed_password": hash_password("Passw0rd!"), "full_name": "Platform Super Admin",
            },
        )

    # Build tenant-schema tables via SQLAlchemy metadata (search_path scoped)
    from app.db.base import Base
    import app.models.tenant  # noqa: F401  registers all tenant models on Base.metadata

    tenant_tables = [
        t for t in Base.metadata.sorted_tables
        if t.schema is None  # tenant tables are unqualified; public tables declare schema="public"
    ]
    for schema in (HOSPITAL_A_SCHEMA, HOSPITAL_B_SCHEMA):
        async with engine.begin() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tenant_tables, checkfirst=False))

    await engine.dispose()

    transport = ASGITransport(app=_get_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "tenant_a_id": tenant_a_id,
            "tenant_b_id": tenant_b_id,
            "user_a_id": user_a_id,
            "user_b_id": user_b_id,
            "super_admin_id": super_admin_id,
        }

    # Cleanup
    cleanup_engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with cleanup_engine.begin() as conn:
        for schema in (HOSPITAL_A_SCHEMA, HOSPITAL_B_SCHEMA):
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await conn.execute(text("DELETE FROM public.users WHERE id = ANY(:ids)"), {"ids": [user_a_id, user_b_id, super_admin_id]})
        await conn.execute(text("DELETE FROM public.tenants WHERE id = ANY(:ids)"), {"ids": [tenant_a_id, tenant_b_id]})
    await cleanup_engine.dispose()

    # Detach the app's singletons from this module's loop before it closes,
    # so subsequent test modules reattach cleanly to their own loop.
    await app_engine.dispose()
    if redis_client_module._client is not None:
        await redis_client_module._client.aclose()
        redis_client_module._client = None


def _get_app():
    from app.main import app
    return app


async def _login(client: AsyncClient, login_id: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"login_id": login_id, "password": "Passw0rd!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _register_patient(client: AsyncClient, token: str, phone: str, aadhar: str) -> dict:
    resp = await client.post(
        "/api/v1/patients",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "first_name": "Test",
            "last_name": "Patient",
            "gender": "male",
            "phone": phone,
            "aadhar_number": aadhar,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio(loop_scope="module")
async def test_hospital_a_user_can_access_hospital_a_data(app_client):
    client = app_client["client"]
    token_a = await _login(client, f"recA-{app_client['user_a_id']}@test.com")
    created = await _register_patient(client, token_a, "9000000001", "111122223333")

    resp = await client.get("/api/v1/patients", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 200
    uhids = [p["uhid"] for p in resp.json()]
    assert created["uhid"] in uhids


@pytest.mark.asyncio(loop_scope="module")
async def test_hospital_a_user_cannot_access_hospital_b_data(app_client):
    client = app_client["client"]
    token_a = await _login(client, f"recA-{app_client['user_a_id']}@test.com")
    token_b = await _login(client, f"recB-{app_client['user_b_id']}@test.com")

    await _register_patient(client, token_a, "9000000002", "222233334444")
    patient_b = await _register_patient(client, token_b, "9000000003", "333344445555")

    # Hospital A's list must never contain Hospital B's patient (compare globally
    # unique IDs — UHIDs are independently sequenced per tenant and may collide).
    resp = await client.get("/api/v1/patients", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 200
    ids_a = [p["id"] for p in resp.json()]
    assert patient_b["id"] not in ids_a

    # Direct lookup by ID must also fail cross-tenant (404, not 200 with data).
    resp = await client.get(
        f"/api/v1/patients/{patient_b['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="module")
async def test_x_tenant_schema_header_cannot_override_jwt_tenant(app_client):
    """The removed header override must have zero effect — proves the fix."""
    client = app_client["client"]
    token_a = await _login(client, f"recA-{app_client['user_a_id']}@test.com")
    token_b = await _login(client, f"recB-{app_client['user_b_id']}@test.com")

    patient_b = await _register_patient(client, token_b, "9000000004", "444455556666")

    resp = await client.get(
        "/api/v1/patients",
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Tenant-Schema": HOSPITAL_B_SCHEMA,
        },
    )
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    # Even with a forged header pointing at Hospital B, the response must
    # still be scoped to Hospital A (i.e. never contain Hospital B's patient).
    assert patient_b["id"] not in ids


@pytest.mark.asyncio(loop_scope="module")
async def test_invalid_tenant_schema_claim_is_rejected(app_client):
    """A JWT whose tenant_schema claim doesn't match its tenant_id is rejected with 403."""
    client = app_client["client"]
    forged_token = create_access_token(
        subject=str(app_client["user_a_id"]),
        extra_claims={
            "role": "receptionist",
            "tenant_id": str(app_client["tenant_a_id"]),
            "tenant_schema": "not_the_real_schema",  # mismatched claim
            "hospital_name": "Hospital A",
            "features": [],
            "must_change_password": False,
        },
    )
    resp = await client.get(
        "/api/v1/patients",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="module")
async def test_deactivated_tenant_is_rejected(app_client):
    """A tenant_id that is inactive/unknown to PostgreSQL is rejected with 403."""
    client = app_client["client"]
    unknown_tenant_token = create_access_token(
        subject=str(uuid.uuid4()),
        extra_claims={
            "role": "receptionist",
            "tenant_id": str(uuid.uuid4()),  # not present in public.tenants
            "tenant_schema": "some_schema",
            "hospital_name": "Ghost Hospital",
            "features": [],
            "must_change_password": False,
        },
    )
    resp = await client.get(
        "/api/v1/patients",
        headers={"Authorization": f"Bearer {unknown_tenant_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="module")
async def test_super_admin_cannot_access_tenant_clinical_api(app_client):
    client = app_client["client"]
    super_admin_token = create_access_token(
        subject=str(app_client["super_admin_id"]),
        extra_claims={"role": "super_admin", "tenant_schema": "", "hospital_name": "", "features": [], "session_version": 0},
    )
    resp = await client.get(
        "/api/v1/patients",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="module")
async def test_public_routes_remain_accessible_without_auth(app_client):
    client = app_client["client"]
    resp = await client.get("/health")
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/auth/login",
        json={"login_id": "no-such-user@test.com", "password": "wrong"},
    )
    # Public route reachable (401 for bad creds, never 403/404 due to tenant middleware)
    assert resp.status_code == 401
