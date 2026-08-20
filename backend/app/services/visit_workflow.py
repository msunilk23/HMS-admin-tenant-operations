from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import tenant_schema_var
from app.services.audit_service import record_audit


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
    def normalize(cls, value: Any) -> "VisitStatus":
        if value is None:
            raise ValueError("Visit status is required")
        raw = str(value).strip().upper()
        legacy_aliases = {
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
        if raw in legacy_aliases:
            return legacy_aliases[raw]
        return cls(raw)


class VisitTransitionSource(StrEnum):
    RECEPTION = "RECEPTION"
    NURSE = "NURSE"
    DOCTOR = "DOCTOR"
    SYSTEM = "SYSTEM"
    CANCELLED = "CANCELLED"


_ALLOWED_TRANSITIONS: dict[VisitStatus, set[VisitStatus]] = {
    VisitStatus.REGISTERED: {VisitStatus.WAITING_FOR_NURSE, VisitStatus.CANCELLED},
    VisitStatus.WAITING_FOR_NURSE: {VisitStatus.IN_PRE_VITAL, VisitStatus.CANCELLED},
    VisitStatus.IN_PRE_VITAL: {VisitStatus.WAITING_FOR_DOCTOR, VisitStatus.CANCELLED},
    VisitStatus.WAITING_FOR_DOCTOR: {VisitStatus.IN_CONSULTATION, VisitStatus.CANCELLED},
    VisitStatus.IN_CONSULTATION: {VisitStatus.CONSULTATION_COMPLETED, VisitStatus.CANCELLED},
    VisitStatus.CONSULTATION_COMPLETED: {VisitStatus.CLOSED},
    VisitStatus.CLOSED: set(),
    VisitStatus.CANCELLED: set(),
}


class VisitWorkflowService:
    @staticmethod
    def can_transition(current_status: Any, next_status: Any) -> bool:
        current = VisitStatus.normalize(current_status)
        target = VisitStatus.normalize(next_status)
        return target in _ALLOWED_TRANSITIONS.get(current, set())

    @staticmethod
    async def transition(
        session: AsyncSession,
        visit: Any,
        new_status: Any,
        changed_by: str | uuid.UUID | None,
        source: VisitTransitionSource | str,
    ) -> Any:
        previous_status = VisitStatus.normalize(getattr(visit, "status", None))
        next_status = VisitStatus.normalize(new_status)
        if not VisitWorkflowService.can_transition(previous_status, next_status):
            raise ValueError(
                f"Invalid visit transition from '{previous_status.value}' to '{next_status.value}'"
            )

        visit.status = next_status.value
        timestamp = datetime.now(timezone.utc)
        if next_status == VisitStatus.WAITING_FOR_NURSE:
            visit.nurse_queue_at = getattr(visit, "nurse_queue_at", None) or timestamp
        elif next_status == VisitStatus.IN_PRE_VITAL:
            visit.nurse_called_at = getattr(visit, "nurse_called_at", None) or timestamp
            visit.pre_vital_started_at = getattr(visit, "pre_vital_started_at", None) or timestamp
        elif next_status == VisitStatus.WAITING_FOR_DOCTOR:
            visit.pre_vital_completed_at = getattr(visit, "pre_vital_completed_at", None) or timestamp
            visit.doctor_queue_at = getattr(visit, "doctor_queue_at", None) or timestamp
        elif next_status == VisitStatus.IN_CONSULTATION:
            visit.doctor_called_at = getattr(visit, "doctor_called_at", None) or timestamp
            visit.consultation_started_at = getattr(visit, "consultation_started_at", None) or timestamp
        elif next_status == VisitStatus.CONSULTATION_COMPLETED:
            visit.consultation_completed_at = getattr(visit, "consultation_completed_at", None) or timestamp
        if next_status in {VisitStatus.CLOSED, VisitStatus.CANCELLED}:
            visit.closed_at = timestamp

        record_audit(
            session,
            current_user={
                "sub": changed_by,
                "role": str(source).lower(),
                "tenant_schema": tenant_schema_var.get(),
            },
            action="UPDATE",
            resource_type="visit_state",
            resource_id=visit.id,
            visit_id=visit.id,
            old_value={"status": previous_status.value},
            new_value={
                "status": next_status.value,
                "changed_by": str(changed_by) if changed_by is not None else None,
                "source": str(source),
                "timestamp": timestamp.isoformat(),
            },
        )
        return visit
