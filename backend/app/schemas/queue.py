import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class QueueTokenCreate(BaseModel):
    patient_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    queue_type: str = "registration"   # registration | vitals | consultation | pharmacy | billing
    priority: Literal["normal", "senior_citizen", "pregnant", "disabled", "urgent", "emergency"] = "normal"
    priority_reason: Optional[str] = None
    waive_fee: bool = False            # True = follow-up within 7 days, skip invoice/Razorpay


class QueueTokenRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    token_no: int
    queue_type: str
    priority: str
    priority_reason: Optional[str] = None
    priority_assigned_by: Optional[uuid.UUID] = None
    priority_assigned_at: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    issued_at: datetime
    called_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    # Joined fields (populated in query)
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    department_name: Optional[str] = None
    doctor_name: Optional[str] = None
    visit_id: Optional[uuid.UUID] = None  # Set on issuance; used for upfront billing redirect

    model_config = {"from_attributes": True}


class QueueTokenStatusUpdate(BaseModel):
    status: str  # checked_in | completed | cancelled
    notes: Optional[str] = None  # required when status == cancelled


class CancelTokenRequest(BaseModel):
    notes: str  # mandatory cancellation reason


class QueueTokenUpdate(BaseModel):
    department_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    priority: Optional[Literal["normal", "senior_citizen", "pregnant", "disabled", "urgent", "emergency"]] = None
    priority_reason: Optional[str] = None
