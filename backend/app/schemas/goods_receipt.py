import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class GoodsReceiptCreate(BaseModel):
    purchase_order_id: uuid.UUID
    received_date: date = Field(default_factory=date.today)
    supplier_invoice_number: Optional[str] = None
    supplier_invoice_date: Optional[date] = None
    notes: Optional[str] = None


class GoodsReceiptItemCreate(BaseModel):
    purchase_order_item_id: uuid.UUID
    received_quantity: Decimal = Field(gt=0)
    free_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    batch_number: str = Field(min_length=1, max_length=100)
    manufacturing_date: Optional[date] = None
    expiry_date: date
    receiving_notes: Optional[str] = None


class GoodsReceiptItemRead(BaseModel):
    id: uuid.UUID
    goods_receipt_id: uuid.UUID
    purchase_order_item_id: uuid.UUID
    medicine_product_id: uuid.UUID
    batch_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    received_quantity: Decimal
    free_quantity: Decimal
    purchase_rate: Decimal
    mrp: Optional[Decimal] = None
    gst_percent: Decimal
    taxable_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    receiving_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class GoodsReceiptRead(BaseModel):
    id: uuid.UUID
    grn_number: str
    purchase_order_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_invoice_number: Optional[str] = None
    supplier_invoice_date: Optional[date] = None
    received_date: date
    received_by_user_id: Optional[uuid.UUID] = None
    status: str
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    notes: Optional[str] = None
    created_by_user_id: Optional[uuid.UUID] = None
    updated_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    items: list[GoodsReceiptItemRead]
    model_config = {"from_attributes": True}
