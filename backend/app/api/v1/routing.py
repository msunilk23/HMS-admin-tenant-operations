import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.api.dependencies import get_facility_id
from app.db.engine import get_session
from app.models.tenant.patient_route import PatientRoute, PatientRouteStep
from app.schemas.patient_route import PatientRouteRead, PatientRouteStepRead, RouteOutcomeRequest, RoutePresentationRequest
from app.services.patient_routing import expire_steps, present_step, transition_service_step
from app.services.audit_service import record_audit

router = APIRouter()
_READ_ROLES = ("doctor", "receptionist", "nurse", "pharmacist", "lab_technician", "billing_officer", "hospital_admin")
_PRESENT_ROLES = ("receptionist", "nurse", "hospital_admin", "pharmacist", "lab_technician", "billing_officer")


async def _load_route(session: AsyncSession, route_id: uuid.UUID) -> PatientRoute:
    route = (await session.execute(select(PatientRoute).where(PatientRoute.id == route_id))).scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


async def _read(route: PatientRoute, session: AsyncSession) -> PatientRouteRead:
    steps = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.route_id == route.id).order_by(PatientRouteStep.created_at))).scalars().all()
    result = PatientRouteRead.model_validate(route)
    result.steps = [PatientRouteStepRead.model_validate(step) for step in steps]
    return result


@router.get("/visits/{visit_id}/routing", response_model=PatientRouteRead)
async def visit_routing(visit_id: uuid.UUID, session: AsyncSession = Depends(get_session), _: dict = Depends(require_role(*_READ_ROLES)), facility_id: uuid.UUID = Depends(get_facility_id)):
    route = (await session.execute(select(PatientRoute).where(PatientRoute.visit_id == visit_id, PatientRoute.facility_id == facility_id))).scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="Routing journey not found")
    return await _read(route, session)


@router.get("/routing/steps", response_model=list[PatientRouteStepRead])
async def list_route_steps(destination: str | None = Query(None), status: str | None = Query(None), session: AsyncSession = Depends(get_session), _: dict = Depends(require_role(*_READ_ROLES)), facility_id: uuid.UUID = Depends(get_facility_id)):
    stmt = select(PatientRouteStep).join(PatientRoute, PatientRoute.id == PatientRouteStep.route_id).where(PatientRoute.facility_id == facility_id).order_by(PatientRouteStep.presentation_deadline_at).limit(100)
    if destination:
        stmt = stmt.where(PatientRouteStep.destination == destination.upper())
    if status:
        stmt = stmt.where(PatientRouteStep.status == status.upper())
    return (await session.execute(stmt)).scalars().all()


@router.post("/routing/steps/{step_id}/present", response_model=PatientRouteStepRead)
async def present_route_step(step_id: uuid.UUID, payload: RoutePresentationRequest, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role(*_PRESENT_ROLES))):
    step = await present_step(session, step_id, current_user, channel=payload.channel)
    await session.commit()
    return step


@router.post("/routing/steps/{step_id}/start", response_model=PatientRouteStepRead)
async def start_route_step(step_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role(*_PRESENT_ROLES))):
    step = await transition_service_step(session, step_id, "IN_SERVICE", current_user)
    await session.commit()
    return step


@router.post("/routing/steps/{step_id}/complete", response_model=PatientRouteStepRead)
async def complete_route_step(step_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role(*_PRESENT_ROLES))):
    step = await transition_service_step(session, step_id, "COMPLETED", current_user)
    await session.commit()
    return step


@router.post("/routing/steps/{step_id}/decline", response_model=PatientRouteStepRead)
async def decline_route_step(step_id: uuid.UUID, payload: RouteOutcomeRequest, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role(*_PRESENT_ROLES))):
    return await _record_terminal(step_id, "DECLINED", payload, session, current_user)


@router.post("/routing/steps/{step_id}/external", response_model=PatientRouteStepRead)
async def external_route_step(step_id: uuid.UUID, payload: RouteOutcomeRequest, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("receptionist", "nurse", "hospital_admin"))):
    step = await _load_step(session, step_id)
    target = "EXTERNAL_PURCHASE_CONFIRMED" if step.destination == "PHARMACY" else "EXTERNAL_LAB_CONFIRMED" if step.destination == "LAB" else "CANCELLED"
    return await _record_terminal(step_id, target, payload, session, current_user)


@router.post("/routing/steps/{step_id}/cancel", response_model=PatientRouteStepRead)
async def cancel_route_step(step_id: uuid.UUID, payload: RouteOutcomeRequest, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin", "receptionist"))):
    return await _record_terminal(step_id, "CANCELLED", payload, session, current_user)


@router.post("/routing/expire", response_model=dict)
async def expire_routing(session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin"))):
    count = await expire_steps(session, current_user)
    await session.commit()
    return {"expired": count}


async def _load_step(session: AsyncSession, step_id: uuid.UUID) -> PatientRouteStep:
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.id == step_id).with_for_update())).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Route step not found")
    return step


async def _record_terminal(step_id: uuid.UUID, target: str, payload: RouteOutcomeRequest, session: AsyncSession, current_user: dict) -> PatientRouteStep:
    if not payload.reason.strip():
        raise HTTPException(status_code=422, detail="A reason is required")
    step = await _load_step(session, step_id)
    route = await session.get(PatientRoute, step.route_id)
    if step.status == target:
        return step
    if step.status not in {"AWAITING_PATIENT", "NOT_PRESENTED", "PRESENTED", "PRESENTED_LATE"}:
        raise HTTPException(status_code=409, detail=f"Cannot transition route step from {step.status} to {target}")
    previous = step.status
    step.status = target
    step.outcome_reason = payload.reason.strip()
    step.version += 1
    from app.services.patient_routing import _event
    _event(session, route, step, "OUTCOME_RECORDED", previous, target, current_user, reason=step.outcome_reason, channel=payload.channel)
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="patient_route_step", resource_id=step.id, patient_id=route.patient_id, visit_id=route.visit_id, old_value={"status": previous}, new_value={"status": target}, reason=step.outcome_reason)
    await session.commit()
    return step