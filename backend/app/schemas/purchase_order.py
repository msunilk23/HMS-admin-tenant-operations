import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


def _utc_business_date() -> date:
    return datetime.now(timezone.utc).date()


class PurchaseOrderItemCreate(BaseModel):
    medicine_product_id: uuid.UUID
    ordered_quantity: Decimal = Field(gt=0)
    free_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    unit_of_measure: str = Field(min_length=1, max_length=50)
    unit_purchase_price: Decimal = Field(ge=0, decimal_places=2)
    mrp: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    gst_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID
    po_date: date = Field(default_factory=_utc_business_date)
    required_by_date: Optional[date] = None
    notes: Optional[str] = None
    items: list[PurchaseOrderItemCreate] = Field(min_length=1)


class PurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[uuid.UUID] = None
    po_date: Optional[date] = None
    required_by_date: Optional[date] = None
    notes: Optional[str] = None
    items: Optional[list[PurchaseOrderItemCreate]] = Field(default=None, min_length=1)


class PurchaseOrderItemRead(BaseModel):
    id: uuid.UUID
    purchase_order_id: uuid.UUID
    medicine_product_id: uuid.UUID
    ordered_quantity: Decimal
    free_quantity: Decimal
    unit_of_measure: str
    unit_purchase_price: Decimal
    mrp: Optional[Decimal] = None
    discount_percent: Decimal
    gst_percent: Decimal
    taxable_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    received_quantity: Decimal
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PurchaseOrderRead(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    po_date: date
    required_by_date: Optional[date] = None
    status: str
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    notes: Optional[str] = None
    approved_by_user_id: Optional[uuid.UUID] = None
    approved_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_by_user_id: Optional[uuid.UUID] = None
    updated_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseOrderItemRead]
    model_config = {"from_attributes": True}
