import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockTransaction(Base):
    __tablename__ = "stock_transactions"
    __table_args__ = (
        UniqueConstraint(
            "reference_type",
            "reference_id",
            "transaction_type",
            name="uq_stock_transactions_source_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    medicine_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    inventory_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    previous_balance: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    new_balance: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    reference_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    reference_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    correlation_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    performed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
