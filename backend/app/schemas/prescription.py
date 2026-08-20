import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MedicineItem(BaseModel):
    medicine: str
    strength: Optional[str] = None
    dose: Optional[str] = None
    route: str = "oral"
    frequency: Optional[str] = None
    duration: Optional[str] = None
    quantity: Optional[str] = None
    instructions: Optional[str] = None


class LabTestItem(BaseModel):
    test_name: str
    notes: Optional[str] = None


class PrescriptionItemRead(BaseModel):
    id: uuid.UUID
    prescription_id: uuid.UUID
    medicine: str
    strength: Optional[str] = None
    dose: Optional[str] = None
    route: Optional[str] = "oral"
    frequency: Optional[str] = None
    duration: Optional[str] = None
    quantity: Optional[str] = None
    instructions: Optional[str] = None

    model_config = {"from_attributes": True}


class PrescriptionCreate(BaseModel):
    visit_id: uuid.UUID
    consultation_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    items: Optional[List[MedicineItem]] = None
    medicines: Optional[List[MedicineItem]] = None
    instructions: Optional[str] = None
    lab_tests: Optional[List[LabTestItem]] = None  # doctor can include lab tests with prescription


class PrescriptionUpdate(BaseModel):
    consultation_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    items: Optional[List[MedicineItem]] = None
    medicines: Optional[List[MedicineItem]] = None
    instructions: Optional[str] = None
    lab_tests: Optional[List[LabTestItem]] = None


class PrescriptionRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    consultation_id: Optional[uuid.UUID] = None
    doctor_id: Optional[uuid.UUID] = None
    status: str = "finalized"
    items: Optional[List[PrescriptionItemRead]] = None
    medicines: Optional[List[Dict[str, Any]]] = None
    instructions: Optional[str] = None
    lab_tests: Optional[List[Dict[str, Any]]] = None
    created_at: datetime

    model_config = {"from_attributes": True}
