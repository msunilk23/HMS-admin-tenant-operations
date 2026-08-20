from enum import StrEnum
from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class VisitStatus(StrEnum):
    REGISTERED = "REGISTERED"
    WAITING_FOR_NURSE = "WAITING_FOR_NURSE"
    IN_PRE_VITAL = "IN_PRE_VITAL"
    WAITING_FOR_DOCTOR = "WAITING_FOR_DOCTOR"
    IN_CONSULTATION = "IN_CONSULTATION"
    CONSULTATION_COMPLETED = "CONSULTATION_COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

    @classmethod
    def normalize(cls, value: object) -> "VisitStatus":
        if value is None:
            raise ValueError("Visit status is required")
        raw = str(value).strip().upper()
        alias_map = {
            "REGISTERED": cls.REGISTERED,
            "WAITING_FOR_NURSE": cls.WAITING_FOR_NURSE,
            "IN_PRE_VITAL": cls.IN_PRE_VITAL,
            "WAITING_FOR_DOCTOR": cls.WAITING_FOR_DOCTOR,
            "IN_CONSULTATION": cls.IN_CONSULTATION,
            "CONSULTATION_COMPLETED": cls.CONSULTATION_COMPLETED,
            "CLOSED": cls.CLOSED,
            "CANCELLED": cls.CANCELLED,
            "VITALS_DONE": cls.WAITING_FOR_DOCTOR,
            "PRESCRIPTION_DONE": cls.CONSULTATION_COMPLETED,
            "PRE_BILLING": cls.CONSULTATION_COMPLETED,
            "BILLING_PENDING": cls.CONSULTATION_COMPLETED,
            "DISPATCHED_PHARMACY": cls.CONSULTATION_COMPLETED,
            "DISPATCHED_LAB": cls.CONSULTATION_COMPLETED,
            "DISPATCHED_BOTH": cls.CONSULTATION_COMPLETED,
        }
        if raw in alias_map:
            return alias_map[raw]
        return cls(raw)


class Visit(Base, TimestampMixin):
    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    doctor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("doctors.id"), nullable=True)
    appointment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("appointments.id"))
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("departments.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=VisitStatus.REGISTERED.value)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    nurse_queue_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    nurse_called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pre_vital_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pre_vital_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    doctor_queue_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    doctor_called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consultation_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consultation_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    billing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    billing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
