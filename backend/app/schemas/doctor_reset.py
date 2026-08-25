import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DoctorPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=5, max_length=500)
    send_via: Literal["sms", "whatsapp", "none"] = "none"

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("reason must be at least 5 characters")
        return value


class DoctorPasswordResetResponse(BaseModel):
    message: str
    doctor_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    phone: str | None
    temporary_password: str
    must_change_password: bool
    delivery_status: Literal["sent", "failed", "not_requested"]
