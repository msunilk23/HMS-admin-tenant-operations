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

from app.api.v1.consultations import create_consultation, update_consultation
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.consultation import Consultation
from app.models.tenant.doctor import Doctor
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.icd10_code import ICD10Code
from app.schemas.consultation import ConsultationCreate, ConsultationUpdate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "doctor"}

_TABLES = [
    Patient.__table__,
    Doctor.__table__,
    Visit.__table__,
    Consultation.__table__,
    AuditLog.__table__,
    ICD10Code.__table__,
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
async def test_consultation_can_be_saved_as_draft_in_doctor_queue(session):
    doctor_user_id = uuid.uuid4()
    doctor = _make_doctor(user_id=doctor_user_id)
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        status=VisitStatus.WAITING_FOR_DOCTOR.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([doctor, patient, visit])
    await session.commit()

    response = await create_consultation(
        payload=ConsultationCreate(
            visit_id=visit.id,
            chief_complaint="Fever",
            history="Started 2 days ago",
            status="draft",
        ),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
    )

    await session.refresh(visit)
    assert response.status == "draft"
    assert visit.status == VisitStatus.IN_CONSULTATION.value


@pytest.mark.asyncio
async def test_consultation_completion_moves_visit_to_consultation_completed(session):
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
    icd = ICD10Code(id=uuid.uuid4(), code="J06.9", description="Acute URI", is_active=True)
    session.add_all([doctor, patient, visit, icd])
    await session.commit()

    response = await create_consultation(
        payload=ConsultationCreate(
            visit_id=visit.id,
            chief_complaint="Dry cough",
            diagnosis_icd10=[{"code": "J06.9", "description": "Acute URI", "master_id": icd.id}],
            status="completed",
        ),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
    )

    await session.refresh(visit)
    assert response.status == "completed"
    assert visit.status == VisitStatus.CONSULTATION_COMPLETED.value


@pytest.mark.asyncio
async def test_completed_consultations_require_explicit_amendment(session):
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
    session.add_all([doctor, patient, visit])
    await session.commit()

    completed = await create_consultation(
        payload=ConsultationCreate(
            visit_id=visit.id,
            chief_complaint="Back pain",
            status="completed",
        ),
        session=session,
        current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
    )

    with pytest.raises(Exception):
        await update_consultation(
            visit.id,
            ConsultationUpdate(notes="silent overwrite"),
            session=session,
            current_user={"sub": str(doctor_user_id), "role": "doctor", "tenant_schema": "test_tenant"},
        )

    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_free_text_diagnosis_requires_reason(session):
    with pytest.raises(Exception, match="clinical reason"):
        ConsultationCreate(
            visit_id=uuid.uuid4(),
            chief_complaint="Fever",
            diagnosis_icd10=[{"description": "Unusual syndrome", "free_text": True}],
            status="draft",
        )


@pytest.mark.asyncio
async def test_consultation_diagnosis_schema_rejects_unknown_fields():
    with pytest.raises(Exception):
        ConsultationCreate(
            visit_id=uuid.uuid4(),
            chief_complaint="Fever",
            diagnosis_icd10=[{"code": "J06.9", "description": "URI", "unexpected": "value"}],
        )


@pytest.mark.asyncio
async def test_diagnosis_schema_enforces_controlled_and_free_text_contracts():
    with pytest.raises(Exception, match="master_id"):
        ConsultationCreate(
            visit_id=uuid.uuid4(),
            diagnosis_icd10=[{"code": "J06.9", "description": "URI"}],
        )
    with pytest.raises(Exception):
        ConsultationCreate(
            visit_id=uuid.uuid4(),
            diagnosis_icd10=[{"code": "", "master_id": "", "description": "Free text", "free_text": True}],
            free_text_diagnosis_reason="No suitable ICD-10 code",
        )
    payload = ConsultationCreate(
        visit_id=uuid.uuid4(),
        diagnosis_icd10=[{"description": "Unusual syndrome", "free_text": True}],
        free_text_diagnosis_reason="No suitable ICD-10 code",
    )
    assert payload.diagnosis_icd10[0].code is None
    assert payload.diagnosis_icd10[0].master_id is None
