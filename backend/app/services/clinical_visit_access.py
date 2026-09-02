import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.doctor import Doctor
from app.models.tenant.visit import Visit


async def authorized_clinical_visit(
    session: AsyncSession,
    *,
    visit_id: uuid.UUID,
    current_user: dict,
    facility_id: uuid.UUID | None,
) -> Visit:
    stmt = select(Visit).where(Visit.id == visit_id)
    if facility_id is not None:
        stmt = stmt.where(Visit.facility_id == facility_id)
    visit = await session.scalar(stmt)
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    if current_user.get("role") != "doctor" or facility_id is None:
        return visit

    doctor_id = await session.scalar(select(Doctor.id).where(
        Doctor.user_id == uuid.UUID(current_user["sub"]),
        Doctor.is_active.is_(True),
    ))
    if doctor_id is None:
        raise HTTPException(status_code=403, detail="Doctor account is not linked to an active Doctor record")
    if visit.doctor_id != doctor_id:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit