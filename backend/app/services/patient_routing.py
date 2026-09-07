from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import tenant_schema_var
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.document_request import PrescriptionDocumentRequest
from app.models.tenant.invoice import Invoice
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient_route import PatientRoute, PatientRouteConfiguration, PatientRouteEvent, PatientRouteStep
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription
from app.services.audit_service import record_audit


_TERMINAL = {"COMPLETED", "NOT_PRESENTED", "DECLINED", "EXTERNAL_PURCHASE_CONFIRMED", "EXTERNAL_LAB_CONFIRMED", "CANCELLED"}
_ACTIVE_SERVICE_ROLES = {
    "PHARMACY": {"pharmacist", "hospital_admin"},
    "LAB": {"lab_technician", "hospital_admin"},
    "BILLING": {"billing_officer", "hospital_admin"},
}


async def _window_minutes(session: AsyncSession, current_user: dict, facility_id: uuid.UUID | None) -> int:
    tenant_id = current_user.get("tenant_id")
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except (TypeError, ValueError):
        return 30
    stmt = select(PatientRouteConfiguration).where(PatientRouteConfiguration.tenant_id == tenant_uuid)
    if facility_id is None:
        stmt = stmt.where(PatientRouteConfiguration.facility_id.is_(None))
    else:
        stmt = stmt.where(PatientRouteConfiguration.facility_id == facility_id)
    config = (await session.execute(stmt)).scalar_one_or_none()
    return max(1, config.presentation_window_minutes if config else 30)


def _actor(current_user: dict) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(current_user.get("sub")))
    except (TypeError, ValueError):
        return None


def _event(session: AsyncSession, route: PatientRoute, step: PatientRouteStep | None, event_type: str, previous: str | None, new: str, current_user: dict, *, reason: str | None = None, channel: str | None = None) -> None:
    session.add(PatientRouteEvent(
        id=uuid.uuid4(), route_id=route.id, step_id=step.id if step else None,
        event_type=event_type, previous_state=previous, new_state=new,
        actor_user_id=_actor(current_user), reason=reason, channel=channel,
        request_id=None, metadata_json={"tenant_schema": tenant_schema_var.get()},
    ))


async def ensure_route(session: AsyncSession, visit, consultation, current_user: dict, *, now: datetime | None = None) -> PatientRoute:
    now = now or datetime.now(timezone.utc)
    route = (await session.execute(
        select(PatientRoute).where(PatientRoute.visit_id == visit.id).with_for_update()
    )).scalar_one_or_none()
    if route:
        return route

    minutes = await _window_minutes(session, current_user, visit.facility_id)
    route = PatientRoute(
        id=uuid.uuid4(), visit_id=visit.id, consultation_id=consultation.id if consultation else None,
        patient_id=visit.patient_id, uhid=visit.uhid, facility_id=visit.facility_id,
        status="AWAITING_PATIENT", version=1,
    )
    session.add(route)
    await session.flush()

    prescription = (await session.execute(
        select(Prescription).options(selectinload(Prescription.items)).where(Prescription.visit_id == visit.id).with_for_update()
    )).scalar_one_or_none()
    lab_order = (await session.execute(
        select(LabOrder).where(LabOrder.visit_id == visit.id).with_for_update()
    )).scalar_one_or_none()
    invoice = (await session.execute(
        select(Invoice).where(Invoice.visit_id == visit.id).order_by(Invoice.created_at.desc()).limit(1).with_for_update()
    )).scalar_one_or_none()

    has_medicines = bool(prescription and (prescription.items or prescription.medicines))
    sources: list[tuple[str, str | None, uuid.UUID | None]] = []
    if has_medicines and prescription is not None:
        sources.append(("PHARMACY", "prescription", prescription.id))
    if lab_order and lab_order.status not in {"completed", "rejected"} and lab_order.tests:
        sources.append(("LAB", "lab_order", lab_order.id))
    if invoice and invoice.status in {"draft", "pending", "partially_paid"} and float(invoice.total or 0) > float(invoice.paid_amount or 0):
        sources.append(("BILLING", "invoice", invoice.id))
    if not sources:
        sources.append(("EXIT", None, None))

    for destination, source_type, source_id in sources:
        step = PatientRouteStep(
            id=uuid.uuid4(), route_id=route.id, visit_id=visit.id,
            destination=destination, source_type=source_type, source_record_id=source_id,
            status="AWAITING_PATIENT", presentation_deadline_at=now + timedelta(minutes=minutes),
        )
        session.add(step)
        await session.flush()
        _event(session, route, step, "STEP_CREATED", None, step.status, current_user)
    _event(session, route, None, "ROUTE_CREATED", None, route.status, current_user)
    record_audit(session, current_user=current_user, action="CREATE", resource_type="patient_route", resource_id=route.id, patient_id=visit.patient_id, visit_id=visit.id, new_value={"status": route.status, "destinations": [item[0] for item in sources]})
    return route


async def present_step(session: AsyncSession, step_id: uuid.UUID, current_user: dict, *, channel: str, now: datetime | None = None) -> PatientRouteStep:
    now = now or datetime.now(timezone.utc)
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.id == step_id).with_for_update())).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Route step not found")
    route = await session.get(PatientRoute, step.route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    user_facility = current_user.get("facility_id")
    if route.facility_id and user_facility and str(route.facility_id) != str(user_facility):
        raise HTTPException(status_code=404, detail="Route not found")
    if current_user.get("role") not in {"receptionist", "nurse", "hospital_admin"} and current_user.get("role") not in _ACTIVE_SERVICE_ROLES.get(step.destination, set()):
        raise HTTPException(status_code=403, detail="You are not authorized for this route destination")
    if step.status == "PRESENTED" or step.status == "PRESENTED_LATE":
        return step
    if step.status in _TERMINAL and step.status != "NOT_PRESENTED":
        raise HTTPException(status_code=409, detail=f"Route step is already {step.status}")
    if step.status == "NOT_PRESENTED":
        step.status = "PRESENTED_LATE"
        step.late_presentation = True
        step.reopened_at = now
    else:
        step.status = "PRESENTED"
    previous = "NOT_PRESENTED" if step.late_presentation else "AWAITING_PATIENT"
    step.presented_at = step.presented_at or now
    step.presented_by_user_id = step.presented_by_user_id or _actor(current_user)
    step.presentation_channel = channel
    step.version += 1
    _event(session, route, step, "PRESENTED", previous, step.status, current_user, channel=channel)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="patient_route_step", resource_id=step.id, patient_id=route.patient_id, visit_id=route.visit_id, new_value={"status": step.status, "late": step.late_presentation, "channel": channel})
    if step.destination == "PHARMACY":
        prescription = await session.get(Prescription, step.source_record_id)
        if prescription:
            existing = (await session.execute(select(PharmacyQueue).where(PharmacyQueue.prescription_id == prescription.id).with_for_update())).scalar_one_or_none()
            if not existing:
                session.add(PharmacyQueue(id=uuid.uuid4(), prescription_id=prescription.id, uhid=route.uhid, status="pending"))
    elif step.destination == "LAB":
        lab_order = await session.get(LabOrder, step.source_record_id)
        if lab_order and lab_order.status == "ordered":
            lab_order.status = "sample_pending"
    return step


async def transition_service_step(session: AsyncSession, step_id: uuid.UUID, target: str, current_user: dict, *, reason: str | None = None) -> PatientRouteStep:
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.id == step_id).with_for_update())).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Route step not found")
    allowed_roles = _ACTIVE_SERVICE_ROLES.get(step.destination, set())
    if current_user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="You are not authorized for this route destination")
    allowed = {"PRESENTED": {"IN_SERVICE"}, "PRESENTED_LATE": {"IN_SERVICE"}, "IN_SERVICE": {"COMPLETED"}}
    if target not in allowed.get(step.status, set()):
        if target == step.status:
            return step
        raise HTTPException(status_code=409, detail=f"Cannot transition route step from {step.status} to {target}")
    route = await session.get(PatientRoute, step.route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    user_facility = current_user.get("facility_id")
    if route.facility_id and user_facility and str(route.facility_id) != str(user_facility):
        raise HTTPException(status_code=404, detail="Route not found")
    previous = step.status
    now = datetime.now(timezone.utc)
    step.status = target
    if target == "IN_SERVICE":
        step.service_started_at = step.service_started_at or now
    if target == "COMPLETED":
        step.completed_at = step.completed_at or now
    step.version += 1
    _event(session, route, step, "SERVICE_TRANSITION", previous, target, current_user, reason=reason)
    return step


async def expire_steps(session: AsyncSession, current_user: dict, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    rows = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.status == "AWAITING_PATIENT", PatientRouteStep.presentation_deadline_at <= now).with_for_update())).scalars().all()
    for step in rows:
        route = await session.get(PatientRoute, step.route_id)
        if not route:
            continue
        step.status = "NOT_PRESENTED"
        step.not_presented_at = now
        step.version += 1
        _event(session, route, step, "EXPIRED", "AWAITING_PATIENT", "NOT_PRESENTED", current_user)
    return len(rows)