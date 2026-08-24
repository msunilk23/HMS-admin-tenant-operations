import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class LineItem(BaseModel):
    description: str
    amount: float


class PharmacyLineItem(BaseModel):
    name: str
    mfr: str = ""
    batch: str = ""
    expiry: str = ""        # "MM/YYYY" free-text
    qty: float = 1
    mrp: float = 0.0
    gst_pct: float = 0.0   # percentage e.g. 5 or 12
    dis_pct: float = 0.0   # discount percentage
    total: float = 0.0     # computed on frontend, stored as-is


class PharmacyBillCreate(BaseModel):
    line_items: List[PharmacyLineItem]
    discount: float = 0.0
    payment_method: str = "cash"   # cash | online

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v: str) -> str:
        if v not in ("cash", "online"):
            raise ValueError("payment_method must be 'cash' or 'online'")
        return v


class InvoiceCreate(BaseModel):
    visit_id: uuid.UUID
    line_items: Optional[List[LineItem]] = None
    discount: float = 0.0
    tax: float = 0.0


class InvoicePayment(BaseModel):
    payment_method: str  # cash | upi | card | insurance | razorpay
    amount: Optional[float] = None
    transaction_reference: Optional[str] = None


class PaymentRead(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    amount: float
    payment_method: str
    status: str
    transaction_reference: Optional[str] = None
    gateway: Optional[str] = None
    paid_at: datetime

    model_config = {"from_attributes": True}


class RefundCreate(BaseModel):
    amount: Optional[float] = None
    reason: str


class InvoiceRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    line_items: Optional[List[Dict[str, Any]]] = None
    subtotal: float
    discount: float
    tax: float
    total: float
    paid_amount: float = 0.0
    balance: float = 0.0
    payment_method: Optional[str] = None
    status: str
    source: Optional[str] = None
    pharmacy_queue_id: Optional[uuid.UUID] = None
    paid_at: Optional[datetime] = None
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    receipt_number: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
