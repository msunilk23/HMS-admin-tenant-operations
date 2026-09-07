import os
import uuid
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"

from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.consultation import Consultation
from app.models.tenant.doctor import Doctor
from app.models.tenant.document import DocumentVersion, DocumentVersionCounter
from app.models.tenant.document_request import PrescriptionDocumentRequest
from app.models.tenant.invoice import Invoice
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.patient_route import PatientRoute, PatientRouteConfiguration, PatientRouteEvent, PatientRouteStep
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.services.consultation_completion import complete_consultation
from app.services.patient_routing import expire_steps, present_step, transition_service_step

_TABLES = [
    Patient.__table__, Doctor.__table__, Visit.__table__, Consultation.__table__,
    Prescription.__table__, PrescriptionItem.__table__, LabOrder.__table__, Invoice.__table__,
    QueueToken.__table__, PharmacyQueue.__table__, AuditLog.__table__,
    PatientRouteConfiguration.__table__, PatientRoute.__table__, PatientRouteStep.__table__,
    PatientRouteEvent.__table__, PrescriptionDocumentRequest.__table__,
    DocumentVersion.__table__, DocumentVersionCounter.__table__,
]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as value:
        yield value
    await engine.dispose()


def _user(role="doctor"):
    return {"sub": str(uuid.uuid4()), "role": role, "tenant_id": str(uuid.uuid4()), "tenant_schema": "test_tenant"}


async def _fixture(session, *, medicines=False, lab=False, invoice=False):
    doctor_user = uuid.uuid4()
    doctor = Doctor(id=uuid.uuid4(), user_id=doctor_user, full_name="Dr. PF1", specialization="General", consultation_fee=0, qualification="MBBS", experience_years=5, is_active=True)
    patient = Patient(id=uuid.uuid4(), uhid="PF1-0001", first_name="PF", last_name="Patient", gender="female", phone="9999999999")
    visit = Visit(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, doctor_id=doctor.id, facility_id=uuid.uuid4(), status=VisitStatus.IN_CONSULTATION.value)
    consultation = Consultation(id=uuid.uuid4(), visit_id=visit.id, uhid=patient.uhid, status="completed", completed_at=datetime.now(timezone.utc))
    token = QueueToken(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, visit_id=visit.id, token_no=1, token_scope="queue:test", token_date=date.today(), queue_type="consultation", status="checked_in")
    session.add_all([doctor, patient, visit, consultation, token])
    if medicines:
        session.add(Prescription(id=uuid.uuid4(), visit_id=visit.id, consultation_id=consultation.id, doctor_id=doctor.id, uhid=patient.uhid, status="finalized", medicines=[{"medicine": "Drug", "dose": "1"}], instructions="daily"))
    if lab:
        session.add(LabOrder(id=uuid.uuid4(), visit_id=visit.id, facility_id=visit.facility_id, uhid=patient.uhid, tests=[{"test": "CBC"}], status="ordered"))
    if invoice:
        session.add(Invoice(id=uuid.uuid4(), visit_id=visit.id, uhid=patient.uhid, total=100, paid_amount=0, status="pending"))
    await session.commit()
    return doctor_user, visit, consultation


@pytest.mark.asyncio
async def test_completion_derives_independent_routes_and_closes_opd(session):
    doctor_user, visit, consultation = await _fixture(session, medicines=True, lab=True, invoice=True)
    user = {"sub": str(doctor_user), "role": "doctor", "tenant_id": str(uuid.uuid4()), "facility_id": str(visit.facility_id), "tenant_schema": "test_tenant"}
    completed, route = await complete_consultation(session, visit.id, user, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    await session.commit()
    steps = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id))).scalars().all()
    assert completed.status == VisitStatus.CLOSED.value
    assert {step.destination for step in steps} == {"PHARMACY", "LAB", "BILLING"}
    assert all(step.status == "AWAITING_PATIENT" for step in steps)


@pytest.mark.asyncio
async def test_presentation_activates_only_requested_destination(session):
    doctor_user, visit, consultation = await _fixture(session, medicines=True, lab=True)
    user = _user("nurse")
    user["facility_id"] = str(visit.facility_id)
    _, route = await complete_consultation(session, visit.id, {"sub": str(doctor_user), "role": "doctor", "tenant_id": user["tenant_id"], "facility_id": user["facility_id"], "tenant_schema": "test_tenant"})
    await session.commit()
    pharmacy = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id, PatientRouteStep.destination == "PHARMACY"))).scalar_one()
    lab = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id, PatientRouteStep.destination == "LAB"))).scalar_one()
    await present_step(session, pharmacy.id, user, channel="RECEPTION")
    await session.commit()
    queue = (await session.execute(select(PharmacyQueue))).scalar_one()
    assert queue.status == "pending"
    assert (await session.get(LabOrder, lab.source_record_id)).status == "ordered"


@pytest.mark.asyncio
async def test_expiry_is_explicit_and_late_presentation_does_not_cancel_source(session):
    _, visit, _ = await _fixture(session, medicines=True)
    user = _user("hospital_admin")
    user["facility_id"] = str(visit.facility_id)
    _, route = await complete_consultation(session, visit.id, user, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    await session.commit()
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id, PatientRouteStep.destination == "PHARMACY"))).scalar_one()
    count = await expire_steps(session, user, now=step.presentation_deadline_at + timedelta(seconds=1))
    await session.commit()
    assert count == 1
    assert step.status == "NOT_PRESENTED"
    presented = await present_step(session, step.id, user, channel="RECEPTION", now=step.presentation_deadline_at + timedelta(hours=1))
    assert presented.status == "PRESENTED_LATE"


@pytest.mark.asyncio
async def test_invalid_service_transition_is_rejected(session):
    _, visit, _ = await _fixture(session, medicines=True)
    user = _user("hospital_admin")
    user["facility_id"] = str(visit.facility_id)
    _, route = await complete_consultation(session, visit.id, user)
    await session.commit()
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id))).scalar_one()
    with pytest.raises(Exception, match="authorized|Cannot transition"):
        await transition_service_step(session, step.id, "COMPLETED", user)