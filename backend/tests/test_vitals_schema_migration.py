"""Real PostgreSQL checks for the expanded vitals migration contract."""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital")

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.vitals import record_vitals
from app.db.base import Base
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.vitals import Vitals
from app.schemas.vitals import VitalsCreate

PG_URL = os.environ["DATABASE_URL"]
BACKEND_DIR = Path(__file__).resolve().parents[1]


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


def _upgrade_head() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": PG_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic upgrade failed:\n{result.stdout}\n{result.stderr}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrated_tenant():
    schema = f"test_vitals_schema_{uuid.uuid4().hex[:10]}"
    tenant_id = uuid.uuid4()
    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text("""
            INSERT INTO public.tenants
                (id, schema_name, hospital_name, contact_email, is_active, timezone, display_token)
            VALUES (:id, :schema, 'Vitals Migration Test', :email, true, 'Asia/Kolkata', :token)
        """), {"id": tenant_id, "schema": schema, "email": f"{schema}@example.test", "token": uuid.uuid4().hex})
    _upgrade_head()
    yield schema, tenant_id, engine
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_migrated_vitals_matches_model_and_unique_constraint(migrated_tenant):
    schema, _, engine = migrated_tenant
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        columns = {item["name"]: item for item in await conn.run_sync(lambda c: inspect(c).get_columns("vitals"))}
        model_columns = {item.name: item for item in Vitals.__table__.columns}
        assert set(model_columns).issubset(columns)
        def normalized_type(column_type):
            rendered = str(column_type).lower()
            if "double precision" in rendered or rendered == "float":
                return "double precision"
            return rendered

        for name in ("temperature", "respiratory_rate", "bmi", "blood_glucose"):
            assert normalized_type(columns[name]["type"]) == normalized_type(model_columns[name].type)
        constraints = await conn.run_sync(lambda c: inspect(c).get_unique_constraints("vitals"))
        assert any(item["name"] == "uq_vitals_visit_id" for item in constraints)
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("vitals"))
        assert any("visit_id" in item["column_names"] for item in indexes)


@pytest.mark.asyncio(loop_scope="module")
async def test_legacy_vitals_schema_is_expanded_and_can_complete(migrated_tenant):
    schema, tenant_id, engine = migrated_tenant
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        await conn.execute(text(f'DROP TABLE "{schema}".vitals CASCADE'))
        await conn.execute(text(f"""
            CREATE TABLE "{schema}".vitals (
                id UUID PRIMARY KEY, visit_id UUID NOT NULL, bp_systolic INTEGER,
                bp_diastolic INTEGER, temperature DOUBLE PRECISION, weight DOUBLE PRECISION,
                height DOUBLE PRECISION, spo2 INTEGER, pulse INTEGER,
                recorded_by_user_id UUID NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text(f'INSERT INTO "{schema}".vitals (id, visit_id, temperature, recorded_by_user_id) VALUES (:id, :visit, 36.7, :user)'), {"id": uuid.uuid4(), "visit": uuid.uuid4(), "user": uuid.uuid4()})
        await conn.execute(text(f'UPDATE "{schema}".alembic_version SET version_num = \'0046_schedule_audit_action\''))
    _upgrade_head()
    async with maker() as session:
        await session.execute(text(f'SET search_path TO "{schema}", public'))
        department = Department(id=uuid.uuid4(), name="Migration Dept", is_active=True)
        doctor = Doctor(id=uuid.uuid4(), user_id=uuid.uuid4(), full_name="Migration Doctor", specialization="General", department_id=department.id, is_active=True)
        patient = Patient(id=uuid.uuid4(), uhid="MIGRATION-PATIENT", first_name="Legacy", last_name="Patient", gender="female", phone="9000000000")
        visit = Visit(id=uuid.uuid4(), facility_id=tenant_id, patient_id=patient.id, uhid=patient.uhid, doctor_id=doctor.id, department_id=department.id, status=VisitStatus.IN_PRE_VITAL.value, registered_at=datetime.now(timezone.utc))
        session.add_all([department, doctor, patient, visit])
        await session.commit()
        payload = VitalsCreate(
            visit_id=visit.id, bp_systolic=120, bp_diastolic=80, temperature=36.7,
            weight=70, height=170, spo2=98, pulse=72, respiratory_rate=18,
            pain_score=0, blood_glucose=96, chief_complaint="Fever", allergies="None",
            known_no_allergies=True, general_condition="Stable", level_of_consciousness="Alert",
            nurse_notes="Fever", status="completed",
        )
        await record_vitals(payload, session=session, current_user={"sub": str(doctor.user_id), "role": "nurse", "tenant_schema": schema})
        rows = (await session.execute(text("SELECT COUNT(*) FROM vitals WHERE visit_id = :id"), {"id": visit.id})).scalar_one()
        row = (await session.execute(text("SELECT temperature, bmi, status, uhid FROM vitals WHERE visit_id = :id"), {"id": visit.id})).one()
        assert rows == 1
        assert float(row.temperature) == pytest.approx(36.7)
        assert float(row.bmi) == pytest.approx(24.2, abs=0.1)
        assert row.status == "completed"
        assert row.uhid == patient.uhid
        assert visit.status == VisitStatus.WAITING_FOR_DOCTOR.value
