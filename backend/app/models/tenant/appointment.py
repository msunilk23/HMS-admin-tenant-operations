from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"), nullable=False, index=True)
    slot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    # status: scheduled | confirmed | checked_in | completed | cancelled | no_show
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="walkin")
    # type: walkin | phone | online
    notes: Mapped[Optional[str]] = mapped_column(Text)
    booked_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column()  # receptionist or patient self
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
