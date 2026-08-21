"""
Task 4 — Public token display privacy regression tests.

1. Unit test (SQLite): the `queue:update` "token_issued" broadcast — the same
   channel the unauthenticated public display board subscribes to — must
   never carry patient-identifying fields.
2. Integration tests (real PostgreSQL + real WebSocket handshake): the
   revocable per-tenant display credential grants read-only access to
   `queue:update` only, and rotating it immediately revokes the old value.
"""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


from app.api.v1.queue import issue_token
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.invoice import Invoice
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.token_counter import TokenCounter
from app.models.tenant.visit import Visit
from app.schemas.queue import QueueTokenCreate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "receptionist"}

_TABLES = [
    Patient.__table__, Department.__table__, Doctor.__table__,
    Visit.__table__, QueueToken.__table__, TokenCounter.__table__,
    Invoice.__table__, AuditLog.__table__,
]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


def _make_patient(**overrides) -> Patient:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(), uhid=f"UHID{uuid.uuid4().hex[:8].upper()}", first_name="Priya", last_name="Sharma",
        gender="female", phone="9999999999", created_at=now, updated_at=now,
    )
    defaults.update(overrides)
    return Patient(**defaults)


@pytest.mark.asyncio
async def test_token_issued_broadcast_carries_no_patient_pii(session, monkeypatch):
    patient = _make_patient()
    session.add(patient)
    await session.commit()

    captured = []

    async def _fake_broadcast(tenant, channel, message):
        captured.append((channel, message))

    monkeypatch.setattr("app.api.v1.queue.ws_manager.broadcast", AsyncMock(side_effect=_fake_broadcast))

    await issue_token(
        QueueTokenCreate(patient_id=patient.id, queue_type="registration"),
        session=session,
        current_user=CURRENT_USER,
    )

    queue_events = [msg for (channel, msg) in captured if channel == "queue:update"]
    assert len(queue_events) == 1
    payload = queue_events[0]

    forbidden_keys = {"patient_name", "patient_id", "uhid", "phone", "patient_phone"}
    leaked = forbidden_keys & payload.keys()
    assert not leaked, f"Public queue:update payload leaked PII fields: {leaked}"

    # Also check no PII value leaked under an unexpected key name.
    serialized = str(payload).lower()
    assert patient.first_name.lower() not in serialized
    assert patient.uhid.lower() not in serialized
    assert patient.phone not in serialized

    # Legitimate, non-identifying fields the public display needs are present.
    assert payload["token_no"] == 1
    assert "is_priority" in payload
    assert payload["event"] == "token_issued"


def _postgres_reachable() -> bool:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL not reachable")
class TestDisplayCredentialWebSocket:
    """Real WebSocket handshake tests against the actual FastAPI app + PostgreSQL."""

    SCHEMA = "test_display_ws"

    def setup_method(self):
        import asyncio
        asyncio.run(self._provision())

    def teardown_method(self):
        import asyncio
        asyncio.run(self._cleanup())

    async def _provision(self):
        from sqlalchemy import text
        from app.db.engine import engine as app_engine
        pg_url = os.environ["DATABASE_URL"]
        engine = create_async_engine(pg_url, pool_pre_ping=True)
        self.tenant_id = uuid.uuid4()
        self.display_token = f"disp-{uuid.uuid4().hex}"
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.SCHEMA}" CASCADE'))
            await conn.execute(text(f'CREATE SCHEMA "{self.SCHEMA}"'))
            await conn.execute(
                text(
                    """
                    INSERT INTO public.tenants
                        (id, schema_name, hospital_name, contact_email, plan, is_active,
                         display_token, created_at, updated_at)
                    VALUES
                        (:id, :schema, 'Display WS Test', :email, 'enterprise', true, :tok, now(), now())
                    """
                ),
                {"id": self.tenant_id, "schema": self.SCHEMA, "email": f"ws-{self.tenant_id}@test.com", "tok": self.display_token},
            )
        await engine.dispose()
        # Detach the app's own global engine from this (about-to-close) loop.
        await app_engine.dispose()

    async def _cleanup(self):
        from sqlalchemy import text
        from app.db.engine import engine as app_engine
        pg_url = os.environ["DATABASE_URL"]
        engine = create_async_engine(pg_url, pool_pre_ping=True)
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.SCHEMA}" CASCADE'))
            await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": self.tenant_id})
        await engine.dispose()
        await app_engine.dispose()

    def _client(self):
        from starlette.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_valid_display_token_connects_to_public_queue_channel(self):
        client = self._client()
        with client.websocket_connect(f"/ws/{self.SCHEMA}/queue:update?token={self.display_token}"):
            pass  # connection accepted without exception/close

    def test_wrong_display_token_is_rejected(self):
        from starlette.websockets import WebSocketDisconnect
        client = self._client()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/{self.SCHEMA}/queue:update?token=not-the-real-token") as ws:
                ws.receive_text()

    def test_display_token_cannot_open_a_staff_channel(self):
        from starlette.websockets import WebSocketDisconnect
        client = self._client()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/{self.SCHEMA}/visit:update?token={self.display_token}") as ws:
                ws.receive_text()

    def test_rotating_display_token_revokes_the_old_one(self):
        """
        Rotation must take effect immediately (no caching layer for this
        credential). Exercised directly against the lookup helper the
        websocket router uses, on a single event loop, to avoid unrelated
        cross-loop asyncpg teardown noise from mixing asyncio.run() with a
        separately-threaded TestClient websocket connection in one test.
        """
        import asyncio
        from sqlalchemy import text
        from app.websocket.router import _tenant_display_token

        async def _check():
            from app.db.engine import engine as app_engine
            pg_url = os.environ["DATABASE_URL"]
            engine = create_async_engine(pg_url, pool_pre_ping=True)

            old_token = self.display_token
            assert await _tenant_display_token(self.SCHEMA) == old_token

            new_token = f"disp-rotated-{uuid.uuid4().hex}"
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE public.tenants SET display_token = :tok WHERE id = :id"),
                    {"tok": new_token, "id": self.tenant_id},
                )
            await engine.dispose()

            current = await _tenant_display_token(self.SCHEMA)
            assert current == new_token
            assert current != old_token

            await app_engine.dispose()

        asyncio.run(_check())
