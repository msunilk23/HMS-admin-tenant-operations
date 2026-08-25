"""
Doctors API — list (public) + admin CRUD.
"""
import uuid
from typing import List, Optional

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.security import hash_password, generate_temp_password
from app.core.sms import send_doctor_credentials
from app.core.redis_client import allow_tenant_admin_password_reset
from app.core.username import generate_username
from app.db.engine import get_session
from app.models.public.user import Tenant, User
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.doctor_schedule import DoctorSchedule
from app.schemas.doctor_reset import DoctorPasswordResetRequest, DoctorPasswordResetResponse
from app.services.audit_service import record_audit
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
    _: dict = Depends(require_role("hospital_admin")),
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
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Create a doctor login account + doctor profile in one step."""
    # Resolve tenant from JWT
    tenant_schema: str = current_user.get("tenant_schema", "")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.schema_name == tenant_schema)
    )).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")
    schedule_payloads = payload.schedules
    if schedule_payloads and payload.schedule_later:
        raise HTTPException(status_code=422, detail="Choose schedules now or schedule later, not both")
    if any(schedule_payload.doctor_id is not None for schedule_payload in schedule_payloads):
        raise HTTPException(status_code=422, detail="Onboarding schedules must not include doctor_id")
    if payload.department_id is not None:
        department = (await session.execute(select(Department).where(Department.id == payload.department_id, Department.is_active == True))).scalar_one_or_none()  # noqa: E712
        if not department:
            raise HTTPException(status_code=404, detail="Department not found")

    # Auto-generate password if not provided
    temp_password = payload.password or generate_temp_password()

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
        if existing_user.tenant_id != tenant.id or existing_user.role != "doctor":
            raise HTTPException(status_code=409, detail="An account already exists for this email")
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
    await session.flush()
    if schedule_payloads:
        existing_ranges: list[tuple] = []
        for schedule_payload in schedule_payloads:
            if any(
                item.weekday == schedule_payload.weekday
                and item.start_time < schedule_payload.end_time
                and item.end_time > schedule_payload.start_time
                and (schedule_payload.effective_from is None or item.effective_to is None or schedule_payload.effective_from <= item.effective_to)
                and (schedule_payload.effective_to is None or item.effective_from is None or schedule_payload.effective_to >= item.effective_from)
                for item in existing_ranges
            ):
                raise HTTPException(status_code=409, detail="Schedule sessions overlap")
            existing_ranges.append(schedule_payload)
            session.add(DoctorSchedule(doctor_id=doctor.id, **schedule_payload.model_dump(exclude={"doctor_id"})))
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


@router.post("/{doctor_id}/reset-password", response_model=DoctorPasswordResetResponse)
async def reset_doctor_password(
    doctor_id: uuid.UUID,
    payload: DoctorPasswordResetRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Reset one doctor account inside the authenticated tenant."""
    try:
        allowed = await allow_tenant_admin_password_reset(current_user["sub"], doctor_id)
    except Exception:
        allowed = True
    if not allowed:
        raise HTTPException(status_code=429, detail="Doctor password reset rate limit exceeded")
    tenant = (await session.execute(select(Tenant).where(Tenant.schema_name == current_user.get("tenant_schema")))).scalar_one_or_none()
    doctor = (await session.execute(select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active == True).with_for_update())).scalar_one_or_none()  # noqa: E712
    if not tenant or not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    user = (await session.execute(select(User).where(User.id == doctor.user_id, User.tenant_id == tenant.id).with_for_update())).scalar_one_or_none()
    if not user or user.role != "doctor" or not user.is_active:
        raise HTTPException(status_code=404, detail="Doctor account not found")
    temporary_password = generate_temp_password()
    user.hashed_password = hash_password(temporary_password)
    user.must_change_password = True
    user.password_changed_at = None
    user.session_version = getattr(user, "session_version", 0) + 1
    user.tokens_valid_after = datetime.now(timezone.utc)
    record_audit(session, current_user=current_user, action="DOCTOR_PASSWORD_RESET", resource_type="doctor", resource_id=doctor.id, reason=payload.reason, new_value={"user_id": str(user.id), "send_via": payload.send_via})
    await session.commit()
    delivery_status = "not_requested"
    if payload.send_via != "none":
        send_doctor_credentials(to_phone=user.phone or "", full_name=user.full_name, username=user.username, password=temporary_password, hospital_name=tenant.hospital_name, send_via=payload.send_via)
        delivery_status = "sent"
    return DoctorPasswordResetResponse(message="Doctor password reset successfully", doctor_id=doctor.id, user_id=user.id, username=user.username, phone=(f"******{user.phone[-4:]}" if user.phone else None), temporary_password=temporary_password, must_change_password=True, delivery_status=delivery_status)


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
