import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.models.tenant.visit import VisitStatus


class VisitCreate(BaseModel):
    patient_id: uuid.UUID
    doctor_id: Optional[uuid.UUID] = None
    appointment_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None


class VisitRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: Optional[uuid.UUID] = None
    appointment_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    status: VisitStatus
    created_at: datetime
    closed_at: Optional[datetime] = None
    # Joined display fields
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    department_name: Optional[str] = None
    doctor_consultation_fee: Optional[float] = None  # pre-filled on billing page
    # Queue token fields (today's token, if any)
    priority: Optional[str] = None      # emergency | senior_citizen | normal
    token_no: Optional[int] = None      # today's queue token number
    has_lab_order: Optional[bool] = None  # True if a LabOrder exists for this visit

    model_config = {"from_attributes": True}


class VisitStatusUpdate(BaseModel):
    status: VisitStatus


class VisitDispatch(BaseModel):
    """Nurse dispatch action after prescription_done."""
    action: Literal["close", "billing", "pharmacy", "lab"]
    # close    = hand prescription to patient, close visit (no extra billing)
    # billing  = send to billing for additional charges → billing_pending
    # pharmacy = send to hospital pharmacy → creates PharmacyQueue → dispatched_pharmacy
    # lab      = send to lab → activates LabOrder → dispatched_lab
    # pharmacy and lab are independent — both can be dispatched for the same visit
