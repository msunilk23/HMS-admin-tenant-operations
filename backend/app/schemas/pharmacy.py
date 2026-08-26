import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class PharmacyQueueRead(BaseModel):
    id: uuid.UUID
    prescription_id: uuid.UUID
    patient_id: Optional[uuid.UUID] = None
    visit_id: Optional[uuid.UUID] = None
    status: str
    notes: Optional[str] = None
    updated_at: datetime
    # Joined
    patient_name: Optional[str] = None
    medicines: Optional[list] = None      # from prescription

    model_config = {"from_attributes": True}


class PharmacyStatusUpdate(BaseModel):
    status: str   # pending | called | dispensing | dispensed | partially_dispensed | out_of_stock | cancelled
    notes: Optional[str] = None


class FormularyMedicineSearchResult(BaseModel):
    medicine_product_id: uuid.UUID
    code: str
    brand_name: Optional[str] = None
    generic_name: str
    strength: Optional[str] = None
    unit: Optional[str] = None
    dosage_form_name: str
    default_route_name: Optional[str] = None
    composition: Optional[str] = None
    is_controlled_drug: bool
    requires_prescription: bool
    is_approved: bool
    is_preferred: bool
    is_prescribable: bool
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
