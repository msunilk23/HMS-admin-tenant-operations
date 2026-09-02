import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class LabTestItem(BaseModel):
    """Controlled Lab Test Master reference. Free-text ordering is not
    accepted for new orders; legacy free-text rows (test_id absent) remain
    readable via LabOrderRead only."""
    test_id: uuid.UUID
    notes: Optional[str] = None


class LabOrderCreate(BaseModel):
    visit_id: uuid.UUID
    tests: List[LabTestItem]


class LabOrderRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    facility_id: Optional[uuid.UUID] = None
    tests: Optional[list] = None
    status: str
    ordered_at: datetime
    # Joined
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    result: Optional["LabResultRead"] = None

    model_config = {"from_attributes": True}


class NurseLabOrderRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    visit_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    doctor_name: Optional[str] = None
    tests: list[dict[str, Any]]
    ordered_at: datetime
    collection_status: str
    sample_collected_at: Optional[datetime] = None
    status: str
    critical_result: bool


class ReceptionLabOrderRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    visit_id: uuid.UUID
    appointment_id: Optional[uuid.UUID] = None
    test_names: list[str]
    collection_completed: bool
    status: str


class LabResultCreate(BaseModel):
    results: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    critical_flags: Optional[Dict[str, bool]] = None  # {test_code: is_critical}


class LabResultRead(BaseModel):
    id: uuid.UUID
    lab_order_id: uuid.UUID
    results: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    critical_flags: Optional[Dict[str, bool]] = None
    report_url: Optional[str] = None
    reported_by_user_id: Optional[uuid.UUID] = None
    reported_at: datetime
    verified_by_user_id: Optional[uuid.UUID] = None
    verified_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
