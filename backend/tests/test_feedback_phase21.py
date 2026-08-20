import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.feedback import submit_feedback
from app.db.base import Base
from app.models.tenant.feedback import Feedback
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.feedback import FeedbackCreate


_TABLES = [Patient.__table__, Visit.__table__, Feedback.__table__]


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
    async with maker() as current_session:
        yield current_session
    await engine.dispose()


def make_visit():
    now = datetime.now(timezone.utc)
    patient = Patient(
        id=uuid.uuid4(), uhid=f"UHID{uuid.uuid4().hex[:8]}", first_name="Test",
        last_name="Patient", gender="female", phone="9999999999", created_at=now, updated_at=now,
    )
    visit = Visit(
        id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid,
        status=VisitStatus.CLOSED.value, created_at=now, updated_at=now,
    )
    return patient, visit


@pytest.mark.asyncio
async def test_feedback_is_visit_linked_and_duplicate_submission_is_rejected(session):
    patient, visit = make_visit()
    session.add_all([patient, visit])
    await session.commit()
    user = {"sub": str(uuid.uuid4()), "role": "receptionist", "tenant_schema": "tenant_a"}
    payload = FeedbackCreate(visit_id=visit.id, rating=5, comments="Excellent", channel="qr")

    created = await submit_feedback(payload, session=session, _=user)
    assert created.visit_id == visit.id
    assert created.channel == "qr"
    assert created.submitted_at is not None

    with pytest.raises(Exception) as error:
        await submit_feedback(payload, session=session, _=user)
    assert getattr(error.value, "status_code", None) == 409


def test_feedback_validates_rating_and_channel():
    with pytest.raises(ValueError):
        FeedbackCreate(visit_id=uuid.uuid4(), rating=6)
    with pytest.raises(ValueError):
        FeedbackCreate(visit_id=uuid.uuid4(), rating=4, channel="email")


@pytest.mark.asyncio
async def test_feedback_unique_visit_constraint_protects_concurrent_writes(session):
    patient, visit = make_visit()
    session.add_all([patient, visit])
    await session.commit()
    session.add_all([
        Feedback(id=uuid.uuid4(), visit_id=visit.id, rating=4, channel="kiosk"),
        Feedback(id=uuid.uuid4(), visit_id=visit.id, rating=5, channel="qr"),
    ])

    with pytest.raises(IntegrityError):
        await session.commit()
