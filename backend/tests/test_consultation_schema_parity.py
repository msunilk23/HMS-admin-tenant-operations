"""Real PostgreSQL schema parity checks for critical consultation/vitals tables."""
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.tenant.consultation import Consultation
from app.models.tenant.vitals import Vitals

PG_URL = os.environ["DATABASE_URL"]
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _reachable() -> bool:
    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="PostgreSQL is not reachable")


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": PG_URL},
        capture_output=True,
        text=True,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def tenant_schema():
    schema = f"test_consultation_parity_{uuid.uuid4().hex[:10]}"
    tenant_id = uuid.uuid4()
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text("""
            INSERT INTO public.tenants
                (id, schema_name, hospital_name, contact_email, is_active, timezone, display_token)
            VALUES (:id, :schema, 'Consultation Parity', :email, true, 'Asia/Kolkata', :token)
        """), {"id": tenant_id, "schema": schema, "email": f"{schema}@example.test", "token": uuid.uuid4().hex})
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, f"Alembic upgrade failed:\n{result.stdout}\n{result.stderr}"
    yield schema, engine
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await engine.dispose()


def _normal_type(value) -> str:
    rendered = str(value).lower()
    if "timestamp" in rendered:
        return "datetime"
    if "datetime" in rendered:
        return "datetime"
    if "double precision" in rendered or rendered == "float":
        return "double"
    if "json" in rendered:
        return "json"
    if "character varying" in rendered or "varchar" in rendered:
        return "varchar"
    if "text" in rendered:
        return "text"
    if "char(32)" in rendered:
        return "uuid"
    if "integer" in rendered:
        return "integer"
    return rendered


@pytest.mark.asyncio(loop_scope="module")
async def test_consultation_and_vitals_models_match_alembic_schema(tenant_schema):
    schema, engine = tenant_schema
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        for model in (Consultation, Vitals):
            actual = {item["name"]: item for item in await conn.run_sync(lambda sync: inspect(sync).get_columns(model.__tablename__))}
            expected = {column.name: column for column in model.__table__.columns}
            assert set(expected).issubset(actual), f"Missing {model.__tablename__} columns: {set(expected) - set(actual)}"
            for name, column in expected.items():
                assert _normal_type(actual[name]["type"]) == _normal_type(column.type), f"Type mismatch {model.__tablename__}.{name}"
        for table_name in ("consultations", "vitals"):
            constraints = await conn.run_sync(lambda sync: inspect(sync).get_unique_constraints(table_name))
            indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes(table_name))
            assert any("visit_id" in item["column_names"] for item in constraints), f"Missing unique visit_id on {table_name}"
            assert any("visit_id" in item["column_names"] for item in indexes), f"Missing visit_id index on {table_name}"


@pytest.mark.asyncio(loop_scope="module")
async def test_consultation_lifecycle_columns_backfill_from_visit_state(tenant_schema):
    schema, engine = tenant_schema
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        await conn.execute(text("ALTER TABLE consultations DROP COLUMN status, DROP COLUMN started_at, DROP COLUMN completed_at, DROP COLUMN amended_at"))
        await conn.execute(text("""
            INSERT INTO departments (id, name, is_active) VALUES (:department, 'Parity', true)
        """), {"department": uuid.uuid4()})
        department_id = (await conn.execute(text("SELECT id FROM departments LIMIT 1"))).scalar_one()
        patient_id = uuid.uuid4()
        doctor_id = uuid.uuid4()
        visit_id = uuid.uuid4()
        await conn.execute(text("""
            INSERT INTO patients (id, uhid, first_name, last_name, gender, phone)
            VALUES (:patient, 'PARITY-1', 'Parity', 'Patient', 'female', '9000000000')
        """), {"patient": patient_id})
        facility_id = (await conn.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :schema"),
            {"schema": schema},
        )).scalar_one()
        await conn.execute(text("""
            INSERT INTO doctors (id, user_id, full_name, specialization, department_id, is_active)
            VALUES (:doctor, :user, 'Parity Doctor', 'General', :department, true)
        """), {"doctor": doctor_id, "user": uuid.uuid4(), "department": department_id})
        await conn.execute(text("""
            INSERT INTO visits (id, facility_id, patient_id, uhid, doctor_id, department_id, status)
            VALUES (:visit, :facility, :patient, 'PARITY-1', :doctor, :department, 'CONSULTATION_COMPLETED')
        """), {"visit": visit_id, "facility": facility_id, "patient": patient_id, "doctor": doctor_id, "department": department_id})
        await conn.execute(text("""
            INSERT INTO consultations (id, visit_id, uhid, chief_complaint)
            VALUES (:consultation, :visit, 'PARITY-1', 'Legacy consultation')
        """), {"consultation": uuid.uuid4(), "visit": visit_id})
        await conn.execute(text("UPDATE alembic_version SET version_num = '0048_expand_vitals_schema'"))
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, f"Alembic lifecycle upgrade failed:\n{result.stdout}\n{result.stderr}"
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        row = (await conn.execute(text("SELECT status, started_at, completed_at FROM consultations WHERE visit_id = :visit"), {"visit": visit_id})).one()
        assert row.status == "completed"
        assert row.started_at is not None
        assert row.completed_at is not None
