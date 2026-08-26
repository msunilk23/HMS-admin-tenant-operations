import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class HospitalFormulary(Base, TimestampMixin):
    __tablename__ = "hospital_formulary"
    __table_args__ = (
        UniqueConstraint(
            "medicine_product_id",
            "department_id",
            name="uq_hospital_formulary_product_department",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    medicine_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medicine_products.id"), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False, index=True
    )
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_prescribable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
