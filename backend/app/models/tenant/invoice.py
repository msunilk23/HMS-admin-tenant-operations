from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # e.g. [{"description": "Consultation", "amount": 500.00}, {"description": "CBC Test", "amount": 300.00}]
    line_items: Mapped[Optional[list]] = mapped_column(JSONB)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    discount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    tax: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    payment_method: Mapped[Optional[str]] = mapped_column(String(20))
    # payment_method: cash | upi | card | insurance
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # status: draft | pending | partially_paid | paid | cancelled | refunded
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, unique=True)
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # pharmacy billing fields
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="consultation")
    pharmacy_queue_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)

    @property
    def balance(self) -> float:
        return max(float(self.total) - float(self.paid_amount), 0.0)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="captured")
    transaction_reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, unique=True)
    gateway: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def invoice_status_for_payment(total: float, paid_amount: float) -> str:
    if paid_amount <= 0:
        return "pending"
    if paid_amount < total:
        return "partially_paid"
    return "paid"
