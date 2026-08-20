"""
Vitals API — nurse records patient vitals for a visit.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role, require_feature
from app.db.engine import get_session
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.vitals import Vitals
from app.schemas.vitals import VitalsCreate, VitalsRead
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.websocket.manager import ws_manager

router = APIRouter(dependencies=[Depends(require_feature("vitals"))])


@router.post("", response_model=VitalsRead, status_code=status.HTTP_201_CREATED)
async def record_vitals(
    payload: VitalsCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "doctor", "hospital_admin")),
):
    visit = await session.get(Visit, payload.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    allowed_states = {VisitStatus.WAITING_FOR_NURSE.value, VisitStatus.IN_PRE_VITAL.value}
    if visit.status not in allowed_states:
        raise HTTPException(
            status_code=400,
            detail="Pre-vitals can only be recorded while the patient is waiting for nurse assessment or already in pre-vitals.",
        )

    if visit.status == VisitStatus.WAITING_FOR_NURSE.value:
        try:
            await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.IN_PRE_VITAL,
                current_user.get("sub"),
                VisitTransitionSource.NURSE,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    patient = await session.get(Patient, visit.patient_id)

    bmi_value: float | None = None
    if payload.weight and payload.height and payload.height > 0:
        height_m = payload.height / 100
        bmi_value = round(payload.weight / (height_m ** 2), 1)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    payload_data = payload.model_dump()
    payload_data["bmi"] = bmi_value
    payload_data["uhid"] = patient.uhid if patient else None
    payload_data["recorded_by_user_id"] = uuid.UUID(current_user["sub"])
    payload_data["started_at"] = now
    payload_data["completed_at"] = now if payload.status == "completed" else None
    payload_data["status"] = payload.status
    vitals = Vitals(**payload_data)
    session.add(vitals)

    if payload.status == "completed":
        try:
            await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.WAITING_FOR_DOCTOR,
                current_user.get("sub"),
                VisitTransitionSource.NURSE,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(vitals)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "vitals_recorded",
        "visit_id": str(visit.id),
        "patient_id": str(visit.patient_id),
        "status": visit.status,
        "vitals_status": vitals.status,
    })

    return vitals


@router.get("/{visit_id}", response_model=VitalsRead)
async def get_vitals(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("nurse", "doctor", "hospital_admin", "super_admin")),
):
    result = await session.execute(
        select(Vitals).where(Vitals.visit_id == visit_id).order_by(Vitals.recorded_at.desc()).limit(1)
    )
    vitals = result.scalar_one_or_none()
    if not vitals:
        raise HTTPException(status_code=404, detail="Vitals not found for this visit")
    return vitals
