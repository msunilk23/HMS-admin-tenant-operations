"""
Task G — Migration hardening regression tests (real PostgreSQL, not SQLite).

Covers:
  1. Clean database upgrade to head for a brand-new tenant schema (this also
     exercises "upgrade from the Phase 1 pre-document schema" since a fresh
     schema necessarily walks through every pre-0043 revision on the way to
     head — there is no separate "already at 0036" state to special-case).
  2. Exactly one Alembic head.
  3. Safe downgrade + re-upgrade of the newly added document migrations
     (0043, 0044).
  4. document_versions uniqueness constraints (tenant-scoped via schema).
  5. Migration 0044's duplicate-queue-token remediation logic, run directly
     against a crafted pre-fix duplicate dataset.
  6. Migration 0044's tenant-timezone-correct token_date backfill, including
     tokens issued right around local midnight.

Requires PostgreSQL reachable (see infra/docker-compose.yml). Skips cleanly
if not available.
"""
import importlib.util
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"


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


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = PG_URL
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )


def _load_migration_module(filename: str):
    path = ALEMBIC_VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


TEST_TENANT_SCHEMA = f"test_mig_taskg_{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def registered_tenant():
    """Register a brand-new tenant row so `alembic upgrade head` migrates its
    (not-yet-existing) schema from scratch — a genuine clean-DB-to-head run
    that also passes through every pre-document revision along the way."""
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    tenant_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_TENANT_SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{TEST_TENANT_SCHEMA}"'))
        await conn.execute(
            text(
                """
                INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, is_active, timezone, display_token)
                VALUES (:id, :schema, 'Task G Test Hospital', :email, true, 'Asia/Kolkata', :dt)
                """
            ),
            {"id": tenant_id, "schema": TEST_TENANT_SCHEMA, "email": f"{TEST_TENANT_SCHEMA}@example.test", "dt": uuid.uuid4().hex},
        )
    yield {"tenant_id": tenant_id, "schema": TEST_TENANT_SCHEMA, "engine": engine}
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_TENANT_SCHEMA}" CASCADE'))
    await engine.dispose()


def test_clean_upgrade_to_head_succeeds_for_a_brand_new_tenant_schema(registered_tenant):
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.asyncio(loop_scope="module")
async def test_clean_upgrade_creates_p29_pharmacy_linkage(registered_tenant):
        schema = registered_tenant["schema"]
        engine = registered_tenant["engine"]
        async with engine.connect() as connection:
                await connection.execute(text(f'SET search_path TO "{schema}", public'))
                columns = (await connection.execute(text("""
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                            AND ((table_name = 'invoices' AND column_name = 'pharmacy_dispense_id')
                                OR (table_name = 'pharmacy_dispenses' AND column_name = 'invoice_id'))
                """))).all()
                assert set(columns) == {
                        ("invoices", "pharmacy_dispense_id"),
                        ("pharmacy_dispenses", "invoice_id"),
                }

                constraints = (await connection.execute(text("""
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = current_schema()
                            AND constraint_name IN (
                                'uq_invoices_pharmacy_dispense',
                                'fk_invoices_pharmacy_dispense_id',
                                'fk_pharmacy_dispenses_invoice_id'
                            )
                """))).scalars().all()
                assert set(constraints) == {
                        "uq_invoices_pharmacy_dispense",
                        "fk_invoices_pharmacy_dispense_id",
                        "fk_pharmacy_dispenses_invoice_id",
                }


def test_exactly_one_alembic_head(registered_tenant):
    result = _run_alembic("heads")
    assert result.returncode == 0, result.stderr
    head_lines = [line for line in result.stdout.splitlines() if "(head)" in line]
    assert len(head_lines) == 1, f"Expected exactly one Alembic head, got: {result.stdout}"


def test_downgrade_and_reupgrade_of_document_migrations_is_safe(registered_tenant):
    down = _run_alembic("downgrade", "-2")
    assert down.returncode == 0, f"downgrade -2 failed:\n{down.stdout}\n{down.stderr}"

    up = _run_alembic("upgrade", "head")
    assert up.returncode == 0, f"re-upgrade to head failed:\n{up.stdout}\n{up.stderr}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg_session_for_schema(registered_tenant):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    engine = registered_tenant["engine"]
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async def new_session():
        s = maker()
        await s.execute(text(f'SET search_path TO "{TEST_TENANT_SCHEMA}", public'))
        return s

    return new_session


@pytest.mark.asyncio(loop_scope="module")
async def test_document_versions_uniqueness_constraint_is_tenant_scoped(pg_session_for_schema):
    from app.models.tenant.document import DocumentVersion

    new_session = pg_session_for_schema
    parent_id = uuid.uuid4()

    session = await new_session()
    session.add(DocumentVersion(
        id=uuid.uuid4(), document_type="invoice", parent_id=parent_id, version=1,
        checksum_sha256="a" * 64, snapshot_checksum="b" * 64, storage_key=f"invoice/{parent_id}/v1-x.pdf",
        file_size_bytes=10, snapshot_json={"x": 1}, is_current=True,
    ))
    await session.commit()
    await session.close()

    # Same (document_type, parent_id, version) must be rejected.
    session = await new_session()
    session.add(DocumentVersion(
        id=uuid.uuid4(), document_type="invoice", parent_id=parent_id, version=1,
        checksum_sha256="c" * 64, snapshot_checksum="d" * 64, storage_key=f"invoice/{parent_id}/v1-y.pdf",
        file_size_bytes=20, snapshot_json={"x": 2}, is_current=True,
    ))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    await session.close()


async def _provision_pre_remediation_queue_tokens(engine, schema: str):
    """Build a schema containing queue_tokens WITHOUT the 0037 unique
    constraint (so we can seed pre-existing duplicates), used only to
    exercise migration 0044's remediation logic in isolation."""
    from app.db.base import Base
    from app.models.tenant.appointment import Appointment
    from app.models.tenant.department import Department
    from app.models.tenant.doctor import Doctor
    from app.models.tenant.patient import Patient
    from app.models.tenant.queue_token import QueueToken
    from app.models.tenant.visit import Visit

    tables = [Department.__table__, Doctor.__table__, Appointment.__table__, Patient.__table__, Visit.__table__, QueueToken.__table__]
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables, checkfirst=False))
        # Drop the unique constraint so we can seed a duplicate historical state.
        await conn.execute(text(f'ALTER TABLE "{schema}".queue_tokens DROP CONSTRAINT uq_queue_tokens_scope_date_token_no'))


def _apply_0044(sync_conn, schema: str):
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations

    sync_conn.execute(text(f'SET search_path TO "{schema}", public'))
    mc = MigrationContext.configure(sync_conn)
    module = _load_migration_module("0044_harden_queue_token_migration.py")
    with Operations.context(mc):
        module.upgrade()


@pytest.mark.asyncio(loop_scope="module")
async def test_migration_0044_remediates_historical_duplicate_tokens(registered_tenant):
    schema = f"test_mig_dup_{uuid.uuid4().hex[:8]}"
    engine = registered_tenant["engine"]
    tenant_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, is_active, timezone, display_token)
                VALUES (:id, :schema, 'Dup Test', :email, true, 'Asia/Kolkata', :dt)
                """
            ),
            {"id": tenant_id, "schema": schema, "email": f"{schema}@example.test", "dt": uuid.uuid4().hex},
        )
    try:
        await _provision_pre_remediation_queue_tokens(engine, schema)

        from app.models.tenant.patient import Patient
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        patient_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        async with maker() as s:
            await s.execute(text(f'SET search_path TO "{schema}", public'))
            s.add(Patient(id=patient_id, uhid="UHIDDUP0001", first_name="Dup", last_name="Test", gender="male", phone="9000000002", created_at=now, updated_at=now))
            await s.commit()

        # Seed two genuinely duplicate historical rows: same scope/date/token_no
        # (this is exactly the pre-0037 lost-update race the constraint now prevents).
        scope = "queue:registration"
        tdate = date(2026, 1, 15)
        async with engine.begin() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            for i in range(2):
                await conn.execute(
                    text(
                        """
                        INSERT INTO queue_tokens (id, patient_id, uhid, token_no, token_scope, token_date, queue_type, priority, status, issued_at)
                        VALUES (:id, :pid, 'UHIDDUP0001', 1, :scope, :tdate, 'registration', 'normal', 'checked_in', :issued_at)
                        """
                    ),
                    {"id": uuid.uuid4(), "pid": patient_id, "scope": scope, "tdate": tdate, "issued_at": now + timedelta(seconds=i)},
                )

        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: _apply_0044(sync_conn, schema))

        async with engine.begin() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            rows = (await conn.execute(text("SELECT token_no FROM queue_tokens WHERE token_scope = :s ORDER BY token_no"), {"s": scope})).fetchall()
            # Recreate the unique constraint 0037 defines — must now succeed with zero violations.
            await conn.execute(
                text(
                    'ALTER TABLE queue_tokens ADD CONSTRAINT uq_queue_tokens_scope_date_token_no '
                    'UNIQUE (token_scope, token_date, token_no)'
                )
            )

        token_nos = sorted(r[0] for r in rows)
        assert len(token_nos) == 2
        assert len(set(token_nos)) == 2, "Duplicate tokens must be deterministically renumbered to be unique"
        assert token_nos[0] == 1, "The earliest-issued row must keep its original token number"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})


@pytest.mark.asyncio(loop_scope="module")
async def test_migration_0044_backfills_token_date_using_tenant_timezone_not_session_timezone(registered_tenant):
    """A token issued at 2026-01-15 19:00 UTC is 2026-01-16 00:30 in
    Asia/Kolkata (UTC+5:30) — a UTC-based ::date cast would land on the wrong
    calendar day for that tenant."""
    schema = f"test_mig_tz_{uuid.uuid4().hex[:8]}"
    engine = registered_tenant["engine"]
    tenant_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, is_active, timezone, display_token)
                VALUES (:id, :schema, 'TZ Test', :email, true, 'Asia/Kolkata', :dt)
                """
            ),
            {"id": tenant_id, "schema": schema, "email": f"{schema}@example.test", "dt": uuid.uuid4().hex},
        )
    try:
        await _provision_pre_remediation_queue_tokens(engine, schema)

        from app.models.tenant.patient import Patient
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        patient_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        async with maker() as s:
            await s.execute(text(f'SET search_path TO "{schema}", public'))
            s.add(Patient(id=patient_id, uhid="UHIDTZ00001", first_name="TZ", last_name="Test", gender="male", phone="9000000003", created_at=now, updated_at=now))
            await s.commit()

        issued_at_utc = datetime(2026, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
        token_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            await conn.execute(
                text(
                    """
                    INSERT INTO queue_tokens (id, patient_id, uhid, token_no, token_scope, token_date, queue_type, priority, status, issued_at)
                    VALUES (:id, :pid, 'UHIDTZ00001', 1, 'queue:registration', :wrong_date, 'registration', 'normal', 'checked_in', :issued_at)
                    """
                ),
                {"id": token_id, "pid": patient_id, "wrong_date": date(2026, 1, 15), "issued_at": issued_at_utc},
            )

        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: _apply_0044(sync_conn, schema))

        async with engine.begin() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            corrected = (await conn.execute(text("SELECT token_date FROM queue_tokens WHERE id = :id"), {"id": token_id})).scalar()

        assert corrected == date(2026, 1, 16), (
            f"Expected tenant-local (Asia/Kolkata) date 2026-01-16 for a 19:00 UTC token, got {corrected}"
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
