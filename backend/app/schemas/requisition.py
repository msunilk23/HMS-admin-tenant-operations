import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class RequisitionCreate(BaseModel):
    from_location: str
    to_location: str          # "Pharmacy" | "General Store"
    need_by_date: date
    items: str


class RequisitionRead(BaseModel):
    id: uuid.UUID
    seq: int
    indent_number: str
    requested_by_id: uuid.UUID
    requested_by_name: str
    from_location: str
    to_location: str
    request_date: date
    need_by_date: date
    items: str
    status: str
    amount: Optional[Decimal] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RequisitionStatusUpdate(BaseModel):
    status: str   # pending | approved | rejected | fulfilled


class RequisitionAmountUpdate(BaseModel):
    amount: Optional[Decimal] = None  # INR, e.g. 10.50


class RequisitionItemsUpdate(BaseModel):
    items: str  # serialized string, e.g. "Sanitizer x2, Bandages x5"
