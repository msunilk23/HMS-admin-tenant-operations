from typing import Optional
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prescriptions.id"), nullable=False, index=True)
    medicine: Mapped[str] = mapped_column(String(200), nullable=False)
    strength: Mapped[Optional[str]] = mapped_column(String(100))
    dose: Mapped[Optional[str]] = mapped_column(String(100))
    route: Mapped[Optional[str]] = mapped_column(String(50), default="oral")
    frequency: Mapped[Optional[str]] = mapped_column(String(50))
    duration: Mapped[Optional[str]] = mapped_column(String(80))
    quantity: Mapped[Optional[str]] = mapped_column(String(50))
    instructions: Mapped[Optional[str]] = mapped_column(Text)

    prescription: Mapped["Prescription"] = relationship(back_populates="items")


class Prescription(Base, TimestampMixin):
    __tablename__ = "prescriptions"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    consultation_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("consultations.id"), nullable=True, index=True)
    doctor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("doctors.id"), nullable=True, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="finalized")
    # Legacy compatibility for downstream code that still expects a medicine list JSON payload.
    medicines: Mapped[Optional[list]] = mapped_column(JSONB)
    instructions: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list[PrescriptionItem]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
    )
