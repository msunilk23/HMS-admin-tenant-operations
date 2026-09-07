import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.api.dependencies import get_facility_id
from app.db.engine import get_session
from app.models.tenant.patient_route import PatientRoute, PatientRouteStep
from app.models.tenant.doctor import Doctor
from app.models.tenant.visit import Visit
from app.schemas.patient_route import PatientRouteRead, PatientRouteStepRead, RouteOutcomeRequest, RoutePresentationRequest
from app.services.patient_routing import expire_steps, present_step, record_outcome, transition_service_step

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
async def visit_routing(visit_id: uuid.UUID, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role(*_READ_ROLES)), facility_id: uuid.UUID = Depends(get_facility_id)):
    route = (await session.execute(select(PatientRoute).where(PatientRoute.visit_id == visit_id, PatientRoute.facility_id == facility_id))).scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="Routing journey not found")
    if current_user.get("role") == "doctor":
        doctor = await session.scalar(select(Doctor).where(Doctor.user_id == uuid.UUID(str(current_user["sub"]))))
        visit = await session.get(Visit, visit_id)
        if not doctor or not visit or visit.doctor_id != doctor.id:
            raise HTTPException(status_code=404, detail="Routing journey not found")
    return await _read(route, session)


@router.get("/routing/steps", response_model=list[PatientRouteStepRead])
async def list_route_steps(destination: str | None = Query(None), status: str | None = Query(None), session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role(*_READ_ROLES)), facility_id: uuid.UUID = Depends(get_facility_id)):
    role = current_user.get("role")
    if role == "doctor":
        raise HTTPException(status_code=403, detail="Doctors must request an authorized Visit routing summary")
    stmt = select(PatientRouteStep).join(PatientRoute, PatientRoute.id == PatientRouteStep.route_id).where(PatientRoute.facility_id == facility_id).order_by(PatientRouteStep.presentation_deadline_at).limit(100)
    if role in {"pharmacist", "lab_technician", "billing_officer"}:
        owned = {"pharmacist": "PHARMACY", "lab_technician": "LAB", "billing_officer": "BILLING"}[role]
        stmt = stmt.where(PatientRouteStep.destination == owned, PatientRouteStep.status.in_(["PRESENTED", "PRESENTED_LATE", "IN_SERVICE", "COMPLETED"]))
    elif status is None:
        stmt = stmt.where(PatientRouteStep.status == "AWAITING_PATIENT")
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
    step = await record_outcome(session, step_id, "DECLINED", current_user, reason=payload.reason, channel=payload.channel)
    await session.commit()
    return step


@router.post("/routing/steps/{step_id}/external", response_model=PatientRouteStepRead)
async def external_route_step(step_id: uuid.UUID, payload: RouteOutcomeRequest, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("receptionist", "nurse", "hospital_admin"))):
    step = await _load_step(session, step_id)
    target = "EXTERNAL_PURCHASE_CONFIRMED" if step.destination == "PHARMACY" else "EXTERNAL_LAB_CONFIRMED" if step.destination == "LAB" else "CANCELLED"
    result = await record_outcome(session, step_id, target, current_user, reason=payload.reason, channel=payload.channel)
    await session.commit()
    return result


@router.post("/routing/steps/{step_id}/cancel", response_model=PatientRouteStepRead)
async def cancel_route_step(step_id: uuid.UUID, payload: RouteOutcomeRequest, session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin", "receptionist"))):
    result = await record_outcome(session, step_id, "CANCELLED", current_user, reason=payload.reason, channel=payload.channel)
    await session.commit()
    return result


@router.post("/routing/expire", response_model=dict)
async def expire_routing(session: AsyncSession = Depends(get_session), current_user: dict = Depends(require_role("hospital_admin")), facility_id: uuid.UUID = Depends(get_facility_id)):
    count = await expire_steps(session, current_user, facility_id=facility_id)
    await session.commit()
    return {"expired": count}


async def _load_step(session: AsyncSession, step_id: uuid.UUID) -> PatientRouteStep:
    step = (await session.execute(select(PatientRouteStep).where(PatientRouteStep.id == step_id).with_for_update())).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Route step not found")
    return step
