from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.engine import tenant_schema_var
from app.models.tenant.invoice import Invoice
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient_route import PatientRoute, PatientRouteConfiguration, PatientRouteEvent, PatientRouteStep
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription
from app.services.audit_service import record_audit

TERMINAL_STEP_STATES = {"COMPLETED", "NOT_PRESENTED", "DECLINED", "EXTERNAL_PURCHASE_CONFIRMED", "EXTERNAL_LAB_CONFIRMED", "CANCELLED"}
ARRIVAL_ROLES = {"receptionist", "nurse", "hospital_admin"}
DESTINATION_ROLES = {"PHARMACY": "pharmacist", "LAB": "lab_technician", "BILLING": "billing_officer"}


def _actor(current_user: dict) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(current_user.get("sub")))
    except (TypeError, ValueError):
        return None


def _facility(current_user: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(current_user["facility_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Facility context is required") from exc


def _assert_facility(route: PatientRoute, current_user: dict) -> uuid.UUID:
    facility_id = _facility(current_user)
    if route.facility_id is None or route.facility_id != facility_id:
        raise HTTPException(status_code=404, detail="Route not found")
    return facility_id


def authorize_destination(current_user: dict, destination: str, *, operation: str) -> None:
    role = current_user.get("role")
    if role in ARRIVAL_ROLES and operation in {"present", "decline", "external", "cancel"}:
        return
    if role == DESTINATION_ROLES.get(destination) and operation in {"present", "start", "complete"}:
        return
    raise HTTPException(status_code=403, detail="You are not authorized for this route destination")


def _event(session: AsyncSession, route: PatientRoute, step: PatientRouteStep | None, event_type: str, previous: str | None, new: str, current_user: dict, *, reason: str | None = None, channel: str | None = None) -> None:
    session.add(PatientRouteEvent(
        id=uuid.uuid4(), route_id=route.id, step_id=step.id if step else None,
        event_type=event_type, previous_state=previous, new_state=new,
        actor_user_id=_actor(current_user), reason=reason, channel=channel,
        metadata_json={"tenant_schema": tenant_schema_var.get()},
    ))


async def _window_minutes(session: AsyncSession, current_user: dict, facility_id: uuid.UUID) -> int:
    try:
        tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Tenant context is required") from exc
    config = await session.scalar(select(PatientRouteConfiguration).where(PatientRouteConfiguration.tenant_id == tenant_id, PatientRouteConfiguration.facility_id == facility_id))
    if config is None:
        config = await session.scalar(select(PatientRouteConfiguration).where(PatientRouteConfiguration.tenant_id == tenant_id, PatientRouteConfiguration.facility_id.is_(None)))
    return max(1, config.presentation_window_minutes if config else 30)


async def _aggregate_route(session: AsyncSession, route: PatientRoute, current_user: dict) -> None:
    steps = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id))).scalars().all()
    if not steps:
        return
    previous = route.status
    if all(step.status == "COMPLETED" for step in steps):
        route.status = "COMPLETED"
        route.completed_at = route.completed_at or datetime.now(timezone.utc)
    elif all(step.status in TERMINAL_STEP_STATES for step in steps):
        route.status = "TERMINAL"
        route.completed_at = None
    elif any(step.status in {"PRESENTED", "PRESENTED_LATE", "IN_SERVICE", "COMPLETED"} for step in steps):
        route.status = "IN_PROGRESS"
        route.completed_at = None
    else:
        route.status = "AWAITING_PATIENT"
        route.completed_at = None
    if previous != route.status:
        route.version += 1
        _event(session, route, None, "ROUTE_AGGREGATE_CHANGED", previous, route.status, current_user)


async def ensure_route(session: AsyncSession, visit, consultation, current_user: dict, *, now: datetime | None = None) -> PatientRoute:
    now = now or datetime.now(timezone.utc)
    route = (await session.execute(select(PatientRoute).where(PatientRoute.visit_id == visit.id).with_for_update())).scalar_one_or_none()
    if route:
        return route
    if visit.facility_id is None:
        raise HTTPException(status_code=409, detail="Visit facility provenance is required for routing")
    facility_id = _facility(current_user)
    if facility_id != visit.facility_id:
        raise HTTPException(status_code=404, detail="Visit not found")
    minutes = await _window_minutes(session, current_user, visit.facility_id)
    route = PatientRoute(id=uuid.uuid4(), visit_id=visit.id, consultation_id=consultation.id if consultation else None, patient_id=visit.patient_id, uhid=visit.uhid, facility_id=visit.facility_id, status="AWAITING_PATIENT", version=1)
    session.add(route)
    await session.flush()

    prescription = (await session.execute(select(Prescription).options(selectinload(Prescription.items)).where(Prescription.visit_id == visit.id).with_for_update())).scalar_one_or_none()
    lab_orders = (await session.execute(select(LabOrder).where(LabOrder.visit_id == visit.id, LabOrder.facility_id == visit.facility_id).with_for_update())).scalars().all()
    eligible_labs = [order for order in lab_orders if order.status not in {"completed", "rejected"} and order.tests]
    invoice = await session.scalar(select(Invoice).where(Invoice.visit_id == visit.id).order_by(Invoice.created_at.desc()).limit(1).with_for_update())
    sources: list[tuple[str, str | None, uuid.UUID | None, list[uuid.UUID] | None]] = []
    if prescription and (prescription.items or prescription.medicines):
        sources.append(("PHARMACY", "prescription", prescription.id, None))
    if eligible_labs:
        sources.append(("LAB", "lab_order", eligible_labs[0].id, [order.id for order in eligible_labs]))
    if invoice and invoice.status in {"draft", "pending", "partially_paid"} and float(invoice.total or 0) > float(invoice.paid_amount or 0):
        sources.append(("BILLING", "invoice", invoice.id, None))
    if not sources:
        sources.append(("EXIT", None, None, None))
    for destination, source_type, source_id, source_ids in sources:
        step = PatientRouteStep(id=uuid.uuid4(), route_id=route.id, visit_id=visit.id, destination=destination, source_type=source_type, source_record_id=source_id, source_record_ids=[str(item) for item in source_ids] if source_ids else None, status="AWAITING_PATIENT", presentation_deadline_at=now + timedelta(minutes=minutes))
        session.add(step)
        await session.flush()
        _event(session, route, step, "STEP_CREATED", None, step.status, current_user)
    _event(session, route, None, "ROUTE_CREATED", None, route.status, current_user)
    record_audit(session, current_user=current_user, action="CREATE", resource_type="patient_route", resource_id=route.id, patient_id=visit.patient_id, visit_id=visit.id, new_value={"status": route.status, "destinations": [item[0] for item in sources]})
    return route


async def _load_step_route(session: AsyncSession, step_id: uuid.UUID, current_user: dict) -> tuple[PatientRouteStep, PatientRoute]:
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.id == step_id).with_for_update())).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Route step not found")
    route = await session.get(PatientRoute, step.route_id, with_for_update=True)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    _assert_facility(route, current_user)
    return step, route


async def _revalidate_sources(session: AsyncSession, step: PatientRouteStep, route: PatientRoute) -> tuple[Prescription | None, list[LabOrder], Invoice | None]:
    if step.destination == "PHARMACY":
        prescription = await session.scalar(select(Prescription).where(Prescription.id == step.source_record_id, Prescription.visit_id == route.visit_id, Prescription.status == "finalized").with_for_update())
        if not prescription:
            raise HTTPException(status_code=409, detail="Prescription is no longer eligible for routing")
        return prescription, [], None
    if step.destination == "LAB":
        ids = [uuid.UUID(str(item)) for item in (step.source_record_ids or ([step.source_record_id] if step.source_record_id else []))]
        orders = (await session.execute(select(LabOrder).where(LabOrder.id.in_(ids), LabOrder.visit_id == route.visit_id, LabOrder.facility_id == route.facility_id).with_for_update())).scalars().all()
        eligible = [order for order in orders if order.status not in {"completed", "rejected"} and order.tests]
        if not eligible:
            raise HTTPException(status_code=409, detail="No eligible Lab order remains for routing")
        return None, eligible, None
    if step.destination == "BILLING":
        invoice = await session.scalar(select(Invoice).where(Invoice.id == step.source_record_id, Invoice.visit_id == route.visit_id).with_for_update())
        if not invoice or invoice.status not in {"draft", "pending", "partially_paid"} or float(invoice.total or 0) <= float(invoice.paid_amount or 0):
            raise HTTPException(status_code=409, detail="Invoice is no longer eligible for routing")
        return None, [], invoice
    return None, [], None


async def present_step(session: AsyncSession, step_id: uuid.UUID, current_user: dict, *, channel: str, now: datetime | None = None) -> PatientRouteStep:
    now = now or datetime.now(timezone.utc)
    step, route = await _load_step_route(session, step_id, current_user)
    authorize_destination(current_user, step.destination, operation="present")
    if step.status in {"PRESENTED", "PRESENTED_LATE"}:
        return step
    if step.status in TERMINAL_STEP_STATES and step.status != "NOT_PRESENTED":
        raise HTTPException(status_code=409, detail=f"Route step is already {step.status}")
    if step.status == "NOT_PRESENTED":
        await _revalidate_sources(session, step, route)
        step.status = "PRESENTED_LATE"
        step.late_presentation = True
        step.reopened_at = now
        step.reopened_by_user_id = _actor(current_user)
        previous = "NOT_PRESENTED"
    else:
        if step.destination != "EXIT":
            await _revalidate_sources(session, step, route)
        step.status = "PRESENTED"
        previous = "AWAITING_PATIENT"
    step.presented_at = step.presented_at or now
    step.presented_by_user_id = step.presented_by_user_id or _actor(current_user)
    step.presentation_channel = channel
    step.version += 1
    _event(session, route, step, "PRESENTED", previous, step.status, current_user, channel=channel)
    if step.destination == "PHARMACY":
        prescription, _, _ = await _revalidate_sources(session, step, route)
        existing = await session.scalar(select(PharmacyQueue).where(PharmacyQueue.prescription_id == prescription.id).with_for_update())
        if not existing:
            session.add(PharmacyQueue(id=uuid.uuid4(), prescription_id=prescription.id, uhid=route.uhid, status="pending"))
    elif step.destination == "LAB":
        _, orders, _ = await _revalidate_sources(session, step, route)
        for order in orders:
            if order.status == "ordered":
                order.status = "sample_pending"
    await _aggregate_route(session, route, current_user)
    return step


async def transition_service_step(session: AsyncSession, step_id: uuid.UUID, target: str, current_user: dict, *, reason: str | None = None) -> PatientRouteStep:
    step, route = await _load_step_route(session, step_id, current_user)
    authorize_destination(current_user, step.destination, operation="start" if target == "IN_SERVICE" else "complete")
    allowed = {"PRESENTED": {"IN_SERVICE"}, "PRESENTED_LATE": {"IN_SERVICE"}, "IN_SERVICE": {"COMPLETED"}}
    if target not in allowed.get(step.status, set()):
        if target == step.status:
            return step
        raise HTTPException(status_code=409, detail=f"Cannot transition route step from {step.status} to {target}")
    previous = step.status
    now = datetime.now(timezone.utc)
    step.status = target
    if target == "IN_SERVICE":
        step.service_started_at = step.service_started_at or now
    else:
        step.completed_at = step.completed_at or now
    step.version += 1
    _event(session, route, step, "SERVICE_TRANSITION", previous, target, current_user, reason=reason)
    await _aggregate_route(session, route, current_user)
    return step


async def record_outcome(session: AsyncSession, step_id: uuid.UUID, target: str, current_user: dict, *, reason: str, channel: str) -> PatientRouteStep:
    if not reason.strip():
        raise HTTPException(status_code=422, detail="A reason is required")
    step, route = await _load_step_route(session, step_id, current_user)
    authorize_destination(current_user, step.destination, operation="external" if target.startswith("EXTERNAL_") else "cancel" if target == "CANCELLED" else "decline")
    if step.status == target:
        return step
    if step.status not in {"AWAITING_PATIENT", "NOT_PRESENTED", "PRESENTED", "PRESENTED_LATE"}:
        raise HTTPException(status_code=409, detail=f"Cannot transition route step from {step.status} to {target}")
    previous = step.status
    step.status = target
    step.outcome_reason = reason.strip()
    step.version += 1
    _event(session, route, step, "OUTCOME_RECORDED", previous, target, current_user, reason=step.outcome_reason, channel=channel)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="patient_route_step", resource_id=step.id, patient_id=route.patient_id, visit_id=route.visit_id, old_value={"status": previous}, new_value={"status": target}, reason=step.outcome_reason)
    await _aggregate_route(session, route, current_user)
    return step


async def expire_steps(session: AsyncSession, current_user: dict, *, facility_id: uuid.UUID | None = None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    stmt = select(PatientRouteStep).join(PatientRoute, PatientRoute.id == PatientRouteStep.route_id).where(PatientRouteStep.status == "AWAITING_PATIENT", PatientRouteStep.presentation_deadline_at <= now)
    if facility_id is not None:
        stmt = stmt.where(PatientRoute.facility_id == facility_id)
    rows = (await session.execute(stmt.with_for_update(skip_locked=True))).scalars().all()
    count = 0
    for step in rows:
        route = await session.get(PatientRoute, step.route_id, with_for_update=True)
        if not route or (facility_id is not None and route.facility_id != facility_id):
            continue
        step.status = "NOT_PRESENTED"
        step.not_presented_at = now
        step.version += 1
        _event(session, route, step, "EXPIRED", "AWAITING_PATIENT", "NOT_PRESENTED", current_user)
        await _aggregate_route(session, route, current_user)
        count += 1
    return count
