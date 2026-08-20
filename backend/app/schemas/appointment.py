import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


AppointmentStatusLiteral = Literal[
    "scheduled", "confirmed", "checked_in", "completed", "cancelled", "no_show"
]
AppointmentTypeLiteral = Literal["walkin", "phone", "online"]


class AppointmentCreate(BaseModel):
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    slot_time: datetime
    type: AppointmentTypeLiteral = "phone"
    notes: Optional[str] = Field(None, max_length=1000)


class AppointmentReschedule(BaseModel):
    slot_time: datetime
    notes: Optional[str] = Field(None, max_length=1000)


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatusLiteral


class AppointmentRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    slot_time: datetime
    status: str
    type: str
    notes: Optional[str] = None
    booked_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    # Enriched fields populated by the API layer
    patient_name: Optional[str] = None
    patient_uhid: Optional[str] = None
    doctor_name: Optional[str] = None

    model_config = {"from_attributes": True}


class CheckInBody(BaseModel):
    waive_fee: bool = False


class CheckInResult(BaseModel):
    appointment_id: uuid.UUID
    visit_id: uuid.UUID
    token_id: uuid.UUID
    token_no: int
    queue_type: str
    needs_payment: bool = False
    invoice_id: Optional[uuid.UUID] = None


class SlotInfo(BaseModel):
    slot_time: datetime
    is_available: bool
