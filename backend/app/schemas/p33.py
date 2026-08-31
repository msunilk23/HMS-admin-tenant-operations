from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

CountType = Literal["FULL", "PARTIAL", "SAMPLE"]
CountStatus = Literal[
    "CREATED", "IN_PROGRESS", "SUBMITTED", "RECOUNT_REQUIRED",
    "RECOUNT_IN_PROGRESS", "RESUBMITTED", "APPROVED", "APPLIED", "CANCELLED",
]


class CountCreate(BaseModel):
    pharmacy_location_id: UUID
    count_type: CountType
    selected_batch_ids: list[UUID] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.count_type == "FULL" and self.selected_batch_ids:
            raise ValueError("FULL counts cannot include an explicit batch selection")
        if self.count_type in {"PARTIAL", "SAMPLE"} and not self.selected_batch_ids:
            raise ValueError(f"{self.count_type} counts require at least one selected batch")
        if len(self.selected_batch_ids) != len(set(self.selected_batch_ids)):
            raise ValueError("Duplicate selected batches are not allowed")
        return self


class CountAction(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class CountCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class CountDetailUpdate(BaseModel):
    physical_quantity: Decimal = Field(ge=0)
    version: int = Field(gt=0)
    variance_reason: str | None = Field(default=None, max_length=2000)
    evidence: str | None = Field(default=None, max_length=2000)


class UnexpectedStockCreate(BaseModel):
    inventory_batch_id: UUID
    physical_quantity: Decimal = Field(gt=0)
    evidence: str = Field(min_length=3, max_length=2000)
    variance_reason: str | None = Field(default=None, max_length=2000)


class RecountRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    assigned_to: UUID


class RecountDetailUpdate(BaseModel):
    physical_quantity: Decimal = Field(ge=0)
    version: int = Field(gt=0)
    variance_reason: str | None = Field(default=None, max_length=2000)


class CountDetailRead(BaseModel):
    id: UUID
    count_id: UUID
    inventory_batch_id: UUID
    medicine_id: UUID
    batch_number: str
    system_quantity: Decimal
    available_quantity: Decimal
    reserved_quantity: Decimal
    unit_cost: Decimal | None = None
    physical_quantity: Decimal | None = None
    variance_quantity: Decimal | None = None
    variance_percent: Decimal | None = None
    variance_value: Decimal | None = None
    classifications: list[str]
    variance_reason: str | None = None
    is_unexpected: bool
    evidence: str | None = None
    counted_by: UUID | None = None
    counted_at: datetime | None = None
    version: int
    adjustment_ledger_id: UUID | None = None

    model_config = {"from_attributes": True}


class RecountDetailRead(BaseModel):
    id: UUID
    recount_id: UUID
    count_detail_id: UUID
    physical_quantity: Decimal | None = None
    variance_quantity: Decimal | None = None
    variance_reason: str | None = None
    counted_by: UUID | None = None
    counted_at: datetime | None = None
    version: int

    model_config = {"from_attributes": True}


class RecountRead(BaseModel):
    id: UUID
    count_id: UUID
    attempt_number: int
    status: str
    reason: str
    assigned_to: UUID
    requested_by: UUID
    requested_at: datetime
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    details: list[RecountDetailRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CountRead(BaseModel):
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    pharmacy_location_id: UUID
    status: CountStatus
    count_type: CountType
    reference_key: str
    selected_batch_ids: list[str]
    notes: str | None = None
    quantity_tolerance_percent: Decimal
    repeated_variance_lookback_days: int
    repeated_variance_trigger: int
    high_value_variance_threshold: Decimal
    expected_total_quantity: Decimal
    physical_total_quantity: Decimal
    variance_quantity: Decimal
    total_items_counted: int
    total_variance_items: int
    recount_count: int
    initiated_by: UUID
    initiated_at: datetime
    started_by: UUID | None = None
    started_at: datetime | None = None
    completed_by: UUID | None = None
    completed_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    applied_by: UUID | None = None
    applied_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CountDetailResponse(CountRead):
    details: list[CountDetailRead] = Field(default_factory=list)
    recounts: list[RecountRead] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)


class CountListResponse(BaseModel):
    items: list[CountRead]
    total: int
    page: int
    page_size: int


class VarianceListResponse(BaseModel):
    items: list[CountDetailRead]
    total: int
    page: int
    page_size: int