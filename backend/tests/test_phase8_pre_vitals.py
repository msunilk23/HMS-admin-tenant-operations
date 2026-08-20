import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"

from app.api.v1.vitals import record_vitals
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.patient import Patient
from app.models.tenant.vitals import Vitals
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.vitals import VitalsCreate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "nurse"}

_TABLES = [
    Patient.__table__,
    Visit.__table__,
    Vitals.__table__,
    AuditLog.__table__,
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
        id=uuid.uuid4(),
        uhid=f"UHID{uuid.uuid4().hex[:8].upper()}",
        first_name="Test",
        last_name="Patient",
        gender="female",
        phone="9999999999",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Patient(**defaults)


@pytest.mark.asyncio
async def test_pre_vitals_supports_complete_clinical_fields_and_moves_to_doctor_queue(session):
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        status=VisitStatus.IN_PRE_VITAL.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([patient, visit])
    await session.commit()

    response = await record_vitals(
        VitalsCreate(
            visit_id=visit.id,
            temperature=98.6,
            pulse=72,
            respiratory_rate=18,
            bp_systolic=120,
            bp_diastolic=80,
            spo2=99,
            pain_score=2,
            height=170,
            weight=70,
            blood_glucose=96,
            chief_complaint="Fever and cough",
            allergies="Penicillin",
            known_no_allergies=False,
            general_condition="Stable",
            level_of_consciousness="Alert and oriented",
            nurse_notes="Patient is stable and afebrile after medication.",
            status="completed",
        ),
        session=session,
        current_user=CURRENT_USER,
    )

    await session.refresh(visit)
    assert response.status == "completed"
    assert response.blood_glucose == 96
    assert response.respiratory_rate == 18
    assert response.pain_score == 2
    assert visit.status == VisitStatus.WAITING_FOR_DOCTOR.value


@pytest.mark.asyncio
async def test_pre_vitals_draft_is_saved_without_moving_to_doctor_queue(session):
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        status=VisitStatus.IN_PRE_VITAL.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([patient, visit])
    await session.commit()

    response = await record_vitals(
        VitalsCreate(
            visit_id=visit.id,
            temperature=99.1,
            pulse=74,
            respiratory_rate=20,
            bp_systolic=118,
            bp_diastolic=76,
            spo2=98,
            pain_score=1,
            height=168,
            weight=65,
            blood_glucose=94,
            chief_complaint="Headache",
            allergies="None",
            known_no_allergies=True,
            general_condition="Stable",
            level_of_consciousness="Alert",
            nurse_notes="Draft noted.",
            status="draft",
        ),
        session=session,
        current_user=CURRENT_USER,
    )

    await session.refresh(visit)
    assert response.status == "draft"
    assert visit.status == VisitStatus.IN_PRE_VITAL.value
