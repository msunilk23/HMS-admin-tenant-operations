import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr


class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    dob: Optional[date] = None
    age: Optional[int] = None
    gender: str  # male | female | other
    phone: str
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    blood_group: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_id: Optional[str] = None
    aadhar_number: str  # exactly 12 digits, required
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    # Set true to proceed after a duplicate warning has been shown to the user.
    override_duplicate: bool = False


class PatientRead(BaseModel):
    id: uuid.UUID
    uhid: str
    first_name: str
    last_name: str
    dob: Optional[date] = None
    age: Optional[int] = None
    gender: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    blood_group: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_id: Optional[str] = None
    aadhar_number: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    dob: Optional[date] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    blood_group: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_id: Optional[str] = None
    aadhar_number: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None


class PatientDuplicateCandidate(BaseModel):
    id: uuid.UUID
    uhid: str
    first_name: str
    last_name: str
    phone: str
    dob: Optional[date] = None
    aadhar_number: Optional[str] = None
    matched_on: List[str]

    model_config = {"from_attributes": True}


# ── Patient History (for doctor consultation view) ──────────────────────────

class PatientHistoryConsultation(BaseModel):
    chief_complaint: Optional[str] = None
    examination: Optional[str] = None
    diagnosis_icd10: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None


class PatientHistoryLabResult(BaseModel):
    results: Optional[Dict[str, Any]] = None
    reported_at: datetime
    report_url: Optional[str] = None


class PatientHistoryLabOrder(BaseModel):
    id: Optional[uuid.UUID] = None
    tests: Optional[List[Dict[str, Any]]] = None
    status: str
    result: Optional[PatientHistoryLabResult] = None


class PatientHistoryItem(BaseModel):
    visit_id: uuid.UUID
    visit_date: datetime
    status: str
    doctor_name: Optional[str] = None
    department_name: Optional[str] = None
    consultation: Optional[PatientHistoryConsultation] = None
    medicines: Optional[List[Dict[str, Any]]] = None
    prescription_instructions: Optional[str] = None
    lab_orders: List[PatientHistoryLabOrder] = []
