"""
Phase 6 regression tests — patient registration: UHID generation, duplicate
detection/override, search (phone/UHID/name/Aadhaar), demographic audit
logging, and deactivate/reactivate patient status.
"""
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

# sqlite has no native JSONB type; AuditLog.old_value/new_value use it,
# so map it to plain JSON for the in-memory test database.
@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"

from app.api.v1.patients import (
    deactivate_patient,
    get_patient,
    list_patients,
    reactivate_patient,
    register_patient,
    update_patient,
)
from app.db.base import Base
from app.models.public.user import Tenant
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate

CURRENT_USER = {"sub": str(uuid.uuid4()), "tenant_schema": "test_tenant", "role": "receptionist"}

_TABLES = [Patient.__table__, AuditLog.__table__]


@pytest_asyncio.fixture
async def session(monkeypatch):
    # Avoid real SMS/WhatsApp calls during registration.
    monkeypatch.setattr("app.api.v1.patients.send_patient_welcome", lambda **kwargs: None)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        # public.tenants is schema-qualified; attach a 'public' database so
        # sqlite can resolve it (mirrors the real Postgres schema separation).
        from sqlalchemy import text
        await conn.execute(text("ATTACH DATABASE ':memory:' AS public"))
        await conn.run_sync(Base.metadata.create_all, tables=[*_TABLES, Tenant.__table__])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


def _create_payload(**overrides) -> PatientCreate:
    defaults = dict(
        first_name="Asha",
        last_name="Rao",
        gender="female",
        phone="9876543210",
        aadhar_number="123456789012",
    )
    defaults.update(overrides)
    return PatientCreate(**defaults)


@pytest.mark.asyncio
async def test_register_patient_generates_uhid_and_audit_create(session):
    patient = await register_patient(_create_payload(), session=session, current_user=CURRENT_USER)

    assert patient.uhid.startswith("UHID-")
    assert patient.is_active is True

    audit_rows = (await session.execute(
        select(AuditLog).where(AuditLog.resource_id == str(patient.id))
    )).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "CREATE"
    assert audit_rows[0].new_value["duplicate_override"] is False


@pytest.mark.asyncio
async def test_duplicate_phone_is_blocked_without_override(session):
    await register_patient(_create_payload(), session=session, current_user=CURRENT_USER)

    with pytest.raises(HTTPException) as exc_info:
        await register_patient(
            _create_payload(aadhar_number="999999999999"),
            session=session,
            current_user=CURRENT_USER,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["duplicates"][0]["matched_on"] == ["phone"]


@pytest.mark.asyncio
async def test_duplicate_phone_can_be_overridden_and_is_audited(session):
    first = await register_patient(_create_payload(), session=session, current_user=CURRENT_USER)

    second = await register_patient(
        _create_payload(aadhar_number="999999999999", override_duplicate=True),
        session=session,
        current_user=CURRENT_USER,
    )

    assert second.id != first.id
    audit_rows = (await session.execute(
        select(AuditLog).where(AuditLog.resource_id == str(second.id))
    )).scalars().all()
    assert audit_rows[0].new_value["duplicate_override"] is True


@pytest.mark.asyncio
async def test_search_by_aadhaar_uhid_phone_and_name(session):
    patient = await register_patient(_create_payload(), session=session, current_user=CURRENT_USER)

    by_aadhaar = await list_patients(q="123456789012", include_inactive=False, skip=0, limit=20, session=session, _=CURRENT_USER)
    by_uhid = await list_patients(q=patient.uhid, include_inactive=False, skip=0, limit=20, session=session, _=CURRENT_USER)
    by_phone = await list_patients(q="9876543210", include_inactive=False, skip=0, limit=20, session=session, _=CURRENT_USER)
    by_name = await list_patients(q="asha", include_inactive=False, skip=0, limit=20, session=session, _=CURRENT_USER)

    for results in (by_aadhaar, by_uhid, by_phone, by_name):
        assert len(results) == 1
        assert results[0].id == patient.id


@pytest.mark.asyncio
async def test_update_patient_audits_only_changed_fields(session):
    patient = await register_patient(_create_payload(), session=session, current_user=CURRENT_USER)

    await update_patient(
        patient.id,
        PatientUpdate(phone="9876543210", blood_group="O+"),  # phone unchanged, blood_group changes
        session=session,
        current_user=CURRENT_USER,
    )

    audit_rows = (await session.execute(
        select(AuditLog)
        .where(AuditLog.resource_id == str(patient.id), AuditLog.action == "UPDATE")
    )).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].new_value == {"blood_group": "O+"}
    assert audit_rows[0].old_value == {"blood_group": None}


@pytest.mark.asyncio
async def test_deactivate_and_reactivate_patient_is_audited_and_still_gettable(session):
    patient = await register_patient(_create_payload(), session=session, current_user=CURRENT_USER)

    deactivated = await deactivate_patient(patient.id, session=session, current_user=CURRENT_USER)
    assert deactivated.is_active is False

    # Deactivated patients are hidden from default search...
    default_search = await list_patients(q=None, include_inactive=False, skip=0, limit=20, session=session, _=CURRENT_USER)
    assert patient.id not in [p.id for p in default_search]

    # ...but still directly retrievable and included with include_inactive=True.
    fetched = await get_patient(patient.id, session=session, _=CURRENT_USER)
    assert fetched.is_active is False
    inclusive_search = await list_patients(q=None, include_inactive=True, skip=0, limit=20, session=session, _=CURRENT_USER)
    assert patient.id in [p.id for p in inclusive_search]

    reactivated = await reactivate_patient(patient.id, session=session, current_user=CURRENT_USER)
    assert reactivated.is_active is True

    audit_rows = (await session.execute(
        select(AuditLog)
        .where(AuditLog.resource_id == str(patient.id), AuditLog.action == "UPDATE")
        .order_by(AuditLog.timestamp)
    )).scalars().all()
    is_active_changes = [r for r in audit_rows if "is_active" in (r.new_value or {})]
    assert {r.new_value["is_active"] for r in is_active_changes} == {False, True}
    deactivate_entry = next(r for r in is_active_changes if r.new_value == {"is_active": False})
    reactivate_entry = next(r for r in is_active_changes if r.new_value == {"is_active": True})
    assert deactivate_entry.old_value == {"is_active": True}
    assert reactivate_entry.old_value == {"is_active": False}
