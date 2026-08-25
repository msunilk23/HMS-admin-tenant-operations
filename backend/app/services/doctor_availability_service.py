"""Shared timezone-aware doctor schedule and appointment slot generation."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.public.user import Tenant
from app.models.tenant.appointment import Appointment
from app.models.tenant.doctor_schedule import DoctorSchedule
from app.models.tenant.doctor_schedule_exception import DoctorScheduleException
from app.schemas.doctor_schedule import DoctorAvailableSlot


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def tenant_timezone(session: AsyncSession, tenant_schema: str | None) -> tuple[str, ZoneInfo]:
    row = None
    if tenant_schema:
        try:
            row = (await session.execute(select(Tenant).where(Tenant.schema_name == tenant_schema))).scalar_one_or_none()
        except Exception:
            # Lightweight SQLite/unit-test schemas may not include public.tenants;
            # production falls back to the documented default for missing rows.
            row = None
    name = getattr(row, "timezone", None) or "Asia/Kolkata"
    try:
        return name, ZoneInfo(name)
    except Exception:
        return "Asia/Kolkata", ZoneInfo("Asia/Kolkata")


async def active_schedules(session: AsyncSession, doctor_id: uuid.UUID, target_date: date):
    return (await session.execute(select(DoctorSchedule).where(
        DoctorSchedule.doctor_id == doctor_id,
        DoctorSchedule.is_active == True,  # noqa: E712
        DoctorSchedule.weekday == target_date.weekday(),
        or_(DoctorSchedule.effective_from.is_(None), DoctorSchedule.effective_from <= target_date),
        or_(DoctorSchedule.effective_to.is_(None), DoctorSchedule.effective_to >= target_date),
    ).order_by(DoctorSchedule.start_time))).scalars().all()


async def available_slots(
    session: AsyncSession,
    doctor_id: uuid.UUID,
    target_date: date,
    *,
    tenant_schema: str | None = None,
    include_unavailable: bool = True,
) -> tuple[str, list[DoctorAvailableSlot]]:
    timezone_name, local_tz = await tenant_timezone(session, tenant_schema)
    schedules = await active_schedules(session, doctor_id, target_date)
    if not schedules:
        return timezone_name, []

    local_start = datetime.combine(target_date, time.min, tzinfo=local_tz)
    local_end = local_start + timedelta(days=1)
    exceptions = (await session.execute(select(DoctorScheduleException).where(
        DoctorScheduleException.doctor_id == doctor_id,
        DoctorScheduleException.is_active == True,  # noqa: E712
        DoctorScheduleException.start_datetime < local_end.astimezone(timezone.utc),
        DoctorScheduleException.end_datetime > local_start.astimezone(timezone.utc),
    ))).scalars().all()
    booked_rows = (await session.execute(select(Appointment.slot_time, func.count(Appointment.id)).where(
        Appointment.doctor_id == doctor_id,
        Appointment.slot_time >= local_start.astimezone(timezone.utc),
        Appointment.slot_time < local_end.astimezone(timezone.utc),
        Appointment.status.notin_(["cancelled", "no_show"]),
    ).group_by(Appointment.slot_time))).all()
    booked = {_as_utc(slot): count for slot, count in booked_rows}
    now = datetime.now(timezone.utc)
    result: list[DoctorAvailableSlot] = []
    for schedule in schedules:
        local_slot = datetime.combine(target_date, schedule.start_time, tzinfo=local_tz)
        local_session_end = datetime.combine(target_date, schedule.end_time, tzinfo=local_tz)
        while local_slot < local_session_end:
            slot_time = local_slot.astimezone(timezone.utc)
            slot_end = (local_slot + timedelta(minutes=schedule.slot_duration_minutes)).astimezone(timezone.utc)
            blocked = next((ex for ex in exceptions if _as_utc(ex.start_datetime) < slot_end and _as_utc(ex.end_datetime) > slot_time), None)
            count = booked.get(slot_time, 0)
            available = slot_time > now and blocked is None and count < schedule.capacity
            if include_unavailable or available:
                result.append(DoctorAvailableSlot(
                    slot_time=slot_time,
                    is_available=available,
                    booked_count=count,
                    remaining_capacity=max(schedule.capacity - count, 0),
                    capacity=schedule.capacity,
                    room=schedule.room,
                    appointment_type=schedule.appointment_type,
                    blocked_reason=(blocked.reason or blocked.exception_type) if blocked else ("past" if slot_time <= now else None),
                ))
            local_slot += timedelta(minutes=schedule.slot_duration_minutes)
    unique = {slot.slot_time: slot for slot in result}
    return timezone_name, sorted(unique.values(), key=lambda slot: slot.slot_time)


async def validate_slot(
    session: AsyncSession,
    doctor_id: uuid.UUID,
    slot_time: datetime,
    *,
    tenant_schema: str | None = None,
    exclude_appointment_id: uuid.UUID | None = None,
) -> tuple[DoctorAvailableSlot, DoctorSchedule]:
    timezone_name, local_tz = await tenant_timezone(session, tenant_schema)
    local_date = _as_utc(slot_time).astimezone(local_tz).date()
    _, slots = await available_slots(session, doctor_id, local_date, tenant_schema=tenant_schema)
    normalized = _as_utc(slot_time)
    match = next((slot for slot in slots if slot.slot_time == normalized), None)
    if match is None:
        raise ValueError("Slot is not part of an active doctor schedule")
    if not match.is_available:
        raise ValueError("Slot is not available")
    schedules = await active_schedules(session, doctor_id, local_date)
    schedule = next((item for item in schedules if item.start_time <= normalized.astimezone(local_tz).time() < item.end_time), None)
    if schedule is None:
        raise ValueError("Slot is not part of an active doctor schedule")
    return match, schedule
