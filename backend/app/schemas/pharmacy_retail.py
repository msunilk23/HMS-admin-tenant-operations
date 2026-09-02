import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RetailMedicineRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    strength: Optional[str] = None
    requires_prescription: bool
    is_controlled_drug: bool
    available_quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal


class RetailSaleItemCreate(BaseModel):
    medicine_product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    prescribed_quantity: Optional[Decimal] = Field(default=None, gt=0)
    dose_units: Optional[Decimal] = Field(default=None, gt=0)
    frequency_per_day: Optional[Decimal] = Field(default=None, gt=0)
    duration_days: Optional[int] = Field(default=None, gt=0)


class RetailSaleCreate(BaseModel):
    classification: Literal["OTC", "EXTERNAL_PRESCRIPTION"]
    pharmacy_location_id: uuid.UUID
    patient_id: Optional[uuid.UUID] = None
    patient_name: Optional[str] = Field(default=None, max_length=200)
    patient_date_of_birth: Optional[date] = None
    patient_age: Optional[int] = Field(default=None, ge=0, le=150)
    patient_gender: Optional[str] = Field(default=None, max_length=30)
    patient_mobile: Optional[str] = Field(default=None, max_length=30)
    patient_address: Optional[str] = Field(default=None, max_length=1000)
    government_id_type: Optional[str] = Field(default=None, max_length=50)
    government_id_last_four: Optional[str] = Field(default=None, min_length=4, max_length=4)
    prescriber_name: Optional[str] = Field(default=None, max_length=200)
    prescriber_registration_number: Optional[str] = Field(default=None, max_length=100)
    prescription_date: Optional[date] = None
    issuing_facility: Optional[str] = Field(default=None, max_length=200)
    prescription_reference: Optional[str] = Field(default=None, max_length=100)
    prescription_attachment_reference: Optional[str] = Field(default=None, max_length=1000)
    original_prescription_inspected: bool = False
    items: list[RetailSaleItemCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity_shape(self):
        if self.classification == "OTC" and (self.government_id_type or self.government_id_last_four):
            raise ValueError("Government identification must not be collected for OTC sales")
        return self


class RetailSaleDispense(BaseModel):
    payment_method: Literal["CASH", "CARD", "UPI"]
    payment_reference: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_payment_reference(self):
        if self.payment_method != "CASH" and not self.payment_reference:
            raise ValueError("A payment reference is required for non-cash payment")
        return self


class RetailSaleItemRead(BaseModel):
    id: uuid.UUID
    medicine_product_id: uuid.UUID
    medicine_name_snapshot: str
    quantity: Decimal
    prescribed_quantity: Optional[Decimal]
    prescribed_duration_days: Optional[int]
    requires_prescription: bool
    is_controlled_drug: bool
    unit_price: Decimal
    gst_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class RetailSaleRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID
    classification: str
    status: str
    controlled_sale: bool
    patient_id: Optional[uuid.UUID]
    customer_reference: str
    verified_by: Optional[uuid.UUID]
    verified_at: Optional[datetime]
    dispensed_by: Optional[uuid.UUID]
    dispensed_at: Optional[datetime]
    subtotal: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal
    payment_method: Optional[str]
    payment_status: str
    payment_reference: Optional[str]
    receipt_number: Optional[str]
    items: list[RetailSaleItemRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RetailConfigurationWrite(BaseModel):
    non_controlled_validity_days: int = Field(default=30, ge=1, le=30)
    non_controlled_max_supply_days: int = Field(default=30, ge=1, le=30)
    controlled_validity_days: int = Field(default=7, ge=1, le=7)
    controlled_max_supply_days: int = Field(default=7, ge=1, le=7)


class RetailConfigurationRead(RetailConfigurationWrite):
    id: Optional[uuid.UUID] = None
    tenant_id: uuid.UUID
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PharmacistAuthorizationCreate(BaseModel):
    user_id: uuid.UUID
    pharmacy_location_id: uuid.UUID


class PharmacistAuthorizationRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID
    user_id: uuid.UUID
    is_active: bool

    model_config = {"from_attributes": True}


class RetailReturnAllocationCreate(BaseModel):
    sale_allocation_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class RetailReturnCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)
    allocations: list[RetailReturnAllocationCreate] = Field(min_length=1)


class RetailReturnRead(BaseModel):
    id: uuid.UUID
    sale_id: uuid.UUID
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID
    return_number: str
    classification: str
    status: str
    reason: str
    total_quantity: Decimal
    refund_amount: Decimal
    processed_by: uuid.UUID
    processed_at: datetime

    model_config = {"from_attributes": True}