from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StockQuarantineCreate(BaseModel):
    inventory_batch_id: UUID
    quantity: Decimal = Field(gt=0)
    reason: Literal["EXPIRED", "DAMAGED", "INVESTIGATION"]
    idempotency_key: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class StockQuarantineRelease(BaseModel):
    release_reason: str = Field(min_length=10, max_length=2000)


class StockQuarantineDispose(BaseModel):
    disposal_reason: str = Field(min_length=10, max_length=2000)
    disposal_method: str = Field(min_length=3, max_length=100)
    disposal_date: date
    witnessed_by: UUID


class QuarantineBatchRead(BaseModel):
    id: UUID
    pharmacy_location_id: UUID
    medicine_id: UUID
    batch_number: str
    expiry_date: date | None
    available_quantity: Decimal
    status: str

    model_config = {"from_attributes": True}


class StockQuarantineRead(BaseModel):
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    pharmacy_location_id: UUID
    inventory_batch_id: UUID
    status: str
    reference_key: str
    reason: str
    total_quantity_quarantined: Decimal
    remaining_quantity: Decimal
    notes: str | None
    quarantined_by: UUID | None
    quarantined_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None
    approved_action: str | None
    release_reason: str | None
    released_by: UUID | None
    released_at: datetime | None
    disposal_reason: str | None
    disposal_method: str | None
    disposal_date: date | None
    witnessed_by: UUID | None
    disposed_by: UUID | None
    disposed_at: datetime | None
    quarantine_ledger_transaction_id: UUID | None
    release_ledger_transaction_id: UUID | None
    disposal_ledger_transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StockQuarantineListResponse(BaseModel):
    items: list[StockQuarantineRead]
    total: int