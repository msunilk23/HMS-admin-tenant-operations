from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class IdempotentAction(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)


class RecallCreate(IdempotentAction):
    medicine_id: UUID
    batch_number: str = Field(min_length=1, max_length=100)
    recall_reason: str = Field(min_length=10, max_length=2000)
    regulatory_reference: str | None = Field(default=None, max_length=200)


class RecallResolve(IdempotentAction):
    action: Literal["SUPPLIER_RETURN", "APPROVED_RELEASE", "DISPOSAL"]
    reason: str = Field(min_length=10, max_length=2000)


class RecallNotificationUpdate(IdempotentAction):
    notification_status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]


class RecallAffectedStockRead(BaseModel):
    id: UUID
    inventory_batch_id: UUID
    pharmacy_location_id: UUID
    quarantine_id: UUID | None
    quantity_quarantined: Decimal

    model_config = {"from_attributes": True}


class RecallRead(BaseModel):
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    medicine_id: UUID
    batch_number: str
    status: str
    reference_key: str
    recall_reason: str
    regulatory_reference: str | None
    notification_status: str
    initiated_by: UUID
    approved_by: UUID | None
    approved_at: datetime | None
    resolution_action: str | None
    resolution_reason: str | None
    resolved_by: UUID | None
    resolved_date: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecallDetail(RecallRead):
    affected_stock: list[RecallAffectedStockRead] = []


class AffectedDispensingRead(BaseModel):
    dispense_id: UUID
    patient_id: UUID
    uhid: str
    patient_name: str
    phone: str
    dispensed_quantity: Decimal
    dispensed_at: datetime | None
    notification_status: str


class TransferItemCreate(BaseModel):
    inventory_batch_id: UUID
    quantity: Decimal = Field(gt=0)


class TransferCreate(IdempotentAction):
    source_location_id: UUID
    destination_location_id: UUID
    items: list[TransferItemCreate] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_transfer(self):
        if self.source_location_id == self.destination_location_id:
            raise ValueError("Source and destination locations must differ")
        if len({item.inventory_batch_id for item in self.items}) != len(self.items):
            raise ValueError("A batch may appear only once in a transfer")
        return self


class TransferReceiveItem(BaseModel):
    transfer_item_id: UUID
    quantity_received: Decimal = Field(ge=0)
    discrepancy_type: Literal["SHORTAGE", "EXCESS", "DAMAGE", "BATCH_MISMATCH"] | None = None
    discrepancy_quantity: Decimal | None = Field(default=None, gt=0)
    discrepancy_notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_discrepancy(self):
        supplied = self.discrepancy_type is not None
        if supplied != (self.discrepancy_quantity is not None and bool(self.discrepancy_notes and self.discrepancy_notes.strip())):
            raise ValueError("Discrepancy type, quantity, and notes must be supplied together")
        return self


class TransferReceive(IdempotentAction):
    items: list[TransferReceiveItem] = Field(min_length=1)
    complete_receipt: bool = True


class DiscrepancyReconcile(IdempotentAction):
    action: Literal["ACCEPT_EXCESS", "WRITE_OFF_SHORTAGE", "RETURN_EXCESS", "REJECT_MISMATCH"]
    notes: str = Field(min_length=10, max_length=2000)


class TransferDiscrepancyRead(BaseModel):
    id: UUID
    transfer_id: UUID
    transfer_item_id: UUID
    discrepancy_type: str
    quantity: Decimal
    notes: str
    status: str
    reported_by: UUID
    reconciled_by: UUID | None
    reconciled_at: datetime | None
    reconciliation_action: str | None
    reconciliation_notes: str | None

    model_config = {"from_attributes": True}


class TransferItemRead(BaseModel):
    id: UUID
    inventory_batch_id: UUID
    transfer_quantity: Decimal
    received_quantity: Decimal | None
    destination_batch_id: UUID | None
    dispatch_ledger_id: UUID | None
    receive_ledger_id: UUID | None

    model_config = {"from_attributes": True}


class TransferRead(BaseModel):
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    status: str
    reference_key: str
    total_items: int
    total_quantity: Decimal
    notes: str | None
    requested_by: UUID
    requested_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None
    dispatched_by: UUID | None
    dispatched_at: datetime | None
    received_by: UUID | None
    received_at: datetime | None
    received_quantity: Decimal | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TransferDetail(TransferRead):
    items: list[TransferItemRead] = []
    discrepancies: list[TransferDiscrepancyRead] = []


class EligibleTransferBatch(BaseModel):
    id: UUID
    pharmacy_location_id: UUID
    medicine_id: UUID
    batch_number: str
    manufacturing_date: date | None = None
    expiry_date: date | None = None
    available_quantity: Decimal
    reserved_quantity: Decimal
    status: str

    model_config = {"from_attributes": True}