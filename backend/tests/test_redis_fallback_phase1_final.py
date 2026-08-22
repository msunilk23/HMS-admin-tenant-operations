"""
Task B (phase1-final-release-fixes) — secure Redis-failure fallback for tenant
status resolution in `TenantMiddleware`.

Real PostgreSQL tenant rows; Redis failures are simulated by monkeypatching the
cache helper functions to raise (the same effect as a timeout/connection
refusal), so we don't need to physically stop a Redis container to prove the
fallback behaviour deterministically.

Run:
    docker compose -f infra/docker-compose.yml up -d postgres redis
    cd backend
    $env:DATABASE_URL="postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital"
    $env:SECRET_KEY="test-secret-key"
    python -m pytest tests/test_redis_fallback_phase1_final.py -v
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PG_URL = os.environ["DATABASE_URL"]


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


class _RedisDown:
    """Drop-in replacement for a cache coroutine that always fails like a timeout/connection error."""
    async def __call__(self, *_args, **_kwargs):
        raise ConnectionError("Redis unavailable (simulated)")


@pytest_asyncio.fixture(autouse=True)
async def _reset_engine_for_this_loop():
    """
    Each test function gets its own asyncio event loop (function-scoped,
    default pytest-asyncio). The app's SQLAlchemy engine is a process-wide
    singleton bound to whichever loop first touched it, so it must be
    disposed before every test to attach cleanly to the current loop.
    """
    from app.db.engine import engine as app_engine
    await app_engine.dispose()
    yield
    await app_engine.dispose()


@pytest_asyncio.fixture
async def tenant_rows():
    """Insert one active and one suspended tenant directly in PostgreSQL."""
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    active_id = uuid.uuid4()
    suspended_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO public.tenants
                    (id, schema_name, hospital_name, contact_email, plan, is_active,
                     display_token, created_at, updated_at)
                VALUES
                    (:id, :schema, :name, :email, 'enterprise', :is_active, :display_token, now(), now())
                """
            ),
            [
                {
                    "id": active_id, "schema": f"redis_fb_active_{active_id.hex[:8]}",
                    "name": "Active Hospital", "email": f"active-{active_id}@test.com",
                    "is_active": True, "display_token": f"disp-{active_id}",
                },
                {
                    "id": suspended_id, "schema": f"redis_fb_suspended_{suspended_id.hex[:8]}",
                    "name": "Suspended Hospital", "email": f"suspended-{suspended_id}@test.com",
                    "is_active": False, "display_token": f"disp-{suspended_id}",
                },
            ],
        )
    await engine.dispose()

    yield {"active_id": active_id, "suspended_id": suspended_id}

    cleanup_engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with cleanup_engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.tenants WHERE id = ANY(:ids)"), {"ids": [active_id, suspended_id]})
    await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_redis_unavailable_active_tenant_falls_back_to_postgres(monkeypatch, tenant_rows):
    from app.middleware import tenant as tenant_mw

    monkeypatch.setattr(tenant_mw, "get_cached_tenant_status", _RedisDown())
    monkeypatch.setattr(tenant_mw, "set_cached_tenant_status", _RedisDown())

    status = await tenant_mw._load_tenant_status(str(tenant_rows["active_id"]))
    assert status is not None
    assert status["is_active"] is True


@pytest.mark.asyncio
async def test_redis_unavailable_suspended_tenant_still_rejected(monkeypatch, tenant_rows):
    from app.middleware import tenant as tenant_mw

    monkeypatch.setattr(tenant_mw, "get_cached_tenant_status", _RedisDown())
    monkeypatch.setattr(tenant_mw, "set_cached_tenant_status", _RedisDown())

    status = await tenant_mw._load_tenant_status(str(tenant_rows["suspended_id"]))
    assert status is not None
    # Never treat a Redis failure as proof of an active tenant — must reflect
    # the real (suspended) PostgreSQL state, not silently allow the request.
    assert status["is_active"] is False


@pytest.mark.asyncio
async def test_redis_unavailable_unknown_tenant_rejected(monkeypatch):
    from app.middleware import tenant as tenant_mw

    monkeypatch.setattr(tenant_mw, "get_cached_tenant_status", _RedisDown())
    monkeypatch.setattr(tenant_mw, "set_cached_tenant_status", _RedisDown())

    status = await tenant_mw._load_tenant_status(str(uuid.uuid4()))
    assert status is None


@pytest.mark.asyncio
async def test_cache_write_failure_after_successful_lookup_does_not_fail_request(monkeypatch, tenant_rows):
    from app.middleware import tenant as tenant_mw

    async def _cache_miss(*_a, **_kw):
        return None

    monkeypatch.setattr(tenant_mw, "get_cached_tenant_status", _cache_miss)
    monkeypatch.setattr(tenant_mw, "set_cached_tenant_status", _RedisDown())

    # PostgreSQL lookup succeeds; the best-effort cache write failing afterward
    # must not turn into a request-level failure.
    status = await tenant_mw._load_tenant_status(str(tenant_rows["active_id"]))
    assert status is not None
    assert status["is_active"] is True


@pytest.mark.asyncio
async def test_redis_and_postgres_both_unavailable_fails_securely(monkeypatch, tenant_rows):
    from app.middleware import tenant as tenant_mw

    monkeypatch.setattr(tenant_mw, "get_cached_tenant_status", _RedisDown())

    class _BrokenSessionLocal:
        def __call__(self):
            raise ConnectionError("PostgreSQL unavailable (simulated)")

    monkeypatch.setattr("app.db.engine.AsyncSessionLocal", _BrokenSessionLocal())

    # Neither cache nor DB can answer — must fail securely (None => caller
    # rejects with a generic 403), never raise an unhandled exception that
    # could leak internals, and never treat this as "tenant is active".
    status = await tenant_mw._load_tenant_status(str(tenant_rows["active_id"]))
    assert status is None


@pytest.mark.asyncio
async def test_recovery_after_redis_becomes_available_again(monkeypatch, tenant_rows):
    from app.middleware import tenant as tenant_mw

    monkeypatch.setattr(tenant_mw, "get_cached_tenant_status", _RedisDown())
    monkeypatch.setattr(tenant_mw, "set_cached_tenant_status", _RedisDown())
    first = await tenant_mw._load_tenant_status(str(tenant_rows["active_id"]))
    assert first is not None and first["is_active"] is True

    # Redis becomes available again — subsequent requests should be served
    # from cache (or, on a cold cache, PostgreSQL) without any special state
    # left over from the earlier outage.
    monkeypatch.undo()
    from app.core.redis_client import invalidate_tenant_status_cache
    try:
        await invalidate_tenant_status_cache(str(tenant_rows["active_id"]))
    except Exception:
        pytest.skip("Redis not reachable in this environment for the recovery leg")

    second = await tenant_mw._load_tenant_status(str(tenant_rows["active_id"]))
    assert second is not None
    assert second["is_active"] is True
