"""Deterministic isolated PostgreSQL fixture for the Task 7 Playwright suite."""
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.base import Base
from app.models.public.user import Tenant, User
from app.models.tenant import *  # noqa: F401,F403

SCHEMA = "e2e_task7"
DOCTOR_USERNAME = "e2e_doctor_task7"
DOCTOR_EMAIL = "e2e-doctor-task7@example.test"
DOCTOR_PASSWORD = "E2eDoctor@123"
RECEPTIONIST_USERNAME = "e2e_receptionist_task7"
RECEPTIONIST_EMAIL = "e2e-receptionist-task7@example.test"
RECEPTIONIST_PASSWORD = "E2eReception@123"
TENANT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-tenant")
DOCTOR_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor")
RECEPTIONIST_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-receptionist")
DOCTOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-profile")
DEPARTMENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-department")
PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-patient")
VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-visit")
ICD_URI = "https://example.test/icd10/task7"
MED_URI = "https://example.test/medicine/task7"


def _tables():
    return [table for table in Base.metadata.sorted_tables if table.schema is None]


async def seed():
    from app.core.config import settings
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await conn.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_tables(), checkfirst=False))
        await conn.execute(text('DELETE FROM public.users WHERE id IN (:doctor_id, :receptionist_id) OR username IN (:doctor_username, :receptionist_username)'), {"doctor_id": DOCTOR_USER_ID, "receptionist_id": RECEPTIONIST_USER_ID, "doctor_username": DOCTOR_USERNAME, "receptionist_username": RECEPTIONIST_USERNAME})
        await conn.execute(text('DELETE FROM public.tenants WHERE id = :id OR schema_name = :schema'), {"id": TENANT_ID, "schema": SCHEMA})
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.execute(text('SET search_path TO public'))
        tenant = Tenant(id=TENANT_ID, schema_name=SCHEMA, hospital_name="E2E Task 7 Hospital", contact_email="e2e-task7@example.test", display_token=f"e2e-{uuid.uuid4().hex}")
        user = User(id=DOCTOR_USER_ID, tenant_id=TENANT_ID, tenant_name=SCHEMA, email=DOCTOR_EMAIL, username=DOCTOR_USERNAME, hashed_password=hash_password(DOCTOR_PASSWORD), full_name="E2E Doctor", role="doctor", is_active=True, must_change_password=False)
        receptionist = User(id=RECEPTIONIST_USER_ID, tenant_id=TENANT_ID, tenant_name=SCHEMA, email=RECEPTIONIST_EMAIL, username=RECEPTIONIST_USERNAME, hashed_password=hash_password(RECEPTIONIST_PASSWORD), full_name="E2E Receptionist", role="receptionist", is_active=True, must_change_password=False)
        session.add_all([tenant, user, receptionist])
        await session.commit()
        await session.execute(text(f'SET search_path TO "{SCHEMA}", public'))
        department = Department(id=DEPARTMENT_ID, name="E2E General Medicine", is_active=True)
        doctor = Doctor(id=DOCTOR_ID, user_id=DOCTOR_USER_ID, full_name="E2E Doctor", specialization="General Medicine", department_id=DEPARTMENT_ID, consultation_fee=0, is_active=True)
        patient = Patient(id=PATIENT_ID, uhid="E2E-T7-PATIENT", first_name="E2E", last_name="Patient", gender="female", phone="9000000007")
        visit = Visit(id=VISIT_ID, patient_id=PATIENT_ID, uhid=patient.uhid, doctor_id=DOCTOR_ID, department_id=DEPARTMENT_ID, status="WAITING_FOR_DOCTOR", arrived_at=now, registered_at=now, pre_vital_completed_at=now, doctor_queue_at=now)
        vitals = Vitals(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-vitals"), visit_id=VISIT_ID, uhid=patient.uhid, temperature=37.0, pulse=72, respiratory_rate=18, bp_systolic=120, bp_diastolic=80, spo2=99, pain_score=1, height=170, weight=70, bmi=24.2, blood_glucose=95, chief_complaint="E2E cough", allergies="None", known_no_allergies=True, general_condition="Stable", level_of_consciousness="Alert", nurse_notes="E2E completed pre-vitals", status="completed", recorded_by_user_id=DOCTOR_USER_ID, started_at=now, completed_at=now)
        icd_active = ICD10Code(id=uuid.uuid5(uuid.NAMESPACE_DNS, ICD_URI), code="E2E.J06.9", description="E2E Acute upper respiratory infection", is_active=True)
        icd_inactive = ICD10Code(id=uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/icd10/inactive"), code="E2E.Z99.9", description="E2E Inactive diagnosis", is_active=False)
        med_table = MedicineMaster(id=uuid.uuid5(uuid.NAMESPACE_DNS, MED_URI), generic_name="E2E Paracetamol", brand_name="E2E Crocin", strength="500 mg", dosage_form="Tablet", is_active=True)
        med_capsule = MedicineMaster(id=uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/medicine/capsule"), generic_name="E2E Paracetamol", brand_name="E2E Crocin", strength="650 mg", dosage_form="Capsule", is_active=True)
        med_inactive = MedicineMaster(id=uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/medicine/inactive"), generic_name="E2E Inactive Drug", brand_name="E2E Old", strength="10 mg", dosage_form="Tablet", is_active=False)
        session.add_all([department, doctor, patient, visit, vitals, icd_active, icd_inactive, med_table, med_capsule, med_inactive])
        await session.commit()
    await engine.dispose()
    print(f"E2E seed ready: {DOCTOR_USERNAME} / {DOCTOR_PASSWORD} / visit={VISIT_ID}")


async def cleanup():
    from app.core.config import settings
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text('DELETE FROM public.vitals WHERE visit_id = :id'), {"id": VISIT_ID})
        await conn.execute(text('DELETE FROM public.consultations WHERE visit_id = :id'), {"id": VISIT_ID})
        await conn.execute(text('DELETE FROM public.prescriptions WHERE visit_id = :id'), {"id": VISIT_ID})
        await conn.execute(text('DELETE FROM public.lab_orders WHERE visit_id = :id'), {"id": VISIT_ID})
        await conn.execute(text('DELETE FROM public.queue_tokens WHERE visit_id = :id'), {"id": VISIT_ID})
        await conn.execute(text('DELETE FROM public.visits WHERE id = :id OR doctor_id = :doctor_id'), {"id": VISIT_ID, "doctor_id": DOCTOR_ID})
        await conn.execute(text('DELETE FROM public.doctors WHERE id = :id OR department_id = :department_id'), {"id": DOCTOR_ID, "department_id": DEPARTMENT_ID})
        await conn.execute(text('DELETE FROM public.departments WHERE id = :id'), {"id": DEPARTMENT_ID})
        await conn.execute(delete(User).where(User.id.in_([DOCTOR_USER_ID, RECEPTIONIST_USER_ID])))
        await conn.execute(delete(Tenant).where(Tenant.id == TENANT_ID))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed() if sys.argv[1] == "seed" else cleanup())
