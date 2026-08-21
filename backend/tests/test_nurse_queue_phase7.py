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

from app.api.v1.vitals import record_vitals
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.patient import Patient
from app.models.tenant.vitals import Vitals
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.vitals import VitalsCreate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "nurse"}

_TABLES = [
    Patient.__table__,
    Visit.__table__,
    Vitals.__table__,
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


@pytest.mark.asyncio
async def test_nurse_vitals_transitions_waiting_for_nurse_to_in_pre_vital(session):
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        status=VisitStatus.WAITING_FOR_NURSE.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([patient, visit])
    await session.commit()

    response = await record_vitals(
        VitalsCreate(
            visit_id=visit.id,
            bp_systolic=120,
            bp_diastolic=80,
            temperature=37.0,
            weight=70,
            height=170,
            spo2=99,
            pulse=72,
        ),
        session=session,
        current_user=CURRENT_USER,
    )

    await session.refresh(visit)
    assert response.recorded_by_user_id == uuid.UUID(CURRENT_USER["sub"])
    assert visit.status == VisitStatus.IN_PRE_VITAL.value

    audit = (await session.execute(
        __import__('sqlalchemy').select(AuditLog).where(AuditLog.resource_id == str(visit.id))
    )).scalars().all()
    assert any(log.new_value.get("status") == VisitStatus.IN_PRE_VITAL.value for log in audit)


@pytest.mark.asyncio
async def test_nurse_vitals_rejects_registered_visit_before_nurse_queue(session):
    patient = _make_patient()
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        status=VisitStatus.REGISTERED.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add_all([patient, visit])
    await session.commit()

    with pytest.raises(Exception):
        await record_vitals(
            VitalsCreate(
                visit_id=visit.id,
                bp_systolic=120,
                bp_diastolic=80,
                temperature=37.0,
                weight=70,
                height=170,
                spo2=99,
                pulse=72,
            ),
            session=session,
            current_user=CURRENT_USER,
        )
