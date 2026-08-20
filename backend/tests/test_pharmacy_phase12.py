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

from app.api.v1.pharmacy import update_pharmacy_status
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.doctor import Doctor
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.pharmacy import PharmacyStatusUpdate

_TABLES = [
    Patient.__table__,
    Doctor.__table__,
    Visit.__table__,
    Prescription.__table__,
    PharmacyQueue.__table__,
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
async def test_pharmacy_queue_progress_is_independent_from_visit_state(session):
    doctor_user_id = uuid.uuid4()
    doctor = _make_doctor(user_id=doctor_user_id)
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.CONSULTATION_COMPLETED.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    prescription = Prescription(
        id=uuid.uuid4(),
        visit_id=visit.id,
        uhid=patient.uhid,
        medicines=[{"medicine": "Paracetamol", "dose": "1 tablet"}],
        instructions="Take as directed",
        status="finalized",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    queue = PharmacyQueue(
        id=uuid.uuid4(),
        prescription_id=prescription.id,
        uhid=patient.uhid,
        status="pending",
    )
    session.add_all([doctor, patient, visit, prescription, queue])
    await session.commit()

    called = await update_pharmacy_status(
        queue.id,
        PharmacyStatusUpdate(status="called", notes="Patient called to pharmacy"),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "pharmacist", "tenant_schema": "test_tenant"},
    )
    await session.refresh(visit)
    assert called.status == "called"
    assert visit.status == VisitStatus.CONSULTATION_COMPLETED.value

    dispensing = await update_pharmacy_status(
        queue.id,
        PharmacyStatusUpdate(status="dispensing", notes="Preparing medication"),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "pharmacist", "tenant_schema": "test_tenant"},
    )
    await session.refresh(visit)
    assert dispensing.status == "dispensing"
    assert visit.status == VisitStatus.CONSULTATION_COMPLETED.value

    dispensed = await update_pharmacy_status(
        queue.id,
        PharmacyStatusUpdate(status="dispensed", notes="Given to patient"),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "pharmacist", "tenant_schema": "test_tenant"},
    )
    await session.refresh(visit)
    assert dispensed.status == "dispensed"
    assert visit.status == VisitStatus.CONSULTATION_COMPLETED.value
