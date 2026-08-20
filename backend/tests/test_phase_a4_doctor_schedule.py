import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone

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

from app.api.v1.appointments import get_slots, book_appointment
from app.db.base import Base
from app.models.tenant.appointment import Appointment
from app.models.tenant.doctor import Doctor
from app.models.tenant.doctor_schedule import DoctorSchedule
from app.models.tenant.doctor_schedule_exception import DoctorScheduleException
from app.models.tenant.patient import Patient
from app.schemas.appointment import AppointmentCreate


_TABLES = [
    Patient.__table__,
    Doctor.__table__,
    DoctorSchedule.__table__,
    DoctorScheduleException.__table__,
    Appointment.__table__,
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
        uhid="UHID001",
        first_name="Test",
        last_name="Patient",
        gender="female",
        phone="9999999999",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Patient(**defaults)


def _make_doctor(**overrides) -> Doctor:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        full_name="Dr. Test",
        specialization="General Medicine",
        consultation_fee=0.0,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Doctor(**defaults)


@pytest.mark.asyncio
async def test_slots_follow_doctor_schedule_capacity_and_booking(session):
    patient = _make_patient()
    doctor = _make_doctor()
    target_date = date(2026, 8, 17)
    schedule = DoctorSchedule(
        id=uuid.uuid4(),
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        weekday=target_date.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 30),
        slot_duration_minutes=30,
        capacity=1,
        effective_from=target_date,
        effective_to=target_date,
        is_active=True,
    )
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    appointment_time = datetime(2026, 8, 17, 9, 30, tzinfo=ist_tz).astimezone(timezone.utc)
    appt = Appointment(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        slot_time=appointment_time,
        status="scheduled",
        type="phone",
        created_at=appointment_time,
        updated_at=appointment_time,
    )
    session.add_all([patient, doctor, schedule, appt])
    await session.commit()

    slots = await get_slots(
        doctor_id=doctor.id,
        slot_date=target_date,
        session=session,
        _={"sub": str(uuid.uuid4()), "role": "receptionist"},
    )

    available_slot_times = [slot.slot_time for slot in slots if slot.is_available]
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    assert datetime(2026, 8, 17, 9, 0, tzinfo=ist_tz).astimezone(timezone.utc) in available_slot_times
    assert datetime(2026, 8, 17, 9, 30, tzinfo=ist_tz).astimezone(timezone.utc) not in available_slot_times
    assert datetime(2026, 8, 17, 10, 0, tzinfo=ist_tz).astimezone(timezone.utc) in available_slot_times


@pytest.mark.asyncio
async def test_book_appointment_rejects_over_capacity_slot(session):
    patient = _make_patient()
    doctor = _make_doctor()
    target_date = date(2026, 8, 17)
    schedule = DoctorSchedule(
        id=uuid.uuid4(),
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        weekday=target_date.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 0),
        slot_duration_minutes=30,
        capacity=1,
        effective_from=target_date,
        effective_to=target_date,
        is_active=True,
    )
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    appt_time = datetime(2026, 8, 17, 9, 0, tzinfo=ist_tz).astimezone(timezone.utc)
    session.add_all([patient, doctor, schedule])
    await session.commit()

    existing = Appointment(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        slot_time=appt_time,
        status="scheduled",
        type="phone",
        created_at=appt_time,
        updated_at=appt_time,
    )
    session.add(existing)
    await session.commit()

    with pytest.raises(Exception):
        await book_appointment(
            payload=AppointmentCreate(
                patient_id=uuid.uuid4(),
                doctor_id=doctor.id,
                slot_time=appt_time,
                type="phone",
            ),
            session=session,
            current_user={"sub": str(uuid.uuid4()), "role": "receptionist", "tenant_schema": "tenant_1"},
        )


@pytest.mark.asyncio
async def test_multi_capacity_slot_allows_up_to_configured_limit(session):
    doctor = _make_doctor()
    target_date = date(2026, 8, 17)
    schedule = DoctorSchedule(
        id=uuid.uuid4(),
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        weekday=target_date.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 0),
        slot_duration_minutes=30,
        capacity=3,
        effective_from=target_date,
        effective_to=target_date,
        is_active=True,
    )
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    slot_time = datetime(2026, 8, 17, 9, 0, tzinfo=ist_tz).astimezone(timezone.utc)
    for idx in range(2):
        patient = _make_patient(id=uuid.uuid4(), uhid=f"UHID{idx + 10:03d}")
        session.add(
            Appointment(
                id=uuid.uuid4(),
                patient_id=patient.id,
                uhid=patient.uhid,
                doctor_id=doctor.id,
                slot_time=slot_time,
                status="scheduled",
                type="phone",
                created_at=slot_time,
                updated_at=slot_time,
            )
        )
    session.add_all([doctor, schedule])
    await session.commit()

    slots = await get_slots(
        doctor_id=doctor.id,
        slot_date=target_date,
        session=session,
        _={"sub": str(uuid.uuid4()), "role": "receptionist"},
    )

    match = next(slot for slot in slots if slot.slot_time == slot_time)
    assert match.is_available is True


@pytest.mark.asyncio
async def test_cancelled_appointments_release_capacity(session):
    patient = _make_patient()
    doctor = _make_doctor()
    target_date = date(2026, 8, 17)
    schedule = DoctorSchedule(
        id=uuid.uuid4(),
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        weekday=target_date.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 0),
        slot_duration_minutes=30,
        capacity=1,
        effective_from=target_date,
        effective_to=target_date,
        is_active=True,
    )
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    slot_time = datetime(2026, 8, 17, 9, 0, tzinfo=ist_tz).astimezone(timezone.utc)
    appt = Appointment(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        doctor_id=doctor.id,
        slot_time=slot_time,
        status="scheduled",
        type="phone",
        created_at=slot_time,
        updated_at=slot_time,
    )
    session.add_all([patient, doctor, schedule, appt])
    await session.commit()

    appt.status = "cancelled"
    await session.commit()

    slots = await get_slots(
        doctor_id=doctor.id,
        slot_date=target_date,
        session=session,
        _={"sub": str(uuid.uuid4()), "role": "receptionist"},
    )
    match = next(slot for slot in slots if slot.slot_time == slot_time)
    assert match.is_available is True


@pytest.mark.asyncio
async def test_last_capacity_booking_is_concurrency_safe(session):
    doctor = _make_doctor()
    target_date = date(2026, 8, 17)
    schedule = DoctorSchedule(
        id=uuid.uuid4(),
        doctor_id=doctor.id,
        department_id=uuid.uuid4(),
        weekday=target_date.weekday(),
        start_time=time(9, 0),
        end_time=time(9, 30),
        slot_duration_minutes=30,
        capacity=2,
        effective_from=target_date,
        effective_to=target_date,
        is_active=True,
    )
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    slot_time = datetime(2026, 8, 17, 9, 0, tzinfo=ist_tz).astimezone(timezone.utc)
    session.add_all([doctor, schedule])
    await session.commit()

    async def book_for(patient_id: uuid.UUID):
        async with async_sessionmaker(bind=session.bind, expire_on_commit=False, class_=AsyncSession)() as s:
            patient = await s.get(Patient, patient_id)
            if patient is None:
                raise RuntimeError("missing patient")
            return await book_appointment(
                payload=AppointmentCreate(
                    patient_id=patient_id,
                    doctor_id=doctor.id,
                    slot_time=slot_time,
                    type="phone",
                ),
                session=s,
                current_user={"sub": str(uuid.uuid4()), "role": "receptionist", "tenant_schema": "tenant_1"},
            )

    patient_rows = [
        _make_patient(id=uuid.uuid4(), uhid=f"UHID{idx:03d}")
        for idx in range(20, 23)
    ]
    async with async_sessionmaker(bind=session.bind, expire_on_commit=False, class_=AsyncSession)() as s:
        s.add_all(patient_rows)
        await s.commit()

    results = await asyncio.gather(
        *[book_for(patient.id) for patient in patient_rows],
        return_exceptions=True,
    )
    successful = [r for r in results if not isinstance(r, Exception)]
    failed = [r for r in results if isinstance(r, Exception)]

    assert len(successful) == 2
    assert len(failed) == 1
