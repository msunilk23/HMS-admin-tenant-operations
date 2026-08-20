from typing import Optional, List
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Consultation(Base, TimestampMixin):
    __tablename__ = "consultations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, unique=True, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    chief_complaint: Mapped[Optional[str]] = mapped_column(Text)
    history: Mapped[Optional[str]] = mapped_column(Text)
    examination: Mapped[Optional[str]] = mapped_column(Text)
    # e.g. [{"code": "J06.9", "description": "Acute upper respiratory infection"}]
    diagnosis_icd10: Mapped[Optional[List[dict]]] = mapped_column(JSONB, default=None)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    amended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
