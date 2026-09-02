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
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_facility_id
from app.core.dependencies import require_feature, require_role
from app.db.engine import get_session
from app.models.public.user import User
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.nurse_roster import NurseRoster
from app.schemas.nurse_roster import NurseRosterAuditRead, NurseRosterCreate, NurseRosterRead, NurseRosterUpdate
from app.services.audit_service import record_audit

router = APIRouter(dependencies=[Depends(require_feature("nurse_roster"))])

# Hospital Admin is the sole tenant role that manages rosters. Super Admin is
# intentionally excluded here as a matter of contract, not just because the
# router-level tenant guard already denies it.
_ADMIN_ROLES = ("hospital_admin",)


def _values(row: NurseRoster) -> dict:
    return {
        "facility_id": str(row.facility_id),
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


async def _check_overlap(
    *,
    user_id: uuid.UUID,
    substitute_user_id: Optional[uuid.UUID],
    roster_date: date,
    shift: str,
    facility_id: uuid.UUID,
    session: AsyncSession,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    participant_ids = sorted({user_id, *([substitute_user_id] if substitute_user_id else [])}, key=str)
    if session.bind and session.bind.dialect.name == "postgresql":
        for participant_id in participant_ids:
            lock_key = f"nurse-roster:{facility_id}:{participant_id}:{roster_date}:{shift}"
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )
    filters = [
        NurseRoster.facility_id == facility_id,
        NurseRoster.roster_date == roster_date,
        NurseRoster.shift == shift,
        NurseRoster.is_active == True,  # noqa: E712
        or_(
            NurseRoster.user_id.in_(participant_ids),
            NurseRoster.substitute_user_id.in_(participant_ids),
        ),
    ]
    if exclude_id is not None:
        filters.append(NurseRoster.id != exclude_id)
    overlap = (await session.execute(select(NurseRoster).where(*filters).limit(1))).scalar_one_or_none()
    if overlap:
        raise HTTPException(status_code=409, detail="A nurse already has an overlapping active assignment for this date and shift")


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
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    filters = [NurseRoster.facility_id == facility_id]
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


@router.get("/audit/history", response_model=List[NurseRosterAuditRead])
async def roster_audit_history(
    roster_id: Optional[uuid.UUID] = None,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*_ADMIN_ROLES)),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    stmt = select(AuditLog).where(
        AuditLog.resource_type == "nurse_roster",
        or_(
            AuditLog.old_value["facility_id"].astext == str(facility_id),
            AuditLog.new_value["facility_id"].astext == str(facility_id),
        ),
    )
    if roster_id:
        stmt = stmt.where(AuditLog.resource_id == str(roster_id))
    return (await session.execute(stmt.order_by(AuditLog.timestamp.desc()).limit(limit))).scalars().all()


@router.post("", response_model=NurseRosterRead, status_code=status.HTTP_201_CREATED)
async def create_roster(
    payload: NurseRosterCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    await _validate_active_nurse_in_tenant(payload.user_id, current_user, session)
    await _validate_department(payload.department_id, session)
    if payload.assigned_doctor_id:
        await _validate_doctor(payload.assigned_doctor_id, session)
    await _validate_substitute(payload.substitute_user_id, payload.substitution_reason, payload.user_id, current_user, session)
    await _check_overlap(
        user_id=payload.user_id,
        substitute_user_id=payload.substitute_user_id,
        roster_date=payload.roster_date,
        shift=payload.shift,
        facility_id=facility_id,
        session=session,
    )

    row = NurseRoster(id=uuid.uuid4(), facility_id=facility_id, **payload.model_dump())
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
    facility_id: uuid.UUID = Depends(get_facility_id),
):
    row = await session.scalar(select(NurseRoster).where(
        NurseRoster.id == roster_id,
        NurseRoster.facility_id == facility_id,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="Roster entry not found")

    old_value = _values(row)
    changes = payload.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    if changes.get("is_active") is False and (not reason or not reason.strip()):
        raise HTTPException(status_code=422, detail="Deactivation reason is required")

    if "user_id" in changes:
        await _validate_active_nurse_in_tenant(changes["user_id"], current_user, session)
    if "department_id" in changes:
        await _validate_department(changes["department_id"], session)
    if "assigned_doctor_id" in changes and changes["assigned_doctor_id"] is not None:
        await _validate_doctor(changes["assigned_doctor_id"], session)

    next_substitute = changes.get("substitute_user_id", row.substitute_user_id)
    next_reason = changes.get("substitution_reason", row.substitution_reason)
    next_user_id = changes.get("user_id", row.user_id)
    reactivating = changes.get("is_active") is True and not row.is_active
    if reactivating or "substitute_user_id" in changes or "substitution_reason" in changes:
        await _validate_active_nurse_in_tenant(next_user_id, current_user, session)
        await _validate_substitute(next_substitute, next_reason, next_user_id, current_user, session)

    if reactivating or {"user_id", "substitute_user_id", "roster_date", "shift"}.intersection(changes):
        await _check_overlap(
            user_id=changes.get("user_id", row.user_id),
            substitute_user_id=changes.get("substitute_user_id", row.substitute_user_id),
            roster_date=changes.get("roster_date", row.roster_date),
            shift=changes.get("shift", row.shift),
            facility_id=facility_id,
            session=session,
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
