"""Disposable PostgreSQL contract tests for PF-1 migration 0093."""
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")

PG_URL = os.environ["DATABASE_URL"]
BACKEND_DIR = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND_DIR / "alembic" / "versions"


def _reachable() -> bool:
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="PostgreSQL is not reachable")


def _migration():
    path = VERSIONS / "0093_post_consultation_patient_routing.py"
    spec = importlib.util.spec_from_file_location("pf1_migration_0093", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_alembic(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": PG_URL},
        capture_output=True,
        text=True,
    )


async def _drop(engine, schema: str):
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


async def _dependencies(engine, schema: str):
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        for table in ("patients", "visits", "consultations", "prescriptions"):
            await conn.execute(text(f'CREATE TABLE "{schema}"."{table}" (id UUID PRIMARY KEY)'))


async def _apply(engine, schema: str):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    async with engine.begin() as conn:
        def apply(sync_conn):
            sync_conn.execute(text(f'SET search_path TO "{schema}", public'))
            context = MigrationContext.configure(sync_conn)
            with Operations.context(context):
                _migration().upgrade()
        await conn.run_sync(apply)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine():
    value = create_async_engine(PG_URL, pool_pre_ping=True)
    yield value
    await value.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_contract_and_replay(engine):
    schema = f"test_pf1_contract_{uuid.uuid4().hex[:8]}"
    await _dependencies(engine, schema)
    await _apply(engine, schema)
    await _apply(engine, schema)
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        tables = set((await conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name IN ('patient_route_configurations','patient_routes','patient_route_steps','patient_route_events','prescription_document_requests')
        """))).scalars().all())
        assert tables == {"patient_route_configurations", "patient_routes", "patient_route_steps", "patient_route_events", "prescription_document_requests"}
        constraints = set((await conn.execute(text("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_schema = current_schema()
              AND constraint_name IN ('ck_patient_route_config_positive_window','ck_patient_routes_status','ck_patient_route_steps_destination','ck_patient_route_steps_status','uq_patient_routes_visit','uq_patient_route_steps_destination','uq_prescription_document_requests_prescription')
        """))).scalars().all())
        assert constraints == {"ck_patient_route_config_positive_window", "ck_patient_routes_status", "ck_patient_route_steps_destination", "ck_patient_route_steps_status", "uq_patient_routes_visit", "uq_patient_route_steps_destination", "uq_prescription_document_requests_prescription"}
        indexes = set((await conn.execute(text("""
            SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()
              AND indexname IN ('uq_patient_route_config_tenant_default','uq_patient_route_config_tenant_facility','ix_patient_route_steps_lookup','ix_patient_route_events_step_time')
        """))).scalars().all())
        assert indexes == {"uq_patient_route_config_tenant_default", "uq_patient_route_config_tenant_facility", "ix_patient_route_steps_lookup", "ix_patient_route_events_step_time"}
    await _drop(engine, schema)


@pytest.mark.asyncio(loop_scope="module")
async def test_compatible_partial_recovery_and_incompatible_type_rejection(engine):
    partial = f"test_pf1_partial_{uuid.uuid4().hex[:8]}"
    await _dependencies(engine, partial)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{partial}".patient_route_configurations (id UUID PRIMARY KEY)'))
    await _apply(engine, partial)
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{partial}", public'))
        columns = set((await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'patient_route_configurations'
        """))).scalars().all())
        assert {"id", "tenant_id", "facility_id", "presentation_window_minutes", "created_at", "updated_at"}.issubset(columns)
    await _drop(engine, partial)

    incompatible = f"test_pf1_bad_type_{uuid.uuid4().hex[:8]}"
    await _dependencies(engine, incompatible)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{incompatible}".patient_route_configurations (id UUID PRIMARY KEY, tenant_id TEXT NOT NULL)'))
    with pytest.raises(RuntimeError, match="incompatible patient_route_configurations.tenant_id"):
        await _apply(engine, incompatible)
    await _drop(engine, incompatible)


@pytest.mark.asyncio(loop_scope="module")
async def test_existing_invalid_window_is_rejected_before_constraint(engine):
    schema = f"test_pf1_bad_window_{uuid.uuid4().hex[:8]}"
    await _dependencies(engine, schema)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{schema}".patient_route_configurations (id UUID PRIMARY KEY, tenant_id UUID NOT NULL, facility_id UUID, presentation_window_minutes INTEGER NOT NULL)'))
        await conn.execute(text(f'INSERT INTO "{schema}".patient_route_configurations (id, tenant_id, presentation_window_minutes) VALUES (:id, :tenant, 0)'), {"id": uuid.uuid4(), "tenant": uuid.uuid4()})
    with pytest.raises(RuntimeError, match="positive_window"):
        await _apply(engine, schema)
    await _drop(engine, schema)


@pytest.mark.asyncio(loop_scope="module")
async def test_0092_to_0093_to_0092_to_0093(engine):
    result = _run_alembic("upgrade", "0093")
    assert result.returncode == 0, result.stderr
    result = _run_alembic("downgrade", "0092")
    assert result.returncode == 0, result.stderr
    result = _run_alembic("upgrade", "0093")
    assert result.returncode == 0, result.stderr
    current = _run_alembic("current")
    assert current.returncode == 0 and "0093" in current.stdout and "0094" not in current.stdout
