from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


ROUTE_STATES = {
    "AWAITING_PATIENT", "PRESENTED", "PRESENTED_LATE", "IN_SERVICE", "COMPLETED",
    "NOT_PRESENTED", "DECLINED", "EXTERNAL_PURCHASE_CONFIRMED", "EXTERNAL_LAB_CONFIRMED", "CANCELLED",
}
DESTINATIONS = {"PHARMACY", "LAB", "BILLING", "EXIT"}


class PatientRouteConfiguration(Base, TimestampMixin):
    __tablename__ = "patient_route_configurations"
    __table_args__ = (CheckConstraint("presentation_window_minutes > 0", name="ck_patient_route_config_positive_window"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    presentation_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)


class PatientRoute(Base, TimestampMixin):
    __tablename__ = "patient_routes"
    __table_args__ = (
        UniqueConstraint("visit_id", name="uq_patient_routes_visit"),
        Index("ix_patient_routes_patient_status", "patient_id", "status"),
        CheckConstraint("status IN ('AWAITING_PATIENT','IN_PROGRESS','COMPLETED','TERMINAL')", name="ck_patient_routes_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    consultation_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("consultations.id"), nullable=True, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="AWAITING_PATIENT")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PatientRouteStep(Base, TimestampMixin):
    __tablename__ = "patient_route_steps"
    __table_args__ = (
        UniqueConstraint("route_id", "destination", name="uq_patient_route_steps_destination"),
        Index("ix_patient_route_steps_lookup", "destination", "status", "presentation_deadline_at"),
        CheckConstraint("destination IN ('PHARMACY','LAB','BILLING','EXIT')", name="ck_patient_route_steps_destination"),
        CheckConstraint("status IN ('AWAITING_PATIENT','PRESENTED','PRESENTED_LATE','IN_SERVICE','COMPLETED','NOT_PRESENTED','DECLINED','EXTERNAL_PURCHASE_CONFIRMED','EXTERNAL_LAB_CONFIRMED','CANCELLED')", name="ck_patient_route_steps_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_routes.id", ondelete="CASCADE"), nullable=False, index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(40))
    source_record_id: Mapped[Optional[uuid.UUID]] = mapped_column()
    source_record_ids: Mapped[Optional[list]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="AWAITING_PATIENT")
    presentation_deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    presented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    service_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    not_presented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    presented_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column()
    reopened_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column()
    presentation_channel: Mapped[Optional[str]] = mapped_column(String(30))
    outcome_reason: Mapped[Optional[str]] = mapped_column(Text)
    late_presentation: Mapped[bool] = mapped_column(nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PatientRouteEvent(Base):
    __tablename__ = "patient_route_events"
    __table_args__ = (Index("ix_patient_route_events_step_time", "step_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_routes.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("patient_route_steps.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_state: Mapped[Optional[str]] = mapped_column(String(40))
    new_state: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column()
    reason: Mapped[Optional[str]] = mapped_column(Text)
    channel: Mapped[Optional[str]] = mapped_column(String(30))
    request_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)