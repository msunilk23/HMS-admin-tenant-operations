import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.config import settings


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class DoctorScheduleCreate(_StrictModel):
    doctor_id: uuid.UUID
    department_id: uuid.UUID | None = None
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    slot_duration_minutes: int = Field(ge=5, le=240)
    capacity: int = Field(ge=1)
    effective_from: date | None = None
    effective_to: date | None = None
    room: str | None = Field(None, max_length=100)
    appointment_type: str | None = Field("consultation", max_length=30)
    is_active: bool = True
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        if self.capacity > settings.SCHEDULE_MAX_CAPACITY:
            raise ValueError(f"capacity cannot exceed {settings.SCHEDULE_MAX_CAPACITY}")
        return self


class DoctorScheduleUpdate(_StrictModel):
    department_id: uuid.UUID | None = None
    weekday: int | None = Field(None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    slot_duration_minutes: int | None = Field(None, ge=5, le=240)
    capacity: int | None = Field(None, ge=1)
    effective_from: date | None = None
    effective_to: date | None = None
    room: str | None = Field(None, max_length=100)
    appointment_type: str | None = Field(None, max_length=30)
    is_active: bool | None = None
    notes: str | None = Field(None, max_length=2000)


class DoctorScheduleRead(_StrictModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    department_id: uuid.UUID | None
    weekday: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    capacity: int
    effective_from: date | None
    effective_to: date | None
    room: str | None
    appointment_type: str | None
    is_active: bool
    notes: str | None


class DoctorScheduleExceptionCreate(_StrictModel):
    exception_type: Literal["leave", "holiday", "block"]
    start_datetime: datetime
    end_datetime: datetime
    reason: str | None = Field(None, max_length=500)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_range(self):
        if self.start_datetime >= self.end_datetime:
            raise ValueError("start_datetime must be before end_datetime")
        return self


class DoctorScheduleExceptionUpdate(_StrictModel):
    exception_type: Literal["leave", "holiday", "block"] | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    reason: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class DoctorScheduleExceptionRead(_StrictModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    exception_type: str
    start_datetime: datetime
    end_datetime: datetime
    reason: str | None
    is_active: bool
    created_by_user_id: uuid.UUID | None


class DoctorAvailabilityDay(_StrictModel):
    date: date
    timezone: str
    slots: list["DoctorAvailableSlot"]


class DoctorAvailableSlot(_StrictModel):
    slot_time: datetime
    is_available: bool
    booked_count: int
    remaining_capacity: int
    capacity: int
    room: str | None
    appointment_type: str | None
    blocked_reason: str | None = None


DoctorAvailabilityDay.model_rebuild()
