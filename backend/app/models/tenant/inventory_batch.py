import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class InventoryBatch(Base, TimestampMixin):
    __tablename__ = "inventory_batches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "facility_id",
            "pharmacy_location_id",
            "medicine_id",
            "batch_number",
            name="uq_inventory_batches_tenant_location_medicine_batch",
        ),
        UniqueConstraint("goods_receipt_item_id", name="uq_inventory_batches_goods_receipt_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    medicine_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    manufacturing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    purchase_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mrp: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    available_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE", index=True)
    frozen_by_count_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
