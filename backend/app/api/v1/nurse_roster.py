"""Nurse roster assignments and attendance.

Ownership contract (Release A, approved): Hospital Admin creates, edits,
deactivates, substitutes, and records attendance for tenant Nurse Rosters.
Nurse has read-only access to their own roster entries. Super Admin has no
tenant Nurse Roster access (denied by the router-level tenant guard; the
per-endpoint role checks below never grant super_admin, as defense in depth).
"""

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_feature, require_role
from app.db.engine import get_session
from app.models.public.user import User
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.nurse_roster import NurseRoster
from app.schemas.nurse_roster import NurseRosterCreate, NurseRosterRead, NurseRosterUpdate
from app.services.audit_service import record_audit

router = APIRouter(dependencies=[Depends(require_feature("nurse_roster"))])

# Hospital Admin is the sole tenant role that manages rosters. Super Admin is
# intentionally excluded here as a matter of contract, not just because the
# router-level tenant guard already denies it.
_ADMIN_ROLES = ("hospital_admin",)


def _values(row: NurseRoster) -> dict:
    return {
        "user_id": str(row.user_id),
        "roster_date": row.roster_date.isoformat(),
        "shift": row.shift,
        "department_id": str(row.department_id),
        "room": row.room,
        "assigned_doctor_id": str(row.assigned_doctor_id) if row.assigned_doctor_id else None,
        "is_present": row.is_present,
        "substitute_user_id": str(row.substitute_user_id) if row.substitute_user_id else None,
        "substitution_reason": row.substitution_reason,
        "is_active": row.is_active,
    }


async def _validate_active_nurse_in_tenant(user_id: uuid.UUID, current_user: dict, session: AsyncSession) -> User:
    user = await session.get(User, user_id)
    if not user or not user.is_active or user.role != "nurse":
        raise HTTPException(status_code=422, detail="user_id must reference an active nurse")
    if str(user.tenant_id) != str(current_user.get("tenant_id")):
        # Cross-tenant nurse IDs are denied without confirming/denying existence.
        raise HTTPException(status_code=404, detail="Nurse not found")
    return user


async def _validate_department(department_id: uuid.UUID, session: AsyncSession) -> Department:
    dept = await session.get(Department, department_id)
    if not dept or not dept.is_active:
        raise HTTPException(status_code=404, detail="Department not found or inactive")
    return dept


async def _validate_doctor(doctor_id: uuid.UUID, session: AsyncSession) -> Doctor:
    doctor = await session.get(Doctor, doctor_id)
    if not doctor or not doctor.is_active:
        raise HTTPException(status_code=404, detail="Doctor not found or inactive")
    return doctor


async def _validate_substitute(
    substitute_user_id: Optional[uuid.UUID],
    substitution_reason: Optional[str],
    original_user_id: uuid.UUID,
    current_user: dict,
    session: AsyncSession,
) -> None:
    if substitute_user_id is None:
        return
    if str(substitute_user_id) == str(original_user_id):
        raise HTTPException(status_code=422, detail="Substitute nurse cannot be the same as the original nurse")
    if not substitution_reason or not substitution_reason.strip():
        raise HTTPException(status_code=422, detail="Substitution reason is required when a substitute nurse is assigned")
    await _validate_active_nurse_in_tenant(substitute_user_id, current_user, session)


async def _check_duplicate(
    user_id: uuid.UUID, roster_date: date, shift: str, session: AsyncSession, exclude_id: Optional[uuid.UUID] = None,
) -> None:
    filters = [
        NurseRoster.user_id == user_id,
        NurseRoster.roster_date == roster_date,
        NurseRoster.shift == shift,
        NurseRoster.is_active == True,  # noqa: E712
    ]
    if exclude_id is not None:
        filters.append(NurseRoster.id != exclude_id)
    duplicate = (await session.execute(select(NurseRoster).where(*filters))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Nurse already has an active roster entry for this date and shift")


async def _enrich(row: NurseRoster, session: AsyncSession) -> NurseRosterRead:
    result = NurseRosterRead.model_validate(row)
    nurse = await session.get(User, row.user_id)
    substitute = await session.get(User, row.substitute_user_id) if row.substitute_user_id else None
    dept = await session.get(Department, row.department_id)
    doctor = await session.get(Doctor, row.assigned_doctor_id) if row.assigned_doctor_id else None
    result.nurse_name = nurse.full_name if nurse else None
    result.substitute_name = substitute.full_name if substitute else None
    result.department_name = dept.name if dept else None
    result.doctor_name = doctor.full_name if doctor else None
    return result


@router.get("", response_model=List[NurseRosterRead])
async def list_roster(
    roster_date: Optional[date] = Query(None),
    date_from: Optional[date] = Query(None, description="Weekly-view range start (inclusive)"),
    date_to: Optional[date] = Query(None, description="Weekly-view range end (inclusive)"),
    department_id: Optional[uuid.UUID] = Query(None),
    shift: Optional[str] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None, description="Hospital Admin only — filter by nurse"),
    include_inactive: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "hospital_admin")),
):
    filters = []
    if roster_date:
        filters.append(NurseRoster.roster_date == roster_date)
    if date_from and date_to:
        filters.append(NurseRoster.roster_date.between(date_from, date_to))
    if department_id:
        filters.append(NurseRoster.department_id == department_id)
    if shift:
        filters.append(NurseRoster.shift == shift)
    if not include_inactive:
        filters.append(NurseRoster.is_active == True)  # noqa: E712
    if current_user.get("role") == "nurse":
        # A Nurse may only ever see their own roster — including entries where
        # they are recorded as the substitute.
        own_id = uuid.UUID(current_user["sub"])
        filters.append(or_(NurseRoster.user_id == own_id, NurseRoster.substitute_user_id == own_id))
    elif user_id:
        filters.append(NurseRoster.user_id == user_id)
    rows = (await session.execute(
        select(NurseRoster).where(and_(*filters)).order_by(NurseRoster.roster_date, NurseRoster.shift)
    )).scalars().all()
    return [await _enrich(row, session) for row in rows]


@router.post("", response_model=NurseRosterRead, status_code=status.HTTP_201_CREATED)
async def create_roster(
    payload: NurseRosterCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    await _validate_active_nurse_in_tenant(payload.user_id, current_user, session)
    await _validate_department(payload.department_id, session)
    if payload.assigned_doctor_id:
        await _validate_doctor(payload.assigned_doctor_id, session)
    await _validate_substitute(payload.substitute_user_id, payload.substitution_reason, payload.user_id, current_user, session)
    await _check_duplicate(payload.user_id, payload.roster_date, payload.shift, session)

    row = NurseRoster(id=uuid.uuid4(), **payload.model_dump())
    session.add(row)
    await session.flush()
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="nurse_roster",
        resource_id=row.id,
        new_value=_values(row),
    )
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

    old_value = _values(row)
    changes = payload.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)

    if "user_id" in changes:
        await _validate_active_nurse_in_tenant(changes["user_id"], current_user, session)
    if "department_id" in changes:
        await _validate_department(changes["department_id"], session)
    if "assigned_doctor_id" in changes and changes["assigned_doctor_id"] is not None:
        await _validate_doctor(changes["assigned_doctor_id"], session)

    next_substitute = changes.get("substitute_user_id", row.substitute_user_id)
    next_reason = changes.get("substitution_reason", row.substitution_reason)
    next_user_id = changes.get("user_id", row.user_id)
    if "substitute_user_id" in changes or "substitution_reason" in changes:
        await _validate_substitute(next_substitute, next_reason, next_user_id, current_user, session)

    if "user_id" in changes or "roster_date" in changes or "shift" in changes:
        await _check_duplicate(
            changes.get("user_id", row.user_id),
            changes.get("roster_date", row.roster_date),
            changes.get("shift", row.shift),
            session,
            exclude_id=row.id,
        )

    for field, value in changes.items():
        setattr(row, field, value)

    if changes.get("is_active") is False:
        action = "DEACTIVATE"
    elif set(changes.keys()) == {"is_present"}:
        action = "ATTENDANCE_RECORDED"
    else:
        action = "UPDATE"

    record_audit(
        session,
        current_user=current_user,
        action=action,
        resource_type="nurse_roster",
        resource_id=row.id,
        old_value=old_value,
        new_value=_values(row),
        reason=reason,
    )
    await session.commit()
    await session.refresh(row)
    return await _enrich(row, session)
