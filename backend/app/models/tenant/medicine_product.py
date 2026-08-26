import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MedicineProduct(Base, TimestampMixin):
    __tablename__ = "medicine_products"
    __table_args__ = (
        UniqueConstraint("code", name="uq_medicine_products_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    generic_medicine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generic_medicines.id"), nullable=False, index=True
    )
    brand_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    strength: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dosage_form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dosage_forms.id"), nullable=False, index=True
    )
    default_route_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("routes.id"), nullable=True, index=True
    )
    manufacturer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("manufacturers.id"), nullable=True, index=True
    )
    composition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    gst_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    schedule_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_controlled_drug: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_prescription: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
