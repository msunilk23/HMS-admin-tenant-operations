import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MedicineItem(BaseModel):
    medicine: str = ""
    medicine_master_id: Optional[uuid.UUID] = None
    medicine_product_id: Optional[uuid.UUID] = None
    is_free_text: bool = False
    free_text_reason: Optional[str] = None
    strength: Optional[str] = None
    dose: Optional[str] = None
    route: str = "oral"
    frequency: Optional[str] = None
    duration: Optional[str] = None
    quantity: Optional[str] = None
    quantity_override_reason: Optional[str] = None
    dosage_form: Optional[str] = None
    timing_relative_to_food: Optional[str] = None
    instructions: Optional[str] = None


class LabTestItem(BaseModel):
    test_name: str
    notes: Optional[str] = None


class PrescriptionItemRead(BaseModel):
    id: uuid.UUID
    prescription_id: uuid.UUID
    medicine: str
    medicine_master_id: Optional[uuid.UUID] = None
    medicine_product_id: Optional[uuid.UUID] = None
    generic_name_snapshot: Optional[str] = None
    brand_name_snapshot: Optional[str] = None
    strength_snapshot: Optional[str] = None
    dosage_form_snapshot: Optional[str] = None
    route_snapshot: Optional[str] = None
    strength: Optional[str] = None
    dose: Optional[str] = None
    route: Optional[str] = "oral"
    frequency: Optional[str] = None
    duration: Optional[str] = None
    quantity: Optional[str] = None
    auto_quantity: Optional[str] = None
    final_quantity: Optional[str] = None
    quantity_override_flag: bool = False
    quantity_override_reason: Optional[str] = None
    instructions: Optional[str] = None
    dosage_form: Optional[str] = None
    timing_relative_to_food: Optional[str] = None

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
