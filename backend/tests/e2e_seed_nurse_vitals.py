"""Runtime-isolated PostgreSQL fixture for the nurse vitals browser flow."""
import asyncio
import json
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.base import Base
from app.models.public.tenant_feature import TenantFeature
from app.models.public.user import Tenant, User
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.nurse_department import NurseDepartment
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit


def _tenant_tables():
    return [table for table in Base.metadata.sorted_tables if table.schema is None]


def _payload(prefix: str) -> dict[str, str]:
    suffix = secrets.token_hex(5)
    return {
        "schema": f"e2e_nurse_{prefix}_{suffix}",
        "tenant_id": str(uuid.uuid4()),
        "nurse_user_id": str(uuid.uuid4()),
        "doctor_user_id": str(uuid.uuid4()),
        "nurse_username": f"nurse_{prefix}_{suffix}",
        "doctor_username": f"doctor_{prefix}_{suffix}",
        "nurse_password": secrets.token_urlsafe(16),
        "doctor_password": secrets.token_urlsafe(16),
        "department_id": str(uuid.uuid4()),
        "doctor_id": str(uuid.uuid4()),
        "patient_id": str(uuid.uuid4()),
        "visit_id": str(uuid.uuid4()),
    }


async def seed():
    from app.core.config import settings

    data = _payload("vitals")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{data["schema"]}"'))
        await conn.execute(text(f'SET search_path TO "{data["schema"]}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_tenant_tables(), checkfirst=False))

    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.execute(text("SET search_path TO public"))
        tenant = Tenant(id=uuid.UUID(data["tenant_id"]), schema_name=data["schema"], hospital_name="Nurse Vitals E2E Hospital", contact_email=f"{data['schema']}@example.test", display_token=secrets.token_urlsafe(24))
        nurse = User(id=uuid.UUID(data["nurse_user_id"]), tenant_id=tenant.id, tenant_name=tenant.schema_name, email=f"{data['nurse_username']}@example.test", username=data["nurse_username"], phone="+919000000001", hashed_password=hash_password(data["nurse_password"]), full_name="E2E Nurse", role="nurse", is_active=True, must_change_password=False)
        doctor_user = User(id=uuid.UUID(data["doctor_user_id"]), tenant_id=tenant.id, tenant_name=tenant.schema_name, email=f"{data['doctor_username']}@example.test", username=data["doctor_username"], phone="+919000000002", hashed_password=hash_password(data["doctor_password"]), full_name="E2E Doctor", role="doctor", is_active=True, must_change_password=False)
        session.add(tenant)
        await session.flush()
        session.add_all([nurse, doctor_user])
        await session.commit()
        session.add_all([
            TenantFeature(id=uuid.uuid4(), tenant_id=tenant.id, feature="vitals", enabled=True),
            TenantFeature(id=uuid.uuid4(), tenant_id=tenant.id, feature="appointments", enabled=True),
            TenantFeature(id=uuid.uuid4(), tenant_id=tenant.id, feature="opd_queue", enabled=True),
        ])
        await session.commit()
        await session.execute(text(f'SET search_path TO "{data["schema"]}", public'))
        department = Department(id=uuid.UUID(data["department_id"]), name="E2E Nursing", is_active=True)
        doctor = Doctor(id=uuid.UUID(data["doctor_id"]), user_id=doctor_user.id, full_name="E2E Doctor", specialization="General Medicine", department_id=department.id, consultation_fee=0, is_active=True)
        patient = Patient(id=uuid.UUID(data["patient_id"]), uhid=f"E2E-{secrets.token_hex(4).upper()}", first_name="Nurse", last_name="Vitals Patient", gender="female", phone="+919000000003")
        visit = Visit(id=uuid.UUID(data["visit_id"]), patient_id=patient.id, uhid=patient.uhid, doctor_id=doctor.id, department_id=department.id, status="WAITING_FOR_NURSE", registered_at=now, arrived_at=now, nurse_queue_at=now)
        assignment = NurseDepartment(id=uuid.uuid4(), user_id=nurse.id, department_id=department.id, assigned_by=nurse.id)
        session.add_all([department, doctor, patient, visit, assignment])
        await session.commit()
    await engine.dispose()
    print(json.dumps(data))


async def cleanup(data: dict[str, str]):
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{data["schema"]}" CASCADE'))
        await conn.execute(delete(TenantFeature).where(TenantFeature.tenant_id == uuid.UUID(data["tenant_id"])))
        await conn.execute(delete(User).where(User.id.in_([uuid.UUID(data["nurse_user_id"]), uuid.UUID(data["doctor_user_id"])])))
        await conn.execute(delete(Tenant).where(Tenant.id == uuid.UUID(data["tenant_id"])))
    await engine.dispose()


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "seed":
        asyncio.run(seed())
    elif command == "cleanup":
        asyncio.run(cleanup(json.loads(sys.stdin.read())))
    else:
        raise SystemExit(f"Unknown command: {command}")
