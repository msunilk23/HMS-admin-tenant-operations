import os
import uuid
from datetime import datetime, timezone

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

from app.api.v1.clinical_alerts import create_clinical_alert, list_patient_alerts, resolve_clinical_alert
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.clinical_alert import ClinicalAlert
from app.models.tenant.patient import Patient
from app.schemas.clinical_alert import ClinicalAlertCreate
from sqlalchemy import select


_TABLES = [Patient.__table__, ClinicalAlert.__table__, AuditLog.__table__]


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


def _patient() -> Patient:
    now = datetime.now(timezone.utc)
    return Patient(
        id=uuid.uuid4(),
        uhid="UHID-A6-001",
        first_name="Asha",
        last_name="Rao",
        gender="female",
        phone="9876543210",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_active_alerts_are_readable_and_resolution_is_audited(session):
    patient = _patient()
    session.add(patient)
    await session.commit()
    user = {"sub": str(uuid.uuid4()), "role": "nurse", "tenant_schema": "test_tenant"}

    alert = await create_clinical_alert(
        ClinicalAlertCreate(patient_id=patient.id, alert_type="allergy", severity="critical", description="Penicillin allergy"),
        session=session,
        current_user=user,
    )
    active = await list_patient_alerts(patient.id, session=session, _=user)
    assert [row.id for row in active] == [alert.id]

    resolved = await resolve_clinical_alert(alert.id, session=session, current_user=user)
    assert resolved.is_active is False
    assert resolved.resolved_by_user_id == uuid.UUID(user["sub"])
    assert await list_patient_alerts(patient.id, session=session, _=user) == []

    audit_rows = (await session.execute(
        select(AuditLog).where(AuditLog.resource_type == "clinical_alert")
    )).scalars().all()
    assert {row.action for row in audit_rows} == {"CREATE", "RESOLVE"}


@pytest.mark.asyncio
async def test_pharmacist_can_read_but_cannot_create_alert():
    from app.api.v1.clinical_alerts import _READ_ROLES, _WRITE_ROLES

    assert "pharmacist" in _READ_ROLES
    assert "pharmacist" not in _WRITE_ROLES
    assert "super_admin" not in _READ_ROLES
    assert "super_admin" not in _WRITE_ROLES
