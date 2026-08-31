import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PharmacyLocation(Base, TimestampMixin):
    __tablename__ = "pharmacy_locations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "facility_id",
            "location_code",
            name="uq_pharmacy_locations_tenant_facility_code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    location_name: Mapped[str] = mapped_column(String(200), nullable=False)
    location_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
