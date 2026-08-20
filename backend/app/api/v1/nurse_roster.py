"""Nurse roster assignments and attendance."""

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_feature, require_role
from app.db.engine import get_session
from app.models.public.user import User
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.nurse_roster import NurseRoster
from app.schemas.nurse_roster import NurseRosterCreate, NurseRosterRead, NurseRosterUpdate

router = APIRouter(dependencies=[Depends(require_feature("nurse_roster"))])
_ADMIN_ROLES = ("hospital_admin", "super_admin")


async def _validate_user(user_id: uuid.UUID, current_user: dict, session: AsyncSession) -> User:
    user = await session.get(User, user_id)
    if not user or not user.is_active or user.role != "nurse":
        raise HTTPException(status_code=422, detail="user_id must reference an active nurse")
    if str(user.tenant_id) != str(current_user.get("tenant_id")):
        raise HTTPException(status_code=403, detail="Nurse belongs to another tenant")
    return user


async def _enrich(row: NurseRoster, session: AsyncSession) -> NurseRosterRead:
    result = NurseRosterRead.model_validate(row)
    nurse = await session.get(User, row.user_id)
    dept = await session.get(Department, row.department_id)
    doctor = await session.get(Doctor, row.assigned_doctor_id) if row.assigned_doctor_id else None
    result.nurse_name = nurse.full_name if nurse else None
    result.department_name = dept.name if dept else None
    result.doctor_name = doctor.full_name if doctor else None
    return result


@router.get("", response_model=List[NurseRosterRead])
async def list_roster(
    roster_date: Optional[date] = Query(None),
    include_inactive: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "hospital_admin", "super_admin")),
):
    filters = []
    if roster_date:
        filters.append(NurseRoster.roster_date == roster_date)
    if not include_inactive:
        filters.append(NurseRoster.is_active == True)  # noqa: E712
    if current_user.get("role") == "nurse":
        filters.append(NurseRoster.user_id == uuid.UUID(current_user["sub"]))
    rows = (await session.execute(
        select(NurseRoster).where(*filters).order_by(NurseRoster.roster_date, NurseRoster.shift)
    )).scalars().all()
    return [await _enrich(row, session) for row in rows]


@router.post("", response_model=NurseRosterRead, status_code=status.HTTP_201_CREATED)
async def create_roster(
    payload: NurseRosterCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    await _validate_user(payload.user_id, current_user, session)
    if not await session.get(Department, payload.department_id):
        raise HTTPException(status_code=404, detail="Department not found")
    if payload.assigned_doctor_id and not await session.get(Doctor, payload.assigned_doctor_id):
        raise HTTPException(status_code=404, detail="Doctor not found")
    duplicate = (await session.execute(
        select(NurseRoster).where(
            NurseRoster.user_id == payload.user_id,
            NurseRoster.roster_date == payload.roster_date,
            NurseRoster.shift == payload.shift,
            NurseRoster.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Nurse already has an active roster entry for this date and shift")
    row = NurseRoster(id=uuid.uuid4(), **payload.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return await _enrich(row, session)


@router.patch("/{roster_id}", response_model=NurseRosterRead)
async def update_roster(
    roster_id: uuid.UUID,
    payload: NurseRosterUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    row = await session.get(NurseRoster, roster_id)
    if not row:
        raise HTTPException(status_code=404, detail="Roster entry not found")
    changes = payload.model_dump(exclude_unset=True)
    if "user_id" in changes:
        await _validate_user(changes["user_id"], current_user, session)
    if "department_id" in changes and not await session.get(Department, changes["department_id"]):
        raise HTTPException(status_code=404, detail="Department not found")
    for field, value in changes.items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    return await _enrich(row, session)
