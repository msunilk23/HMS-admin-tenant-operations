"""
Doctors API — list (public) + admin CRUD.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.security import hash_password
from app.core.sms import send_doctor_credentials
from app.core.username import generate_username
from app.db.engine import get_session
from app.models.public.user import Tenant, User
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorOnboard, DoctorRead, DoctorUpdate

router = APIRouter()


async def _enrich(doctor: Doctor, session: AsyncSession) -> DoctorRead:
    """Attach department_name and username to a DoctorRead."""
    read = DoctorRead.model_validate(doctor)
    if doctor.department_id:
        dept = await session.get(Department, doctor.department_id)
        read.department_name = dept.name if dept else None
    # Fetch username from linked user account
    user = await session.get(User, doctor.user_id)
    if user:
        read.username = user.username
        read.phone = user.phone
    return read


@router.get("", response_model=List[DoctorRead])
async def list_doctors(
    include_inactive: bool = False,
    department_id: Optional[uuid.UUID] = None,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(
        "receptionist", "nurse", "doctor", "billing_officer",
        "hospital_admin", "super_admin",
    )),
):
    stmt = select(Doctor).order_by(Doctor.full_name)
    if not include_inactive:
        stmt = stmt.where(Doctor.is_active == True)  # noqa: E712
    if department_id:
        stmt = stmt.where(Doctor.department_id == department_id)
    doctors = (await session.execute(stmt)).scalars().all()
    return [await _enrich(d, session) for d in doctors]


@router.post("", response_model=DoctorRead, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    payload: DoctorCreate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    doctor = Doctor(id=uuid.uuid4(), **payload.model_dump())
    session.add(doctor)
    await session.commit()
    await session.refresh(doctor)
    return await _enrich(doctor, session)


@router.post("/onboard", response_model=DoctorRead, status_code=status.HTTP_201_CREATED)
async def onboard_doctor(
    payload: DoctorOnboard,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    """Create a doctor login account + doctor profile in one step."""
    # Resolve tenant from JWT
    tenant_schema: str = current_user.get("tenant_schema", "")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.schema_name == tenant_schema)
    )).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")

    # Auto-generate password if not provided
    temp_password = payload.password or "Password@123"

    # Check if a user with this email already exists
    existing_user = (await session.execute(
        select(User).where(User.email == payload.email)
    )).scalar_one_or_none()

    if existing_user:
        # Idempotency: if the user exists but has no doctor profile (partial insert
        # from a previous failed attempt), create just the doctor profile.
        existing_doctor = (await session.execute(
            select(Doctor).where(Doctor.user_id == existing_user.id)
        )).scalar_one_or_none()
        if existing_doctor:
            raise HTTPException(
                status_code=409,
                detail="A doctor profile already exists for this email"
            )
        # Resume: attach the doctor profile to the existing user account.
        existing_user.hashed_password = hash_password(temp_password)
        existing_user.must_change_password = True
        existing_user.password_changed_at = None
        new_user = existing_user
        username = existing_user.username
    else:
        # Resolve username
        username = payload.username or await generate_username(payload.full_name, session)
        # Ensure username uniqueness if caller supplied one manually
        if payload.username:
            username_taken = (await session.execute(
                select(User).where(User.username == username)
            )).scalar_one_or_none()
            if username_taken:
                raise HTTPException(status_code=409, detail=f"Username '{username}' is already taken")

        # Create user account with doctor role
        new_user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            tenant_name=tenant_schema,
            email=payload.email,
            username=username,
            phone=payload.phone,
            hashed_password=hash_password(temp_password),
            full_name=payload.full_name,
            role="doctor",
            must_change_password=True,
            password_changed_at=None,
        )
        session.add(new_user)
        await session.flush()  # get new_user.id

    # Create doctor profile
    doctor = Doctor(
        id=uuid.uuid4(),
        user_id=new_user.id,
        full_name=payload.full_name,
        specialization=payload.specialization,
        department_id=payload.department_id,
        consultation_fee=payload.consultation_fee,
        qualification=payload.qualification,
        experience_years=payload.experience_years,
    )
    session.add(doctor)
    await session.commit()
    await session.refresh(doctor)
    enriched = await _enrich(doctor, session)

    # Send credentials via SMS — non-blocking (errors are logged, never raised)
    send_doctor_credentials(
        to_phone=new_user.phone,
        full_name=new_user.full_name,
        username=new_user.username,
        password=temp_password,
        hospital_name=tenant.hospital_name if tenant else tenant_schema,
        send_via=payload.send_via,
    )

    enriched.temp_password = temp_password
    return enriched


@router.get("/{doctor_id}", response_model=DoctorRead)
async def get_doctor(
    doctor_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(
        "receptionist", "nurse", "doctor", "hospital_admin", "super_admin",
    )),
):
    doctor = await session.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return await _enrich(doctor, session)


@router.patch("/{doctor_id}", response_model=DoctorRead)
async def update_doctor(
    doctor_id: uuid.UUID,
    payload: DoctorUpdate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    doctor = await session.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(doctor, field, value)
    await session.commit()
    await session.refresh(doctor)
    return await _enrich(doctor, session)
