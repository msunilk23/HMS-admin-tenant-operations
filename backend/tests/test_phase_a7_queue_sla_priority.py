import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"

from app.api.v1.queue import edit_token, queue_summary
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.queue import QueueTokenUpdate
from app.services.queue_sla import queue_stage_summary
from sqlalchemy import select


_TABLES = [Patient.__table__, Visit.__table__, QueueToken.__table__, AuditLog.__table__]


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
    async with maker() as session:
        yield session
    await engine.dispose()


def test_queue_sla_counts_breaches_and_longest_wait():
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    visits = [
        SimpleNamespace(nurse_queue_at=now - timedelta(minutes=16)),
        SimpleNamespace(nurse_queue_at=now - timedelta(minutes=4)),
    ]
    result = queue_stage_summary(
        visits,
        queue_timestamp="nurse_queue_at",
        threshold_seconds=15 * 60,
        now=now,
    )
    assert result["waiting_count"] == 2
    assert result["breached_count"] == 1
    assert result["longest_wait_seconds"] == 16 * 60


@pytest.mark.asyncio
async def test_queue_summary_uses_persisted_wait_timestamps(session, monkeypatch):
    now = datetime.now(timezone.utc)
    patient = Patient(
        id=uuid.uuid4(), uhid="UHID-A7-001", first_name="Asha", last_name="Rao",
        gender="female", phone="9876543210", created_at=now, updated_at=now,
    )
    nurse_visit = Visit(
        id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid,
        status=VisitStatus.WAITING_FOR_NURSE.value,
        nurse_queue_at=now - timedelta(minutes=20), registered_at=now - timedelta(minutes=25),
    )
    doctor_visit = Visit(
        id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid,
        status=VisitStatus.WAITING_FOR_DOCTOR.value,
        doctor_queue_at=now - timedelta(minutes=5), registered_at=now - timedelta(minutes=10),
    )
    session.add_all([patient, nurse_visit, doctor_visit])
    await session.commit()

    monkeypatch.setattr("app.api.v1.queue.settings.QUEUE_SLA_NURSE_MINUTES", 15)
    monkeypatch.setattr("app.api.v1.queue.settings.QUEUE_SLA_DOCTOR_MINUTES", 10)
    result = await queue_summary(session=session, _={"role": "nurse"})

    assert result.waiting_for_nurse.waiting_count == 1
    assert result.waiting_for_nurse.breached_count == 1
    assert result.waiting_for_doctor.waiting_count == 1
    assert result.waiting_for_doctor.breached_count == 0


@pytest.mark.asyncio
async def test_priority_edit_persists_reason_assignment_and_audit(session):
    now = datetime.now(timezone.utc)
    patient = Patient(
        id=uuid.uuid4(), uhid="UHID-A7-002", first_name="Mina", last_name="Das",
        gender="female", phone="9876543211", created_at=now, updated_at=now,
    )
    token = QueueToken(
        id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, token_no=1,
        queue_type="consultation", priority="normal", status="checked_in",
    )
    session.add_all([patient, token])
    await session.commit()
    user = {"sub": str(uuid.uuid4()), "role": "receptionist", "tenant_schema": "test_tenant"}

    result = await edit_token(
        token.id,
        QueueTokenUpdate(priority="urgent", priority_reason="Time-sensitive clinical concern"),
        session=session,
        current_user=user,
    )

    assert result.priority == "urgent"
    assert result.priority_reason == "Time-sensitive clinical concern"
    assert result.priority_assigned_by == uuid.UUID(user["sub"])
    audit = (await session.execute(
        select(AuditLog).where(AuditLog.resource_type == "queue_priority")
    )).scalar_one()
    assert audit.action == "UPDATE"
