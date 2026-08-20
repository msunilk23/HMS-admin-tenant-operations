"""Pure TAT calculations from persisted semantic timestamps."""

from datetime import datetime
from typing import Any


def seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max((end - start).total_seconds(), 0.0)


def build_visit_tat(visit: Any, *, lab_order: Any = None, pharmacy_queue: Any = None, invoice: Any = None) -> dict:
    return {
        "registered_at": visit.registered_at,
        "nurse_queue_at": visit.nurse_queue_at,
        "nurse_called_at": visit.nurse_called_at,
        "pre_vital_started_at": visit.pre_vital_started_at,
        "pre_vital_completed_at": visit.pre_vital_completed_at,
        "doctor_queue_at": visit.doctor_queue_at,
        "doctor_called_at": visit.doctor_called_at,
        "consultation_started_at": visit.consultation_started_at,
        "consultation_completed_at": visit.consultation_completed_at,
        "billing_started_at": getattr(visit, "billing_started_at", None),
        "billing_completed_at": getattr(visit, "billing_completed_at", None),
        "registration_to_nurse_queue_seconds": seconds_between(visit.registered_at, visit.nurse_queue_at),
        "nurse_wait_seconds": seconds_between(visit.nurse_queue_at, visit.nurse_called_at),
        "pre_vitals_seconds": seconds_between(visit.pre_vital_started_at, visit.pre_vital_completed_at),
        "doctor_wait_seconds": seconds_between(visit.doctor_queue_at, visit.doctor_called_at),
        "consultation_seconds": seconds_between(visit.consultation_started_at, visit.consultation_completed_at),
        "total_opd_seconds": seconds_between(visit.registered_at, visit.closed_at),
        "lab_wait_seconds": seconds_between(
            getattr(lab_order, "ordered_at", None),
            getattr(lab_order, "result_ready_at", None),
        ),
        "pharmacy_wait_seconds": seconds_between(
            getattr(pharmacy_queue, "called_at", None),
            getattr(pharmacy_queue, "dispensed_at", None),
        ),
        "billing_seconds": seconds_between(
            getattr(invoice, "billing_started_at", None),
            getattr(invoice, "billing_completed_at", None),
        ),
    }
