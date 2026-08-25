import uuid
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_feature, require_role
from app.db.engine import get_session
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.doctor_schedule import DoctorSchedule
from app.models.tenant.doctor_schedule_exception import DoctorScheduleException
from app.schemas.doctor_schedule import (
    DoctorAvailabilityDay, DoctorAvailableSlot, DoctorScheduleCreate,
    DoctorScheduleExceptionCreate, DoctorScheduleExceptionRead,
    DoctorScheduleExceptionUpdate, DoctorScheduleRead, DoctorScheduleUpdate,
)
from app.services.audit_service import record_audit
from app.services.doctor_availability_service import available_slots

router = APIRouter(dependencies=[Depends(require_feature("appointments"))])


def _check_overlap(existing: list[DoctorSchedule], candidate: DoctorScheduleCreate | DoctorScheduleUpdate) -> bool:
    weekday = candidate.weekday
    start = candidate.start_time
    end = candidate.end_time
    from_date = candidate.effective_from
    to_date = candidate.effective_to
    return any(
        row.weekday == weekday and row.start_time < end and row.end_time > start and
        (from_date is None or row.effective_to is None or from_date <= row.effective_to) and
        (to_date is None or row.effective_from is None or to_date >= row.effective_from)
        for row in existing if row.is_active
    )


async def _doctor_and_department(session: AsyncSession, doctor_id: uuid.UUID, department_id: uuid.UUID | None):
    doctor = (await session.execute(select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active == True))).scalar_one_or_none()  # noqa: E712
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if department_id is not None:
        department = (await session.execute(select(Department).where(Department.id == department_id, Department.is_active == True))).scalar_one_or_none()  # noqa: E712
        if not department:
            raise HTTPException(status_code=404, detail="Department not found")
    return doctor


@router.get("", response_model=List[DoctorScheduleRead])
async def list_doctor_schedules(
    doctor_id: Optional[uuid.UUID] = None,
    include_inactive: bool = False,
    weekday: Optional[int] = Query(None, ge=0, le=6),
    schedule_date: Optional[date] = Query(None, alias="date"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "doctor", "hospital_admin")),
):
    if current_user.get("role") == "doctor":
        doctor = (await session.execute(select(Doctor.id).where(Doctor.user_id == uuid.UUID(current_user["sub"]), Doctor.is_active == True))).scalar_one_or_none()  # noqa: E712
        if doctor is None:
            raise HTTPException(status_code=403, detail="Doctor profile not found")
        if doctor_id and doctor_id != doctor:
            raise HTTPException(status_code=403, detail="Doctors may view only their own schedule")
        doctor_id = doctor
    stmt = select(DoctorSchedule).order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
    if doctor_id:
        stmt = stmt.where(DoctorSchedule.doctor_id == doctor_id)
    if not include_inactive:
        stmt = stmt.where(DoctorSchedule.is_active == True)  # noqa: E712
    if weekday is not None:
        stmt = stmt.where(DoctorSchedule.weekday == weekday)
    if schedule_date is not None:
        stmt = stmt.where(or_(DoctorSchedule.effective_from.is_(None), DoctorSchedule.effective_from <= schedule_date), or_(DoctorSchedule.effective_to.is_(None), DoctorSchedule.effective_to >= schedule_date))
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.post("", response_model=DoctorScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_doctor_schedule(
    payload: DoctorScheduleCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    if payload.doctor_id is None:
        raise HTTPException(status_code=422, detail="doctor_id is required")
    await _doctor_and_department(session, payload.doctor_id, payload.department_id)
    existing = (await session.execute(select(DoctorSchedule).where(DoctorSchedule.doctor_id == payload.doctor_id))).scalars().all()
    if _check_overlap(existing, payload):
        raise HTTPException(status_code=409, detail="Schedule overlaps an active session")
    schedule = DoctorSchedule(id=uuid.uuid4(), **payload.model_dump())
    session.add(schedule)
    record_audit(session, current_user=current_user, action="SCHEDULE_CREATED", resource_type="doctor_schedule", resource_id=schedule.id, new_value={"doctor_id": str(payload.doctor_id)})
    await session.commit()
    await session.refresh(schedule)
    return schedule


@router.get("/{schedule_id}", response_model=DoctorScheduleRead)
async def get_doctor_schedule(schedule_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("receptionist", "doctor", "hospital_admin"))):
    schedule = await session.get(DoctorSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    if current_user.get("role") == "doctor":
        doctor_id = (await session.execute(select(Doctor.id).where(Doctor.user_id == uuid.UUID(current_user["sub"]), Doctor.is_active == True))).scalar_one_or_none()  # noqa: E712
        if doctor_id != schedule.doctor_id:
            raise HTTPException(status_code=403, detail="Doctors may view only their own schedule")
    return schedule


@router.patch("/{schedule_id}", response_model=DoctorScheduleRead)
async def update_doctor_schedule(
    schedule_id: uuid.UUID,
    payload: DoctorScheduleUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    schedule = await session.get(DoctorSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    values = payload.model_dump(exclude_unset=True)
    candidate = DoctorScheduleCreate(
        doctor_id=schedule.doctor_id,
        department_id=values.get("department_id", schedule.department_id),
        weekday=values.get("weekday", schedule.weekday),
        start_time=values.get("start_time", schedule.start_time),
        end_time=values.get("end_time", schedule.end_time),
        slot_duration_minutes=values.get("slot_duration_minutes", schedule.slot_duration_minutes),
        capacity=values.get("capacity", schedule.capacity),
        effective_from=values.get("effective_from", schedule.effective_from),
        effective_to=values.get("effective_to", schedule.effective_to),
        room=values.get("room", schedule.room), appointment_type=values.get("appointment_type", schedule.appointment_type),
        is_active=values.get("is_active", schedule.is_active), notes=values.get("notes", schedule.notes),
    )
    await _doctor_and_department(session, schedule.doctor_id, candidate.department_id)
    existing = (await session.execute(select(DoctorSchedule).where(DoctorSchedule.doctor_id == schedule.doctor_id, DoctorSchedule.id != schedule.id))).scalars().all()
    if candidate.is_active and _check_overlap(existing, candidate):
        raise HTTPException(status_code=409, detail="Schedule overlaps an active session")
    for field, value in values.items():
        setattr(schedule, field, value)
    record_audit(session, current_user=current_user, action="SCHEDULE_CHANGED", resource_type="doctor_schedule", resource_id=schedule.id)
    await session.commit()
    await session.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", response_model=DoctorScheduleRead)
async def deactivate_doctor_schedule(schedule_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin"))):
    schedule = await session.get(DoctorSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    schedule.is_active = False
    record_audit(session, current_user=current_user, action="SCHEDULE_DEACTIVATED", resource_type="doctor_schedule", resource_id=schedule.id)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def _get_doctor_or_404(session: AsyncSession, doctor_id: uuid.UUID) -> Doctor:
    doctor = (await session.execute(select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active == True))).scalar_one_or_none()  # noqa: E712
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


@router.get("/{doctor_id}/exceptions", response_model=list[DoctorScheduleExceptionRead])
async def list_schedule_exceptions(doctor_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("receptionist", "doctor", "hospital_admin"))):
    doctor = await _get_doctor_or_404(session, doctor_id)
    if current_user.get("role") == "doctor" and str(doctor.user_id) != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Doctors may view only their own exceptions")
    return (await session.execute(select(DoctorScheduleException).where(DoctorScheduleException.doctor_id == doctor_id).order_by(DoctorScheduleException.start_datetime))).scalars().all()


@router.post("/{doctor_id}/exceptions", response_model=DoctorScheduleExceptionRead, status_code=201)
async def create_schedule_exception(doctor_id: uuid.UUID, payload: DoctorScheduleExceptionCreate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin"))):
    await _get_doctor_or_404(session, doctor_id)
    exception = DoctorScheduleException(id=uuid.uuid4(), doctor_id=doctor_id, created_by_user_id=uuid.UUID(current_user["sub"]), **payload.model_dump())
    session.add(exception)
    record_audit(session, current_user=current_user, action="EXCEPTION_CREATED", resource_type="doctor_schedule_exception", resource_id=exception.id)
    await session.commit()
    await session.refresh(exception)
    return exception


@router.patch("/{doctor_id}/exceptions/{exception_id}", response_model=DoctorScheduleExceptionRead)
async def update_schedule_exception(doctor_id: uuid.UUID, exception_id: uuid.UUID, payload: DoctorScheduleExceptionUpdate, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin"))):
    exception = (await session.execute(select(DoctorScheduleException).where(DoctorScheduleException.id == exception_id, DoctorScheduleException.doctor_id == doctor_id))).scalar_one_or_none()
    if not exception:
        raise HTTPException(status_code=404, detail="Schedule exception not found")
    values = payload.model_dump(exclude_unset=True)
    start = values.get("start_datetime", exception.start_datetime)
    end = values.get("end_datetime", exception.end_datetime)
    if start >= end:
        raise HTTPException(status_code=422, detail="start_datetime must be before end_datetime")
    for field, value in values.items():
        setattr(exception, field, value)
    record_audit(session, current_user=current_user, action="EXCEPTION_CHANGED", resource_type="doctor_schedule_exception", resource_id=exception.id)
    await session.commit()
    await session.refresh(exception)
    return exception


@router.delete("/{doctor_id}/exceptions/{exception_id}", response_model=DoctorScheduleExceptionRead)
async def deactivate_schedule_exception(doctor_id: uuid.UUID, exception_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin"))):
    exception = (await session.execute(select(DoctorScheduleException).where(DoctorScheduleException.id == exception_id, DoctorScheduleException.doctor_id == doctor_id))).scalar_one_or_none()
    if not exception:
        raise HTTPException(status_code=404, detail="Schedule exception not found")
    exception.is_active = False
    record_audit(session, current_user=current_user, action="EXCEPTION_DEACTIVATED", resource_type="doctor_schedule_exception", resource_id=exception.id)
    await session.commit()
    return exception


@router.get("/{doctor_id}/availability", response_model=list[DoctorAvailabilityDay])
async def doctor_availability(doctor_id: uuid.UUID, from_date: date = Query(...), to_date: date | None = Query(None), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("receptionist", "doctor", "hospital_admin"))):
    if to_date is None:
        to_date = from_date
    if to_date < from_date or (to_date - from_date).days > 31:
        raise HTTPException(status_code=422, detail="Invalid availability date range")
    if current_user.get("role") == "doctor":
        doctor = await _get_doctor_or_404(session, doctor_id)
        if str(doctor.user_id) != current_user.get("sub"):
            raise HTTPException(status_code=403, detail="Doctors may view only their own availability")
    days = []
    current_date = from_date
    while current_date <= to_date:
        timezone_name, slots = await available_slots(session, doctor_id, current_date, tenant_schema=current_user.get("tenant_schema"))
        days.append(DoctorAvailabilityDay(date=current_date, timezone=timezone_name, slots=slots))
        current_date = current_date.fromordinal(current_date.toordinal() + 1)
    return days
