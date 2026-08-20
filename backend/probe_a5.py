import asyncio
import uuid
from datetime import date, datetime, time, timezone, timedelta
from app.api.v1.appointments import book_appointment
from app.db.base import Base
from app.models.tenant.appointment import Appointment
from app.models.tenant.doctor import Doctor
from app.models.tenant.doctor_schedule import DoctorSchedule
from app.models.tenant.doctor_schedule_exception import DoctorScheduleException
from app.models.tenant.patient import Patient
from app.schemas.appointment import AppointmentCreate
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

async def main():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', poolclass=StaticPool, connect_args={'check_same_thread': False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Patient.__table__, Doctor.__table__, DoctorSchedule.__table__, DoctorScheduleException.__table__, Appointment.__table__])

    sync_s = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with sync_s() as s:
        doctor = Doctor(id=uuid.uuid4(), user_id=uuid.uuid4(), full_name='Dr. Test', specialization='General Medicine', consultation_fee=0.0, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        target_date = date(2026, 8, 17)
        schedule = DoctorSchedule(id=uuid.uuid4(), doctor_id=doctor.id, department_id=uuid.uuid4(), weekday=target_date.weekday(), start_time=time(9,0), end_time=time(9,30), slot_duration_minutes=30, capacity=2, effective_from=target_date, effective_to=target_date, is_active=True)
        s.add_all([doctor, schedule]); await s.commit()
        patient_rows = [Patient(id=uuid.uuid4(), uhid=f'UHID{idx:03d}', first_name='Test', last_name='Patient', gender='female', phone='9999999999', created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)) for idx in range(20,23)]
        s.add_all(patient_rows); await s.commit()
        slot_time = datetime(2026,8,17,9,0,tzinfo=timezone(timedelta(hours=5,minutes=30))).astimezone(timezone.utc)

        async def book_for(patient_id):
            async with async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)() as s2:
                try:
                    result = await book_appointment(
                        payload=AppointmentCreate(patient_id=patient_id, doctor_id=doctor.id, slot_time=slot_time, type='phone'),
                        session=s2,
                        current_user={'sub': str(uuid.uuid4()), 'role': 'receptionist', 'tenant_schema': 'tenant_1'},
                    )
                    print('SUCCESS', patient_id, result.id)
                    return result
                except Exception as exc:
                    print('EXCEPTION', patient_id, type(exc).__name__, exc)
                    return exc

        results = await asyncio.gather(*(book_for(p.id) for p in patient_rows), return_exceptions=True)
        print('FINAL', len([r for r in results if not isinstance(r, Exception)]), 'FAILED', len([r for r in results if isinstance(r, Exception)]))
        print(results)

asyncio.run(main())
