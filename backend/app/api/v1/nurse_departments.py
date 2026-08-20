"""
Nurse-Department Assignments API — hospital_admin assigns nurses to departments.
A nurse can be assigned to multiple departments simultaneously.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role, require_feature
from app.db.engine import get_session
from app.models.tenant.department import Department
from app.models.tenant.nurse_department import NurseDepartment
from app.schemas.nurse_department import NurseDepartmentAssign, NurseDepartmentRead

router = APIRouter(dependencies=[Depends(require_feature("nurse_roster"))])


async def _enrich(nd: NurseDepartment, session: AsyncSession) -> NurseDepartmentRead:
    item = NurseDepartmentRead.model_validate(nd)
    dept = await session.get(Department, nd.department_id)
    item.department_name = dept.name if dept else None
    return item


@router.get("", response_model=List[NurseDepartmentRead])
async def list_assignments(
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin", "nurse")),
):
    """List all nurse-department assignments for this tenant."""
    rows = (await session.execute(select(NurseDepartment))).scalars().all()
    return [await _enrich(nd, session) for nd in rows]


@router.post("", response_model=NurseDepartmentRead, status_code=status.HTTP_201_CREATED)
async def assign_nurse(
    payload: NurseDepartmentAssign,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    """Assign a nurse to a department. A nurse may hold multiple department assignments."""
    dept = await session.get(Department, payload.department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    # Idempotent — do not duplicate if already assigned
    existing = (await session.execute(
        select(NurseDepartment).where(
            NurseDepartment.user_id == payload.user_id,
            NurseDepartment.department_id == payload.department_id,
        )
    )).scalar_one_or_none()
    if existing:
        return await _enrich(existing, session)

    nd = NurseDepartment(
        id=uuid.uuid4(),
        user_id=payload.user_id,
        department_id=payload.department_id,
        assigned_by=uuid.UUID(current_user["sub"]),
    )
    session.add(nd)
    await session.commit()
    await session.refresh(nd)
    return await _enrich(nd, session)


@router.delete("/{user_id}/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_nurse_from_dept(
    user_id: uuid.UUID,
    department_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    """Remove a nurse's assignment from a specific department."""
    nd = (await session.execute(
        select(NurseDepartment).where(
            NurseDepartment.user_id == user_id,
            NurseDepartment.department_id == department_id,
        )
    )).scalar_one_or_none()
    if not nd:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await session.delete(nd)
    await session.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_nurse_all(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    """Remove ALL department assignments for a nurse."""
    rows = (await session.execute(
        select(NurseDepartment).where(NurseDepartment.user_id == user_id)
    )).scalars().all()
    for nd in rows:
        await session.delete(nd)
    await session.commit()


@router.get("/my", response_model=List[NurseDepartmentRead])
async def my_departments(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "hospital_admin", "super_admin")),
):
    """Returns all departments assigned to the currently authenticated nurse."""
    user_id = uuid.UUID(current_user["sub"])
    rows = (await session.execute(
        select(NurseDepartment).where(NurseDepartment.user_id == user_id)
    )).scalars().all()
    return [await _enrich(nd, session) for nd in rows]

