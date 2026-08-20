"""
Departments API — CRUD for hospital departments.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.department import Department
from app.schemas.department import DepartmentCreate, DepartmentRead, DepartmentUpdate

router = APIRouter()


@router.get("", response_model=List[DepartmentRead])
async def list_departments(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(
        "receptionist", "nurse", "doctor", "billing_officer",
        "hospital_admin", "super_admin",
    )),
):
    stmt = select(Department).order_by(Department.name)
    if not include_inactive:
        stmt = stmt.where(Department.is_active == True)  # noqa: E712
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.post("", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    dept = Department(id=uuid.uuid4(), **payload.model_dump())
    session.add(dept)
    await session.commit()
    await session.refresh(dept)
    return dept


@router.get("/{dept_id}", response_model=DepartmentRead)
async def get_department(
    dept_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    dept = await session.get(Department, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


@router.patch("/{dept_id}", response_model=DepartmentRead)
async def update_department(
    dept_id: uuid.UUID,
    payload: DepartmentUpdate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    dept = await session.get(Department, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dept, field, value)
    await session.commit()
    await session.refresh(dept)
    return dept
