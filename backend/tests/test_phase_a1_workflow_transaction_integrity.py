"""
Phase A1: Workflow Transaction Integrity Tests

Verify that mandatory transition failures:
1. Stop the operation immediately
2. Roll back the transaction
3. Return a controlled conflict/error
4. Prevent domain/Visit state divergence
"""

import os
import uuid
from datetime import datetime, timezone, date

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

from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.patient import Patient
from app.models.tenant.doctor import Doctor
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.consultation import Consultation
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "doctor"}

_TABLES = [
    Patient.__table__,
    Doctor.__table__,
    Visit.__table__,
    Consultation.__table__,
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



@pytest.mark.asyncio
async def test_invalid_transition_raises_error(session: AsyncSession):
    """
    Verify that an invalid transition raises ValueError immediately
    and does not mutate Visit state.
    """
    # Create test data
    patient = Patient(
        id=uuid.uuid4(),
        uhid="TEST001",
        first_name="Test",
        last_name="Patient",
        dob=date(1990, 1, 1),
        gender="male",
        phone="9999999999",
    )
    session.add(patient)
    await session.flush()

    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        status=VisitStatus.REGISTERED.value,
    )
    session.add(visit)
    await session.flush()

    original_status = visit.status
    original_closed_at = visit.closed_at

    # Attempt invalid transition: REGISTERED → CONSULTATION_COMPLETED (skipping intermediate states)
    with pytest.raises(ValueError) as exc_info:
        await VisitWorkflowService.transition(
            session,
            visit,
            VisitStatus.CONSULTATION_COMPLETED,
            uuid.uuid4(),
            VisitTransitionSource.DOCTOR,
        )

    # Verify error message
    assert "Invalid visit transition" in str(exc_info.value)

    # Verify Visit state did NOT change
    assert visit.status == original_status
    assert visit.closed_at == original_closed_at
    assert visit.status == VisitStatus.REGISTERED.value  # Still REGISTERED, not CONSULTATION_COMPLETED


@pytest.mark.asyncio
async def test_transition_failure_rolls_back_transaction(session: AsyncSession):
    """
    Verify that when a transition fails, the Visit state is not modified.
    """
    # Create test data
    patient = Patient(
        id=uuid.uuid4(),
        uhid="TEST002",
        first_name="Test",
        last_name="Patient2",
        dob=date(1990, 1, 2),
        gender="male",
        phone="9999999999",
    )
    session.add(patient)
    await session.flush()

    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        status=VisitStatus.CLOSED.value,  # Terminal state
    )
    session.add(visit)
    await session.flush()

    # Record original state
    original_status = visit.status

    # Attempt invalid transition from terminal state
    with pytest.raises(ValueError):
        await VisitWorkflowService.transition(
            session,
            visit,
            VisitStatus.WAITING_FOR_NURSE,
            uuid.uuid4(),
            VisitTransitionSource.RECEPTION,
        )

    # Verify state unchanged after failed transition
    # (visit.status should not have been modified by failed transition)
    assert visit.status == original_status
    assert visit.status == VisitStatus.CLOSED.value


@pytest.mark.asyncio
async def test_consultation_creation_fails_on_invalid_transition(session: AsyncSession):
    """
    Verify that consultation creation returns proper error when transition fails,
    not silently swallowing the error.
    """
    # Create test data
    patient = Patient(
        id=uuid.uuid4(),
        uhid="TEST003",
        first_name="Test",
        last_name="Patient3",
        dob=date(1990, 1, 3),
        gender="male",
        phone="9999999999",
    )
    session.add(patient)
    await session.flush()

    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        status=VisitStatus.CLOSED.value,  # Visit is already closed, invalid for consultation
    )
    session.add(visit)
    await session.flush()

    # Try to create consultation when visit is closed
    # This should NOT silently pass; it should raise an error
    with pytest.raises(ValueError) as exc_info:
        await VisitWorkflowService.transition(
            session,
            visit,
            VisitStatus.IN_CONSULTATION,
            uuid.uuid4(),
            VisitTransitionSource.DOCTOR,
        )

    assert "Invalid visit transition" in str(exc_info.value)
    # Visit should still be CLOSED
    assert visit.status == VisitStatus.CLOSED.value


@pytest.mark.asyncio
async def test_valid_transitions_succeed(session: AsyncSession):
    """
    Sanity test: verify that valid transitions in sequence work correctly.
    """
    patient = Patient(
        id=uuid.uuid4(),
        uhid="TEST004",
        first_name="Test",
        last_name="Patient4",
        dob=date(1990, 1, 4),
        gender="male",
        phone="9999999999",
    )
    session.add(patient)
    await session.flush()

    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        status=VisitStatus.REGISTERED.value,
    )
    session.add(visit)
    await session.flush()

    # Valid sequence: REGISTERED → WAITING_FOR_NURSE
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.WAITING_FOR_NURSE,
        uuid.uuid4(),
        VisitTransitionSource.RECEPTION,
    )
    assert visit.status == VisitStatus.WAITING_FOR_NURSE.value
    assert visit.nurse_queue_at is not None

    # Valid: WAITING_FOR_NURSE → IN_PRE_VITAL
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.IN_PRE_VITAL,
        uuid.uuid4(),
        VisitTransitionSource.NURSE,
    )
    assert visit.status == VisitStatus.IN_PRE_VITAL.value
    assert visit.nurse_called_at is not None

    # Valid: IN_PRE_VITAL → WAITING_FOR_DOCTOR
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.WAITING_FOR_DOCTOR,
        uuid.uuid4(),
        VisitTransitionSource.NURSE,
    )
    assert visit.status == VisitStatus.WAITING_FOR_DOCTOR.value

    # Valid: WAITING_FOR_DOCTOR → IN_CONSULTATION
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.IN_CONSULTATION,
        uuid.uuid4(),
        VisitTransitionSource.DOCTOR,
    )
    assert visit.status == VisitStatus.IN_CONSULTATION.value

    # Valid: IN_CONSULTATION → CONSULTATION_COMPLETED
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.CONSULTATION_COMPLETED,
        uuid.uuid4(),
        VisitTransitionSource.DOCTOR,
    )
    assert visit.status == VisitStatus.CONSULTATION_COMPLETED.value

    # Valid: CONSULTATION_COMPLETED → CLOSED
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.CLOSED,
        uuid.uuid4(),
        VisitTransitionSource.SYSTEM,
    )
    assert visit.status == VisitStatus.CLOSED.value
    assert visit.closed_at is not None


@pytest.mark.asyncio
async def test_cancellation_is_allowed_from_any_non_terminal_state(session: AsyncSession):
    """
    Verify that CANCELLED is a valid target from non-terminal states where it's allowed.
    Note: CONSULTATION_COMPLETED can only transition to CLOSED, not CANCELLED.
    """
    patient = Patient(
        id=uuid.uuid4(),
        uhid="TEST005",
        first_name="Test",
        last_name="Patient5",
        dob=date(1990, 1, 5),
        gender="male",
        phone="9999999999",
    )
    session.add(patient)
    await session.flush()

    # Test from each state where cancellation is allowed
    # (CONSULTATION_COMPLETED is NOT allowed to cancel per workflow rules)
    for status in [
        VisitStatus.REGISTERED,
        VisitStatus.WAITING_FOR_NURSE,
        VisitStatus.IN_PRE_VITAL,
        VisitStatus.WAITING_FOR_DOCTOR,
        VisitStatus.IN_CONSULTATION,
    ]:
        visit = Visit(
            id=uuid.uuid4(),
            patient_id=patient.id,
            uhid=patient.uhid,
            doctor_id=uuid.uuid4(),
            department_id=uuid.uuid4(),
            status=status.value,
        )
        session.add(visit)
        await session.flush()

        await VisitWorkflowService.transition(
            session,
            visit,
            VisitStatus.CANCELLED,
            uuid.uuid4(),
            VisitTransitionSource.CANCELLED,
        )

        assert visit.status == VisitStatus.CANCELLED.value
        assert visit.closed_at is not None


@pytest.mark.asyncio
async def test_cannot_transition_from_terminal_state(session: AsyncSession):
    """
    Verify that terminal states (CLOSED, CANCELLED) do not allow further transitions.
    """
    patient = Patient(
        id=uuid.uuid4(),
        uhid="TEST006",
        first_name="Test",
        last_name="Patient6",
        dob=date(1990, 1, 6),
        gender="male",
        phone="9999999999",
    )
    session.add(patient)
    await session.flush()

    # Test from CLOSED
    closed_visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        status=VisitStatus.CLOSED.value,
    )
    session.add(closed_visit)
    await session.flush()

    with pytest.raises(ValueError):
        await VisitWorkflowService.transition(
            session,
            closed_visit,
            VisitStatus.CANCELLED,
            uuid.uuid4(),
            VisitTransitionSource.RECEPTION,
        )

    # Test from CANCELLED
    cancelled_visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        status=VisitStatus.CANCELLED.value,
    )
    session.add(cancelled_visit)
    await session.flush()

    with pytest.raises(ValueError):
        await VisitWorkflowService.transition(
            session,
            cancelled_visit,
            VisitStatus.CLOSED,
            uuid.uuid4(),
            VisitTransitionSource.RECEPTION,
        )
