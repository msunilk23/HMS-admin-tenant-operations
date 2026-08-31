import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PharmacyLocationCreate(BaseModel):
    location_code: str = Field(min_length=1, max_length=50)
    location_name: str = Field(min_length=1, max_length=200)

    @field_validator("location_code", "location_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class PharmacyLocationRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    facility_id: uuid.UUID
    location_code: str
    location_name: str
    location_type: str
    active: bool

    model_config = {"from_attributes": True}


class InventoryBatchRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID
    medicine_id: uuid.UUID
    batch_number: str
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    purchase_rate: Decimal
    mrp: Optional[Decimal] = None
    received_quantity: Decimal
    available_quantity: Decimal
    reserved_quantity: Decimal
    supplier_id: Optional[uuid.UUID] = None
    goods_receipt_id: Optional[uuid.UUID] = None
    goods_receipt_item_id: Optional[uuid.UUID] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StockTransactionRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    facility_id: uuid.UUID
    pharmacy_location_id: uuid.UUID
    medicine_id: uuid.UUID
    inventory_batch_id: Optional[uuid.UUID] = None
    transaction_type: str
    quantity: Decimal
    previous_balance: Decimal
    new_balance: Decimal
    reference_type: str
    reference_id: uuid.UUID
    reason: Optional[str] = None
    performed_by: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InventoryBalanceRead(BaseModel):
    tenant_id: Optional[str] = None
    facility_id: Optional[str] = None
    pharmacy_location_id: str
    medicine_id: str
    on_hand: Decimal
    reserved: Decimal
    available: Decimal


class InventoryReconciliationRead(BaseModel):
    inventory_batch_id: str
    cached_balance: Decimal
    ledger_balance: Decimal
    difference: Decimal
    is_consistent: bool


class StockAdjustmentCreate(BaseModel):
    inventory_batch_id: uuid.UUID
    quantity: Decimal
    reference_id: uuid.UUID
    reason: str