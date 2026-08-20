import uuid
from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.doctor_schedule import DoctorSchedule

router = APIRouter()


@router.get("", response_model=List[DoctorSchedule])
async def list_doctor_schedules(
    doctor_id: Optional[uuid.UUID] = None,
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "doctor", "hospital_admin")),
):
    stmt = select(DoctorSchedule).order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
    if doctor_id:
        stmt = stmt.where(DoctorSchedule.doctor_id == doctor_id)
    if not include_inactive:
        stmt = stmt.where(DoctorSchedule.is_active == True)  # noqa: E712
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.post("", response_model=DoctorSchedule, status_code=status.HTTP_201_CREATED)
async def create_doctor_schedule(
    payload: dict,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin")),
):
    schedule = DoctorSchedule(**payload)
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


@router.patch("/{schedule_id}", response_model=DoctorSchedule)
async def update_doctor_schedule(
    schedule_id: uuid.UUID,
    payload: dict,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin")),
):
    schedule = await session.get(DoctorSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    for field, value in payload.items():
        setattr(schedule, field, value)
    await session.commit()
    await session.refresh(schedule)
    return schedule
