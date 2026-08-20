from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class VisitTATRead(BaseModel):
    registered_at: Optional[datetime] = None
    nurse_queue_at: Optional[datetime] = None
    nurse_called_at: Optional[datetime] = None
    pre_vital_started_at: Optional[datetime] = None
    pre_vital_completed_at: Optional[datetime] = None
    doctor_queue_at: Optional[datetime] = None
    doctor_called_at: Optional[datetime] = None
    consultation_started_at: Optional[datetime] = None
    consultation_completed_at: Optional[datetime] = None
    billing_started_at: Optional[datetime] = None
    billing_completed_at: Optional[datetime] = None
    registration_to_nurse_queue_seconds: Optional[float] = None
    nurse_wait_seconds: Optional[float] = None
    pre_vitals_seconds: Optional[float] = None
    doctor_wait_seconds: Optional[float] = None
    consultation_seconds: Optional[float] = None
    total_opd_seconds: Optional[float] = None
    lab_wait_seconds: Optional[float] = None
    pharmacy_wait_seconds: Optional[float] = None
    billing_seconds: Optional[float] = None
