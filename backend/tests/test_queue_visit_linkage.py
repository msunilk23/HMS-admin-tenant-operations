"""
Phase 4 regression tests — QueueToken/Visit must resolve encounters via visit_id,
not patient_id + today's date, since a patient can have multiple same-day visits.
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

from app.api.v1.lab import list_lab_orders
from app.api.v1.queue import cancel_token
from app.api.v1.visits import _complete_queue_token, list_visits
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.lab_order import LabOrder, LabResult
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.queue import CancelTokenRequest

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "receptionist"}

# Only create the tables these tests touch. Base.metadata is a process-wide
# singleton shared with app.models.public (schema="public" tables), which
# aiosqlite cannot create — other test modules importing those models earlier
# in the same pytest session would otherwise break this fixture.
_TABLES = [
    Patient.__table__,
    Visit.__table__,
    QueueToken.__table__,
    LabOrder.__table__,
    LabResult.__table__,
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


def _make_visit(patient: Patient, status: str = VisitStatus.REGISTERED.value, **overrides) -> Visit:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        status=status,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Visit(**defaults)


def _make_token(patient: Patient, visit, token_no: int, issued_at: datetime, **overrides) -> QueueToken:
    defaults = dict(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        visit_id=visit.id if visit else None,
        token_no=token_no,
        queue_type="consultation",
        priority="normal",
        status="checked_in",
        issued_at=issued_at,
    )
    defaults.update(overrides)
    return QueueToken(**defaults)


@pytest.mark.asyncio
async def test_same_day_visits_get_independent_tokens_and_numbers(session):
    patient = _make_patient()
    morning = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    afternoon = morning.replace(hour=15)

    visit_a = _make_visit(patient)
    visit_b = _make_visit(patient)
    token_a = _make_token(patient, visit_a, token_no=1, issued_at=morning, priority="emergency")
    token_b = _make_token(patient, visit_b, token_no=2, issued_at=afternoon, priority="normal")

    session.add_all([patient, visit_a, visit_b, token_a, token_b])
    await session.commit()

    results = await list_visits(
        patient_id=None,
        status_filter=None,
        department_id=None,
        open_only=False,
        session=session,
        current_user=CURRENT_USER,
    )
    by_id = {r.id: r for r in results}

    assert by_id[visit_a.id].token_no == 1
    assert by_id[visit_a.id].priority == "emergency"
    assert by_id[visit_b.id].token_no == 2
    assert by_id[visit_b.id].priority == "normal"


@pytest.mark.asyncio
async def test_completing_visit_a_does_not_complete_visit_b_token(session):
    patient = _make_patient()
    now = datetime.now(timezone.utc)
    visit_a = _make_visit(patient)
    visit_b = _make_visit(patient)
    token_a = _make_token(patient, visit_a, token_no=1, issued_at=now)
    token_b = _make_token(patient, visit_b, token_no=2, issued_at=now)
    session.add_all([patient, visit_a, visit_b, token_a, token_b])
    await session.commit()

    await _complete_queue_token(visit_a, session)
    await session.commit()

    assert token_a.status == "completed"
    assert token_b.status == "checked_in"


@pytest.mark.asyncio
async def test_cancelling_one_visit_does_not_touch_the_others_same_day_visit(session):
    """P1: 09:00 -> V1/T1, 15:00 -> V2/T2. Cancel V2 only; V1/T1 must stay untouched."""
    patient = _make_patient()
    morning = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    afternoon = morning.replace(hour=15)

    visit_1 = _make_visit(patient)
    visit_2 = _make_visit(patient)
    token_1 = _make_token(patient, visit_1, token_no=1, issued_at=morning)
    token_2 = _make_token(patient, visit_2, token_no=2, issued_at=afternoon)
    session.add_all([patient, visit_1, visit_2, token_1, token_2])
    await session.commit()

    await cancel_token(token_2.id, CancelTokenRequest(notes="patient left"), session, CURRENT_USER)

    await session.refresh(visit_1)
    await session.refresh(visit_2)

    assert visit_1.status == VisitStatus.REGISTERED.value
    assert token_1.status == "checked_in"
    assert visit_2.status == VisitStatus.CANCELLED.value
    assert token_2.status == "cancelled"


@pytest.mark.asyncio
async def test_legacy_token_without_visit_id_falls_back_to_patient_and_date(session):
    patient = _make_patient()
    now = datetime.now(timezone.utc)
    visit = _make_visit(patient)
    legacy_token = _make_token(patient, visit=None, token_no=1, issued_at=now)
    session.add_all([patient, visit, legacy_token])
    await session.commit()

    await _complete_queue_token(visit, session)
    await session.commit()

    assert legacy_token.status == "completed"


@pytest.mark.asyncio
async def test_visit_id_linked_token_never_falls_back_to_an_unrelated_legacy_token(session):
    patient = _make_patient()
    now = datetime.now(timezone.utc)
    visit_a = _make_visit(patient)
    token_a = _make_token(patient, visit_a, token_no=1, issued_at=now)
    # Unrelated legacy token for the same patient/day, no visit_id link.
    legacy_token = _make_token(patient, visit=None, token_no=2, issued_at=now)
    session.add_all([patient, visit_a, token_a, legacy_token])
    await session.commit()

    await _complete_queue_token(visit_a, session)
    await session.commit()

    assert token_a.status == "completed"
    assert legacy_token.status == "checked_in"


@pytest.mark.asyncio
async def test_lab_technician_sees_orders_regardless_of_canonical_visit_status(session):
    patient = _make_patient()
    visit = _make_visit(patient, status=VisitStatus.CONSULTATION_COMPLETED.value)
    ordered = LabOrder(id=uuid.uuid4(), visit_id=visit.id, uhid=patient.uhid, tests=[{"test": "CBC"}], status="ordered")
    resulted = LabOrder(id=uuid.uuid4(), visit_id=visit.id, uhid=patient.uhid, tests=[{"test": "LFT"}], status="resulted")
    session.add_all([patient, visit, ordered, resulted])
    await session.commit()

    lab_tech_user = {"role": "lab_technician", "sub": str(uuid.uuid4()), "tenant_schema": "test_tenant"}
    results = await list_lab_orders(status_filter=None, session=session, current_user=lab_tech_user)
    ids = {r.id for r in results}

    assert ordered.id in ids
    assert resulted.id not in ids
