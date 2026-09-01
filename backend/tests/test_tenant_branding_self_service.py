"""
Tenant self-service branding endpoints — PATCH /tenants/branding and
POST /tenants/branding/logo. hospital_admin only; other tenant roles get 403;
audit log entries are recorded for both actions.

Run:
    docker compose -f infra/docker-compose.yml up -d postgres redis
    cd backend
    $env:DATABASE_URL="postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital"
    $env:SECRET_KEY="test-secret-key"
    python -m pytest tests/test_tenant_branding_self_service.py -v
"""
import os
import socket
import uuid
from io import BytesIO
from urllib.parse import urlparse

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.security import create_access_token, hash_password

PG_URL = os.environ["DATABASE_URL"]
SCHEMA = f"test_branding_{uuid.uuid4().hex[:12]}"


def _postgres_reachable() -> bool:
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


def _get_app():
    from app.main import app
    return app


def _png_bytes(color=(220, 20, 60), size=(40, 40)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_client():
    import app.core.redis_client as redis_client_module
    redis_client_module._client = None
    from app.db.engine import engine as app_engine
    await app_engine.dispose()

    engine = create_async_engine(PG_URL, pool_pre_ping=True)

    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    nurse_id = uuid.uuid4()

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
                "id": tenant_id, "schema": SCHEMA, "name": "Branding Test Hospital",
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
                    (:id, :tenant_id, :tenant_name, :email, :username, NULL, :hashed_password,
                     :full_name, :role, true, false, now(), now(), now())
                """
            ),
            [
                {
                    "id": admin_id, "tenant_id": tenant_id, "tenant_name": SCHEMA,
                    "email": f"admin-{admin_id}@test.com", "username": f"admin{admin_id.hex[:8]}",
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Branding Admin", "role": "hospital_admin",
                },
                {
                    "id": nurse_id, "tenant_id": tenant_id, "tenant_name": SCHEMA,
                    "email": f"nurse-{nurse_id}@test.com", "username": f"nurse{nurse_id.hex[:8]}",
                    "hashed_password": hash_password("Passw0rd!"), "full_name": "Branding Nurse", "role": "nurse",
                },
            ],
        )

    # audit_logs (and other tenant-scoped tables) live in the tenant's own
    # PostgreSQL schema — create them so record_audit()'s INSERT succeeds.
    from app.db.base import Base
    import app.models.tenant  # noqa: F401  registers all tenant models on Base.metadata

    tenant_tables = [t for t in Base.metadata.sorted_tables if t.schema is None]
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tenant_tables, checkfirst=False))

    transport = ASGITransport(app=_get_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {"client": client, "tenant_id": tenant_id, "admin_id": admin_id, "nurse_id": nurse_id}

    cleanup_engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with cleanup_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text("DELETE FROM public.users WHERE id = ANY(:ids)"), {"ids": [admin_id, nurse_id]})
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
    await cleanup_engine.dispose()


def _token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    return create_access_token(str(user_id), {
        "role": role,
        "tenant_id": str(tenant_id),
        "tenant_schema": SCHEMA,
    })


@pytest.mark.asyncio
async def test_hospital_admin_can_update_branding_colors(app_client):
    token = _token(app_client["admin_id"], app_client["tenant_id"], "hospital_admin")
    response = await app_client["client"].patch(
        "/api/v1/tenants/branding",
        json={"primary_color": "#123456", "secondary_color": "#abcdef"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["primary_color"] == "#123456"
    assert body["secondary_color"] == "#abcdef"


@pytest.mark.asyncio
async def test_update_branding_rejects_malformed_hex_color(app_client):
    token = _token(app_client["admin_id"], app_client["tenant_id"], "hospital_admin")
    response = await app_client["client"].patch(
        "/api/v1/tenants/branding",
        json={"primary_color": "not-a-color"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_non_admin_tenant_role_is_forbidden_from_updating_branding(app_client):
    token = _token(app_client["nurse_id"], app_client["tenant_id"], "nurse")
    response = await app_client["client"].patch(
        "/api/v1/tenants/branding",
        json={"primary_color": "#123456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_hospital_admin_can_upload_logo_and_colors_are_extracted(app_client):
    token = _token(app_client["admin_id"], app_client["tenant_id"], "hospital_admin")
    files = {"file": ("logo.png", _png_bytes(color=(220, 20, 60)), "image/png")}
    response = await app_client["client"].post(
        "/api/v1/tenants/branding/logo",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["logo_url"] is not None
    assert body["primary_color"].lower() == "#dc143c"


@pytest.mark.asyncio
async def test_non_admin_tenant_role_is_forbidden_from_uploading_logo(app_client):
    token = _token(app_client["nurse_id"], app_client["tenant_id"], "nurse")
    files = {"file": ("logo.png", _png_bytes(), "image/png")}
    response = await app_client["client"].post(
        "/api/v1/tenants/branding/logo",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
