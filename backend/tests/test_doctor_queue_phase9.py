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

from app.api.v1.consultations import create_consultation
from app.api.v1.visits import list_visits
from app.db.base import Base
from app.models.tenant.consultation import Consultation
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "doctor"}

_TABLES = [
    Patient.__table__,
    Department.__table__,
    Doctor.__table__,
    Visit.__table__,
    QueueToken.__table__,
    LabOrder.__table__,
    Consultation.__table__,
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


def _make_patient(**overrides):
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


def _make_doctor(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        full_name="Dr. Test",
        specialization="General Medicine",
        consultation_fee=500.00,
        qualification="MBBS",
        experience_years=10,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Doctor(**defaults)


@pytest.mark.asyncio
async def test_doctor_queue_lists_only_waiting_for_doctor_visits(session):
    doctor_user_id = uuid.uuid4()
    doctor = _make_doctor(user_id=doctor_user_id)
    other_doctor = _make_doctor(user_id=uuid.uuid4(), full_name="Dr. Other")
    patient_1 = _make_patient()
    patient_2 = _make_patient()
    patient_3 = _make_patient()
    visit_waiting = Visit(
        id=uuid.uuid4(),
        patient_id=patient_1.id,
        uhid=patient_1.uhid,
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.WAITING_FOR_DOCTOR.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    visit_in_vitals = Visit(
        id=uuid.uuid4(),
        patient_id=patient_2.id,
        uhid=patient_2.uhid,
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.IN_PRE_VITAL.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    visit_other_doctor = Visit(
        id=uuid.uuid4(),
        patient_id=patient_3.id,
        uhid=patient_3.uhid,
        doctor_id=other_doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.WAITING_FOR_DOCTOR.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([doctor, other_doctor, patient_1, patient_2, patient_3, visit_waiting, visit_in_vitals, visit_other_doctor])
    await session.commit()

    items = await list_visits(
        None,
        None,
        None,
        False,
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
    )

    assert [item.id for item in items] == [visit_waiting.id]


@pytest.mark.asyncio
async def test_doctor_cannot_open_consultation_outside_waiting_for_doctor_queue(session):
    doctor_user_id = uuid.uuid4()
    doctor = _make_doctor(user_id=doctor_user_id)
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.IN_PRE_VITAL.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([doctor, patient, visit])
    await session.commit()

    with pytest.raises(Exception):
        await create_consultation(
            payload={"visit_id": visit.id, "chief_complaint": "Fever"},
            session=session,
            current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
        )
