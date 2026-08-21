"""
Users API — list, create, and manage tenant staff users (hospital_admin only).
Doctors are excluded; use POST /doctors/onboard instead.
"""
import uuid as _uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.security import hash_password
from app.core.sms import send_doctor_credentials, send_staff_credentials
from app.core.username import generate_username
from app.db.engine import get_session
from app.models.public.user import Tenant, User
from app.services.audit_service import record_audit

router = APIRouter()

# Roles that hospital_admin can create/manage (doctors go via /doctors/onboard)
MANAGEABLE_ROLES = {"receptionist", "nurse", "billing_officer", "hospital_admin", "lab_technician", "pharmacist", "store_manager"}


class UserCreate(BaseModel):
    email: Optional[EmailStr] = None
    phone: str = Field(..., pattern=r"^\+?[1-9]\d{9,14}$")
    password: Optional[str] = Field(
        None,
        min_length=8,
        description="Auto-generated if omitted. Will be sent via SMS.",
    )
    username: Optional[str] = Field(
        None, min_length=3, max_length=50, pattern=r"^[a-z0-9_]+$"
    )
    full_name: str = Field(..., min_length=1, max_length=255)
    role: str
    gender: Optional[str] = Field(None, pattern=r"^(male|female)$")
    send_via: str = Field("whatsapp", pattern=r"^(sms|whatsapp)$")

    @field_validator("role")
    @classmethod
    def role_must_be_manageable(cls, v: str) -> str:
        if v not in MANAGEABLE_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(MANAGEABLE_ROLES))}")
        return v

    @field_validator("username", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    role: Optional[str] = None


def _row_to_dict(r: User) -> dict:
    return {
        "id": str(r.id),
        "full_name": r.full_name,
        "email": r.email,
        "username": r.username,
        "phone": r.phone,
        "role": r.role,
        "is_active": r.is_active,
        "tenant_name": r.tenant_name,
    }


@router.get("", response_model=List[dict])
async def list_users(
    role: Optional[str] = None,
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    """Returns all non-doctor users belonging to the caller's tenant."""
    tenant_schema: str = current_user.get("tenant_schema", "")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.schema_name == tenant_schema)
    )).scalar_one_or_none()
    if not tenant:
        return []

    stmt = (
        select(User)
        .where(
            User.tenant_id == tenant.id,
            User.role != "doctor",
            User.role != "super_admin",   # super_admin is platform-level, not hospital staff
        )
        .order_by(User.full_name)
    )
    if not include_inactive:
        stmt = stmt.where(User.is_active == True)  # noqa: E712
    if role:
        stmt = stmt.where(User.role == role)

    rows = (await session.execute(stmt)).scalars().all()
    return [_row_to_dict(r) for r in rows]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Create a new staff user (non-doctor). Sends credentials via SMS."""
    tenant_schema: str = current_user.get("tenant_schema", "")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.schema_name == tenant_schema)
    )).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")

    if payload.email and (await session.execute(select(User).where(User.email == payload.email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    temp_password = payload.password or "Password@123"
    username = payload.username or await generate_username(payload.full_name, session)
    if payload.username:
        if (await session.execute(select(User).where(User.username == username))).scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Username '{username}' is already taken")

    new_user = User(
        id=_uuid.uuid4(),
        tenant_id=tenant.id,
        tenant_name=tenant_schema,
        email=payload.email,
        username=username,
        phone=payload.phone,
        hashed_password=hash_password(temp_password),
        full_name=payload.full_name,
        role=payload.role,
        must_change_password=True,
        password_changed_at=None,
    )
    session.add(new_user)
    await session.flush()
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="user",
        resource_id=new_user.id,
        new_value={"role": new_user.role, "is_active": new_user.is_active, "username": new_user.username},
    )
    await session.commit()

    send_staff_credentials(
        to_phone=payload.phone,
        full_name=payload.full_name,
        username=username,
        password=temp_password,
        hospital_name=tenant.hospital_name,
        role=payload.role,
        gender=payload.gender or "",
        is_new=True,
        send_via=payload.send_via,
    )

    result = _row_to_dict(new_user)
    result["temp_password"] = temp_password
    return result


@router.patch("/{user_id}", response_model=dict)
async def update_user(
    user_id: _uuid.UUID,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Update a staff user's name or active status."""
    tenant_schema: str = current_user.get("tenant_schema", "")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.schema_name == tenant_schema)
    )).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")

    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant.id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "doctor":
        raise HTTPException(status_code=400, detail="Use /doctors endpoints to manage doctors")

    old_user_value = {"full_name": user.full_name, "is_active": user.is_active, "role": user.role}
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
        user.session_version += 1
        user.tokens_valid_after = datetime.now(timezone.utc)
    if payload.role is not None:
        if payload.role not in MANAGEABLE_ROLES:
            raise HTTPException(status_code=422, detail="Role is not manageable by hospital admin")
        if payload.role != user.role:
            user.role = payload.role
            user.session_version += 1
            user.tokens_valid_after = datetime.now(timezone.utc)

    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="user",
        resource_id=user.id,
        old_value=old_user_value,
        new_value={"full_name": payload.full_name if payload.full_name is not None else user.full_name,
               "is_active": payload.is_active if payload.is_active is not None else user.is_active,
               "role": user.role},
    )
    await session.commit()
    return _row_to_dict(user)


@router.post("/{user_id}/reset-password", response_model=dict)
async def reset_user_password(
    user_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Generate a new random password for a staff user and send it via SMS."""
    tenant_schema: str = current_user.get("tenant_schema", "")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.schema_name == tenant_schema)
    )).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")

    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant.id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "doctor":
        raise HTTPException(status_code=400, detail="Use /doctors endpoints to manage doctors")
    if not user.phone:
        raise HTTPException(status_code=400, detail="User has no phone number — cannot send SMS")

    new_password = "Password@123"
    user.hashed_password = hash_password(new_password)
    user.must_change_password = True
    user.password_changed_at = None
    user.session_version += 1
    user.tokens_valid_after = datetime.now(timezone.utc)
    record_audit(
        session,
        current_user=current_user,
        action="RESET_PASSWORD",
        resource_type="user",
        resource_id=user.id,
        new_value={"must_change_password": True},
    )
    await session.commit()

    send_staff_credentials(
        to_phone=user.phone,
        full_name=user.full_name,
        username=user.username,
        password=new_password,
        hospital_name=tenant.hospital_name,
        role=user.role,
        is_new=False,
    )

    return {"detail": "Password reset. New credentials sent via SMS.", "phone": user.phone}
