import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ClinicalAlert(Base, TimestampMixin):
    __tablename__ = "clinical_alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False, default="allergy")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="critical")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resolved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
