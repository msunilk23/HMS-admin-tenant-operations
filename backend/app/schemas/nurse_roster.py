import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator


_VALID_SHIFTS = {"morning", "afternoon", "night"}


class NurseRosterCreate(BaseModel):
    user_id: uuid.UUID
    roster_date: date
    shift: str
    department_id: uuid.UUID
    room: Optional[str] = None
    assigned_doctor_id: Optional[uuid.UUID] = None
    is_present: bool = False
    substitute_user_id: Optional[uuid.UUID] = None
    substitution_reason: Optional[str] = None

    @field_validator("shift")
    @classmethod
    def valid_shift(cls, value: str) -> str:
        if value not in _VALID_SHIFTS:
            raise ValueError("shift must be morning, afternoon, or night")
        return value


class NurseRosterUpdate(BaseModel):
    roster_date: Optional[date] = None
    shift: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    room: Optional[str] = None
    assigned_doctor_id: Optional[uuid.UUID] = None
    is_present: Optional[bool] = None
    substitute_user_id: Optional[uuid.UUID] = None
    substitution_reason: Optional[str] = None
    is_active: Optional[bool] = None
    reason: Optional[str] = None  # audit-only note (e.g. why deactivated) — not persisted on the row

    @field_validator("shift")
    @classmethod
    def valid_shift(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _VALID_SHIFTS:
            raise ValueError("shift must be morning, afternoon, or night")
        return value


class NurseRosterRead(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    user_id: uuid.UUID
    roster_date: date
    shift: str
    department_id: uuid.UUID
    room: Optional[str] = None
    assigned_doctor_id: Optional[uuid.UUID] = None
    is_present: bool
    substitute_user_id: Optional[uuid.UUID] = None
    substitution_reason: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    nurse_name: Optional[str] = None
    substitute_name: Optional[str] = None
    department_name: Optional[str] = None
    doctor_name: Optional[str] = None

    model_config = {"from_attributes": True}


class NurseRosterAuditRead(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    action: str
    resource_id: Optional[str] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    reason: Optional[str] = None
    timestamp: datetime

    model_config = {"from_attributes": True}
