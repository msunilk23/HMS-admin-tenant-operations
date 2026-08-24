"""
Task A (phase1-final-release-fixes) — versioned refresh-token regression tests.

Real PostgreSQL, full ASGI stack (httpx -> app.main.app), exercising the actual
production /login, /refresh, /change-password, /users/*, /super/hospitals/*
endpoints. No test manufactures or re-signs a JWT with claims that production
issuance code does not itself generate — every token used here is the literal
string returned by a real endpoint call.

Run:
    docker compose -f infra/docker-compose.yml up -d postgres redis
    cd backend
    $env:DATABASE_URL="postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital"
    $env:SECRET_KEY="test-secret-key"
    python -m pytest tests/test_refresh_token_versioning_phase1_final.py -v
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

from app.core.security import hash_password

PG_URL = os.environ["DATABASE_URL"]
SCHEMA = "test_refresh_ver_hospital"


def _postgres_reachable() -> bool:
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


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


def _get_app():
    from app.main import app
    return app


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_client(monkeypatch_module):
    import app.core.redis_client as redis_client_module
    redis_client_module._client = None
    from app.db.engine import engine as app_engine
    await app_engine.dispose()

    monkeypatch_module.setattr("app.api.v1.users.send_staff_credentials", lambda **kwargs: None)

    engine = create_async_engine(PG_URL, pool_pre_ping=True)

    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    staff_id = uuid.uuid4()
    super_admin_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
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
            {
                "id": tenant_id, "schema": SCHEMA, "name": "Refresh Versioning Hospital",
                "email": f"contact-{tenant_id}@test.com", "display_token": f"disp-{tenant_id}",
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO public.users
                    (id, tenant_id, tenant_name, email, username, phone, hashed_password,
                     full_name, role, is_active, must_change_password, password_changed_at,
                     created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :tenant_name, :email, :username, :phone, :hashed_password,
                     :full_name, :role, true, false, now(), now(), now())
                """
            ),
            [
                {
                    "id": admin_id, "tenant_id": tenant_id, "tenant_name": SCHEMA,
                    "email": f"admin-{admin_id}@test.com", "username": f"admin{admin_id.hex[:8]}",
                    "phone": None,
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Hospital Admin",
                    "role": "hospital_admin",
                },
                {
                    "id": staff_id, "tenant_id": tenant_id, "tenant_name": SCHEMA,
                    "email": f"staff-{staff_id}@test.com", "username": f"staff{staff_id.hex[:8]}",
                    "phone": "+919000000099",
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Reception Staff",
                    "role": "receptionist",
                },
                {
                    "id": super_admin_id, "tenant_id": tenant_id, "tenant_name": SCHEMA,
                    "email": f"sa-{super_admin_id}@test.com", "username": f"sa{super_admin_id.hex[:8]}",
                    "phone": None,
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Platform Super Admin",
                    "role": "super_admin",
                },
            ],
        )

    from app.db.base import Base
    import app.models.tenant  # noqa: F401
    tenant_tables = [t for t in Base.metadata.sorted_tables if t.schema is None]
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tenant_tables, checkfirst=False))

    await engine.dispose()

    transport = ASGITransport(app=_get_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "tenant_id": tenant_id,
            "admin_id": admin_id,
            "staff_id": staff_id,
            "super_admin_id": super_admin_id,
            "admin_email": f"admin-{admin_id}@test.com",
            "staff_email": f"staff-{staff_id}@test.com",
            "super_admin_email": f"sa-{super_admin_id}@test.com",
        }

    cleanup_engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with cleanup_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text("DELETE FROM public.users WHERE tenant_id = :id"), {"id": tenant_id})
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
    await cleanup_engine.dispose()

    await app_engine.dispose()
    if redis_client_module._client is not None:
        await redis_client_module._client.aclose()
        redis_client_module._client = None


async def _login(client: AsyncClient, login_id: str, password: str = "Passw0rd!") -> dict:
    resp = await client.post("/api/v1/auth/login", json={"login_id": login_id, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _refresh(client: AsyncClient, refresh_token: str):
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})


async def _me_probe(client: AsyncClient, access_token: str):
    """No dedicated /me endpoint exists; use a cheap authenticated GET accessible
    to receptionist/nurse/hospital_admin/doctor as an access-token liveness probe."""
    return await client.get("/api/v1/patients", headers={"Authorization": f"Bearer {access_token}"})


@pytest.mark.asyncio(loop_scope="module")
async def test_login_issued_refresh_token_works_without_claim_manipulation(app_client):
    client = app_client["client"]
    tokens = await _login(client, app_client["staff_email"])
    resp = await _refresh(client, tokens["refresh_token"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


@pytest.mark.asyncio(loop_scope="module")
async def test_refresh_rotation_returns_another_valid_refresh_token(app_client):
    client = app_client["client"]
    tokens = await _login(client, app_client["staff_email"])
    first = await _refresh(client, tokens["refresh_token"])
    assert first.status_code == 200, first.text
    second_refresh = first.json()["refresh_token"]
    second = await _refresh(client, second_refresh)
    assert second.status_code == 200, second.text
    assert second.json()["access_token"]


@pytest.mark.asyncio(loop_scope="module")
async def test_password_change_invalidates_earlier_access_and_refresh_tokens(app_client):
    client = app_client["client"]
    tokens = await _login(client, app_client["staff_email"])
    old_access = tokens["access_token"]
    old_refresh = tokens["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {old_access}"},
        json={"current_password": "Passw0rd!", "new_password": "NewPassw0rd!2"},
    )
    assert resp.status_code == 200, resp.text

    # Old access token must be dead.
    probe = await _me_probe(client, old_access)
    assert probe.status_code == 401

    # Old refresh token must be dead.
    refresh_resp = await _refresh(client, old_refresh)
    assert refresh_resp.status_code == 401

    # Restore the password so later tests in this module can still log in with it.
    new_tokens = resp.json()
    restore = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
        json={"current_password": "NewPassw0rd!2", "new_password": "Passw0rd!"},
    )
    assert restore.status_code == 200, restore.text


@pytest.mark.asyncio(loop_scope="module")
async def test_login_after_password_change_issues_working_refresh_token(app_client):
    client = app_client["client"]
    tokens = await _login(client, app_client["staff_email"])
    change_resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"current_password": "Passw0rd!", "new_password": "AnotherPass1!"},
    )
    assert change_resp.status_code == 200, change_resp.text

    # Fresh login picks up the current (incremented) session_version from the DB.
    relogin = await _login(client, app_client["staff_email"], password="AnotherPass1!")
    refresh_resp = await _refresh(client, relogin["refresh_token"])
    assert refresh_resp.status_code == 200, refresh_resp.text

    # Restore password for subsequent tests.
    restore = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {relogin['access_token']}"},
        json={"current_password": "AnotherPass1!", "new_password": "Passw0rd!"},
    )
    assert restore.status_code == 200, restore.text


@pytest.mark.asyncio(loop_scope="module")
async def test_admin_password_reset_invalidates_earlier_tokens(app_client):
    client = app_client["client"]
    admin_tokens = await _login(client, app_client["admin_email"])
    staff_tokens = await _login(client, app_client["staff_email"])
    old_access = staff_tokens["access_token"]

    resp = await client.post(
        f"/api/v1/users/{app_client['staff_id']}/reset-password",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text

    probe = await _me_probe(client, old_access)
    assert probe.status_code == 401

    # Reset the DB password back to a known value via a direct hash update so
    # later tests can still authenticate (the reset endpoint only delivers the
    # new password via SMS by design and never echoes it in the response).
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE public.users SET hashed_password = :h WHERE id = :id"),
            {"h": hash_password("Passw0rd!"), "id": app_client["staff_id"]},
        )
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_role_change_invalidates_earlier_tokens(app_client):
    client = app_client["client"]
    admin_tokens = await _login(client, app_client["admin_email"])
    staff_tokens = await _login(client, app_client["staff_email"])
    old_access = staff_tokens["access_token"]

    resp = await client.patch(
        f"/api/v1/users/{app_client['staff_id']}",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
        json={"role": "nurse"},
    )
    assert resp.status_code == 200, resp.text

    probe = await _me_probe(client, old_access)
    assert probe.status_code == 401

    # Revert role for later tests.
    revert = await client.patch(
        f"/api/v1/users/{app_client['staff_id']}",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
        json={"role": "receptionist"},
    )
    assert revert.status_code == 200, revert.text


@pytest.mark.asyncio(loop_scope="module")
async def test_tenant_invalidation_rejects_earlier_tenant_tokens_and_new_token_works(app_client):
    client = app_client["client"]
    super_admin_tokens = await _login(client, app_client["super_admin_email"])
    old_tokens = await _login(client, app_client["staff_email"])

    resp = await client.patch(
        f"/api/v1/super/hospitals/{app_client['tenant_id']}",
        headers={"Authorization": f"Bearer {super_admin_tokens['access_token']}"},
        json={"is_active": True},
    )
    assert resp.status_code == 200, resp.text

    old_probe = await _me_probe(client, old_tokens["access_token"])
    assert old_probe.status_code == 401
    old_refresh_resp = await _refresh(client, old_tokens["refresh_token"])
    assert old_refresh_resp.status_code == 401

    # A freshly issued token after the invalidation carries the new tenant
    # session version and must work normally end-to-end (login + refresh).
    new_tokens = await _login(client, app_client["staff_email"])
    new_probe = await _me_probe(client, new_tokens["access_token"])
    assert new_probe.status_code == 200
    new_refresh_resp = await _refresh(client, new_tokens["refresh_token"])
    assert new_refresh_resp.status_code == 200, new_refresh_resp.text
