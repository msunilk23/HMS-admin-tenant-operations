from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Vitals(Base):
    __tablename__ = "vitals"
    __table_args__ = (UniqueConstraint("visit_id", name="uq_vitals_visit_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float)  # Celsius
    pulse: Mapped[Optional[int]] = mapped_column()               # bpm
    respiratory_rate: Mapped[Optional[int]] = mapped_column()
    bp_systolic: Mapped[Optional[int]] = mapped_column()
    bp_diastolic: Mapped[Optional[int]] = mapped_column()
    spo2: Mapped[Optional[int]] = mapped_column()                # %
    pain_score: Mapped[Optional[int]] = mapped_column()
    height: Mapped[Optional[float]] = mapped_column(Float)       # cm
    weight: Mapped[Optional[float]] = mapped_column(Float)       # kg
    bmi: Mapped[Optional[float]] = mapped_column(Float)          # kg/m²
    blood_glucose: Mapped[Optional[float]] = mapped_column(Float)
    chief_complaint: Mapped[Optional[str]] = mapped_column(Text)
    allergies: Mapped[Optional[str]] = mapped_column(Text)
    known_no_allergies: Mapped[Optional[bool]] = mapped_column(Boolean)
    general_condition: Mapped[Optional[str]] = mapped_column(String(100))
    level_of_consciousness: Mapped[Optional[str]] = mapped_column(String(100))
    nurse_notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
