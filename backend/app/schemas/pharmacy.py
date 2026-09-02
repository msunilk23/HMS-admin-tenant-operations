import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

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
    dispense_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class PharmacyStatusUpdate(BaseModel):
    status: str   # pending | called | dispensing | dispensed | partially_dispensed | out_of_stock | cancelled
    notes: Optional[str] = None


class PharmacyDispenseStart(BaseModel):
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID


class PharmacyDispenseRead(BaseModel):
    id: uuid.UUID
    prescription_id: uuid.UUID
    pharmacy_queue_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID
    prescription_version: int
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    classification: Literal["OPD_PRESCRIPTION"]
    status: str
    billing_status: str

    model_config = {"from_attributes": True}


class PharmacyDispenseItemRead(BaseModel):
    id: uuid.UUID
    prescription_item_id: uuid.UUID
    prescribed_name_snapshot: str
    prescribed_quantity: Decimal
    internal_confirmed_quantity: Decimal
    outside_purchase_quantity: Decimal
    status: str

    model_config = {"from_attributes": True}


class OutsidePurchaseItem(BaseModel):
    dispense_item_id: uuid.UUID
    quantity: Decimal
    reason: str


class OutsidePurchaseCreate(BaseModel):
    items: list[OutsidePurchaseItem]


class PharmacySubstitutionCreate(BaseModel):
    dispense_item_id: uuid.UUID
    dispensed_medicine_product_id: uuid.UUID
    substitution_reason: str


class PharmacyDispenseConfirm(BaseModel):
    billing_authorized: bool


class PharmacyAllocationRequest(BaseModel):
    requested_quantities: dict[uuid.UUID, Decimal] | None = None


class PharmacyReservationRelease(BaseModel):
    reason: str


class PharmacyReservationRead(BaseModel):
    id: uuid.UUID
    inventory_batch_id: uuid.UUID
    dispense_id: uuid.UUID
    dispense_item_id: uuid.UUID
    quantity: Decimal
    status: str
    expires_at: datetime
    released_at: Optional[datetime] = None
    release_reason: Optional[str] = None

    model_config = {"from_attributes": True}


class SupplierRead(BaseModel):
    id: uuid.UUID
    supplier_code: str
    supplier_name: str
    gstin: Optional[str] = None
    drug_license_no: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_days: Optional[int] = None
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class SupplierCreate(BaseModel):
    supplier_code: str
    supplier_name: str
    gstin: Optional[str] = None
    drug_license_no: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "India"
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_days: Optional[int] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    supplier_name: Optional[str] = None
    gstin: Optional[str] = None
    drug_license_no: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class SupplierImportItem(SupplierCreate):
    pass


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
