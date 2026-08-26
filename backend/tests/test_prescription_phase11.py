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

from app.api.v1.prescriptions import create_prescription
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.consultation import Consultation
from app.models.tenant.doctor import Doctor
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.prescription import PrescriptionCreate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "doctor"}

_TABLES = [
    Patient.__table__,
    Doctor.__table__,
    Visit.__table__,
    Consultation.__table__,
    Prescription.__table__,
    PrescriptionItem.__table__,
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
async def test_prescription_requires_structured_items_and_visit_links(session):
    doctor_user_id = uuid.uuid4()
    doctor = _make_doctor(user_id=doctor_user_id)
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.IN_CONSULTATION.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    consultation = Consultation(
        id=uuid.uuid4(),
        visit_id=visit.id,
        uhid=patient.uhid,
        status="completed",
        chief_complaint="Fever",
        notes="Routine follow-up",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([doctor, patient, visit, consultation])
    await session.commit()

    prescription = await create_prescription(
        payload=PrescriptionCreate(
            visit_id=visit.id,
            consultation_id=consultation.id,
            items=[{
                "medicine": "Paracetamol",
                "is_free_text": True,
                "free_text_reason": "No active formulary product was available in this test fixture",
                "strength": "500mg",
                "dose": "1 tablet",
                "route": "oral",
                "frequency": "BD",
                "duration": "5 days",
                "quantity": "10",
                "instructions": "After food",
            }],
            instructions="Take as directed",
        ),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
    )

    assert prescription.consultation_id == consultation.id
    assert prescription.doctor_id == doctor.id
    assert len(prescription.items) == 1
    assert prescription.items[0].medicine == "Paracetamol"
    assert prescription.items[0].frequency == "BD"
