from typing import Optional
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QueueToken(Base):
    __tablename__ = "queue_tokens"
    __table_args__ = (
        UniqueConstraint("token_scope", "token_date", "token_no", name="uq_queue_tokens_scope_date_token_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    appointment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("appointments.id"))
    visit_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("visits.id"), nullable=True, index=True)
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("departments.id"), index=True)
    doctor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("doctors.id"), index=True)
    token_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # Allocation scope this token_no is unique within — 'dept:<uuid>' or 'queue:<queue_type>'.
    token_scope: Mapped[str] = mapped_column(String(120), nullable=False)
    # Tenant-local calendar date the token was issued (daily sequence resets here).
    token_date: Mapped[date] = mapped_column(Date, nullable=False)
    queue_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # queue_type: registration | vitals | consultation | pharmacy | billing
    priority: Mapped[str] = mapped_column(String(30), nullable=False, default="normal")
    # priority: normal | senior_citizen | pregnant | disabled | urgent | emergency
    priority_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority_assigned_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    priority_assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="checked_in")
    # status: checked_in | completed | cancelled
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
