"""
Task 3 — Concurrency-safe token allocation regression tests.

Uses the real PostgreSQL instance (schema-per-tenant) so the atomic
INSERT ... ON CONFLICT DO UPDATE counter and queue_tokens uniqueness
constraint are exercised against genuine concurrent transactions, not
SQLite's single-writer semantics.

Requires PostgreSQL reachable (see infra/docker-compose.yml). Skips cleanly
if not available.
"""
import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.schemas.queue import QueueTokenCreate

PG_URL = os.environ["DATABASE_URL"]


def _postgres_reachable() -> bool:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="PostgreSQL not reachable at DATABASE_URL — start infra/docker-compose.yml postgres service",
)

SCHEMA = "test_token_alloc"
CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": SCHEMA, "role": "receptionist"}


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg(monkeypatch_module):
    """Provision a real Postgres tenant schema with the tables issue_token touches."""
    from app.db.base import Base
    from app.models.tenant.appointment import Appointment
    from app.models.tenant.audit_log import AuditLog
    from app.models.tenant.department import Department
    from app.models.tenant.doctor import Doctor
    from app.models.tenant.patient import Patient
    from app.models.tenant.queue_token import QueueToken
    from app.models.tenant.token_counter import TokenCounter
    from app.models.tenant.visit import Visit

    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await conn.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        tables = [
            Department.__table__, Doctor.__table__, Appointment.__table__,
            Patient.__table__, Visit.__table__, QueueToken.__table__,
            TokenCounter.__table__, AuditLog.__table__,
        ]
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables, checkfirst=False))

    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async def new_session() -> AsyncSession:
        s = maker()
        await s.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        return s

    patient_id = uuid.uuid4()
    dept_a_id = uuid.uuid4()
    dept_b_id = uuid.uuid4()
    async with (await new_session()) as s:
        from app.models.tenant.patient import Patient as PatientModel
        now = datetime.now(timezone.utc)
        s.add(PatientModel(
            id=patient_id, uhid=f"UHID{uuid.uuid4().hex[:8].upper()}", first_name="Test", last_name="Patient",
            gender="male", phone="9000000000", created_at=now, updated_at=now,
        ))
        s.add(Department(id=dept_a_id, name="Dept A"))
        s.add(Department(id=dept_b_id, name="Dept B"))
        await s.commit()

    yield {
        "new_session": new_session, "patient_id": patient_id, "engine": engine,
        "dept_a_id": dept_a_id, "dept_b_id": dept_b_id,
    }

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_twenty_concurrent_walkin_registrations_get_unique_sequential_tokens(pg):
    from app.api.v1.queue import issue_token

    async def _one_registration():
        session = await pg["new_session"]()
        try:
            result = await issue_token(
                QueueTokenCreate(patient_id=pg["patient_id"], queue_type="registration"),
                session=session,
                current_user=CURRENT_USER,
            )
            return result.token_no
        finally:
            await session.close()

    results = await asyncio.gather(*[_one_registration() for _ in range(20)])

    assert len(results) == 20
    assert len(set(results)) == 20, f"Duplicate token numbers issued: {results}"
    assert sorted(results) == list(range(1, 21)), f"Expected sequential 1..20, got {sorted(results)}"


@pytest.mark.asyncio(loop_scope="module")
async def test_department_scoped_tokens_are_independent(pg):
    from app.api.v1.queue import issue_token

    dept_a = pg["dept_a_id"]
    dept_b = pg["dept_b_id"]

    async def _register(department_id):
        session = await pg["new_session"]()
        try:
            result = await issue_token(
                QueueTokenCreate(patient_id=pg["patient_id"], queue_type="consultation", department_id=department_id),
                session=session,
                current_user=CURRENT_USER,
            )
            return result.token_no
        finally:
            await session.close()

    token_a1, token_a2 = await asyncio.gather(_register(dept_a), _register(dept_a))
    token_b1 = await _register(dept_b)

    # Department A gets its own 1..2 sequence; Department B starts independently at 1.
    assert sorted([token_a1, token_a2]) == [1, 2]
    assert token_b1 == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_daily_counter_resets_per_tenant_local_date(pg):
    from app.services.token_allocation import _allocate_token_number

    session = await pg["new_session"]()
    try:
        today = date.today()
        tomorrow = today + timedelta(days=1)

        n1 = await _allocate_token_number(session, "queue:reset_test", today)
        n2 = await _allocate_token_number(session, "queue:reset_test", today)
        n3 = await _allocate_token_number(session, "queue:reset_test", tomorrow)  # different day -> resets
        await session.commit()

        assert (n1, n2) == (1, 2)
        assert n3 == 1
    finally:
        await session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_rollback_does_not_corrupt_or_duplicate_counter(pg):
    """
    If token creation fails downstream of allocation (e.g. the caller's
    transaction is rolled back for an unrelated reason), the counter must not
    be reused — the next allocation continues sequentially rather than
    handing out a number twice.
    """
    from app.services.token_allocation import _allocate_token_number

    session = await pg["new_session"]()
    try:
        n1 = await _allocate_token_number(session, "queue:rollback_test", date.today())
        await session.commit()
        assert n1 == 1

        # Simulate a failed downstream operation after allocation within the
        # same transaction — roll back everything except the already-committed counter.
        n2 = await _allocate_token_number(session, "queue:rollback_test", date.today())
        await session.rollback()  # discard n2's transaction without committing

        # A fresh allocation must continue from n1+1, not reuse n1 or silently duplicate.
        n3 = await _allocate_token_number(session, "queue:rollback_test", date.today())
        await session.commit()
        assert n3 >= n1 + 1
    finally:
        await session.close()
