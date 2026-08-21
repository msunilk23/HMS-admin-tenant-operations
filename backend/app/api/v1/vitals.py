"""
Vitals API — nurse records patient vitals for a visit.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role, require_feature
from app.db.engine import get_session
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.vitals import Vitals
from app.schemas.vitals import VitalsCreate, VitalsRead
from app.services.audit_service import record_audit
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.websocket.manager import ws_manager

router = APIRouter(dependencies=[Depends(require_feature("vitals"))])

# Fields copied verbatim from the payload onto the Vitals row (excludes
# visit_id/status/bmi/audit & timestamp columns, which are set separately).
_VITALS_FIELDS = (
    "temperature", "pulse", "respiratory_rate", "bp_systolic", "bp_diastolic",
    "spo2", "pain_score", "height", "weight", "blood_glucose", "chief_complaint",
    "allergies", "known_no_allergies", "general_condition", "level_of_consciousness",
    "nurse_notes",
)


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

    # A single Vitals row per visit — reload the existing draft (if any) instead
    # of inserting a new row every time the nurse saves.
    existing = (
        await session.execute(
            select(Vitals).where(Vitals.visit_id == payload.visit_id).order_by(Vitals.recorded_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if existing and existing.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pre-vitals have already been completed for this visit and cannot be re-submitted.",
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

    now = datetime.now(timezone.utc)
    was_draft_before = existing is not None
    old_snapshot = (
        {f: getattr(existing, f) for f in _VITALS_FIELDS} | {"status": existing.status}
        if existing else None
    )

    if existing is not None:
        vitals = existing
        for field in _VITALS_FIELDS:
            setattr(vitals, field, getattr(payload, field))
        vitals.bmi = bmi_value
        vitals.status = payload.status
        vitals.recorded_by_user_id = uuid.UUID(current_user["sub"])
        if vitals.started_at is None:
            vitals.started_at = now
        if payload.status == "completed":
            vitals.completed_at = now
    else:
        vitals = Vitals(
            visit_id=payload.visit_id,
            uhid=patient.uhid if patient else None,
            **{f: getattr(payload, f) for f in _VITALS_FIELDS},
            bmi=bmi_value,
            status=payload.status,
            recorded_by_user_id=uuid.UUID(current_user["sub"]),
            started_at=now,
            completed_at=now if payload.status == "completed" else None,
        )
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

    await session.flush()  # populate vitals.id for new rows before audit/commit

    record_audit(
        session,
        current_user=current_user,
        action="vitals.completed" if payload.status == "completed" else "vitals.draft_saved",
        resource_type="vitals",
        resource_id=vitals.id,
        patient_id=visit.patient_id,
        visit_id=visit.id,
        old_value=old_snapshot,
        new_value={f: getattr(vitals, f) for f in _VITALS_FIELDS} | {"status": vitals.status, "bmi": vitals.bmi},
        reason="draft updated" if was_draft_before else "vitals created",
    )

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
