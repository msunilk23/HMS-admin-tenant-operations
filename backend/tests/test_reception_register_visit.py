"""
Phase 5 regression tests — Reception "Register Visit" workflow (Walk-In and
Appointment check-in) must land the visit at WAITING_FOR_NURSE, never further.
"""
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

# sqlite has no native JSONB type; a couple of unrelated tenant columns use it,
# so map it to plain JSON for the in-memory test database.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"

from app.api.v1.appointments import checkin_appointment
from app.api.v1.queue import issue_token
from app.db.base import Base
from app.models.tenant.appointment import Appointment
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.doctor import Doctor
from app.models.tenant.invoice import Invoice
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.token_counter import TokenCounter
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.appointment import CheckInBody
from app.schemas.queue import QueueTokenCreate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "receptionist"}

_TABLES = [
    Patient.__table__,
    Doctor.__table__,
    Appointment.__table__,
    Visit.__table__,
    QueueToken.__table__,
    TokenCounter.__table__,
    Invoice.__table__,
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


def _make_doctor(**overrides) -> Doctor:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        full_name="House",
        specialization="General Medicine",
        consultation_fee=0.0,  # keep billing/Razorpay out of scope for this test
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Doctor(**defaults)


@pytest.mark.asyncio
async def test_walk_in_registration_lands_visit_at_waiting_for_nurse(session):
    patient = _make_patient()
    doctor = _make_doctor()
    session.add_all([patient, doctor])
    await session.commit()

    token = await issue_token(
        QueueTokenCreate(patient_id=patient.id, doctor_id=doctor.id, queue_type="consultation"),
        session=session,
        current_user=CURRENT_USER,
    )

    visit = await session.get(Visit, token.visit_id)
    assert visit.status == VisitStatus.WAITING_FOR_NURSE.value


@pytest.mark.asyncio
async def test_appointment_checkin_lands_visit_at_waiting_for_nurse(session):
    patient = _make_patient()
    doctor = _make_doctor()
    now = datetime.now(timezone.utc)
    appt = Appointment(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        slot_time=now,
        status="scheduled",
        type="phone",
        created_at=now,
        updated_at=now,
    )
    session.add_all([patient, doctor, appt])
    await session.commit()

    result = await checkin_appointment(
        appt.id,
        CheckInBody(waive_fee=False),
        session=session,
        current_user=CURRENT_USER,
    )

    visit = await session.get(Visit, result.visit_id)
    assert visit.status == VisitStatus.WAITING_FOR_NURSE.value
    assert visit.appointment_id == appt.id
