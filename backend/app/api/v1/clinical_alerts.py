"""Tenant-scoped clinical warnings, including longitudinal allergy alerts."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.clinical_alert import ClinicalAlert
from app.models.tenant.patient import Patient
from app.schemas.clinical_alert import ClinicalAlertCreate, ClinicalAlertRead
from app.services.audit_service import record_audit

router = APIRouter()
_READ_ROLES = ("nurse", "doctor", "pharmacist", "hospital_admin")
_WRITE_ROLES = ("nurse", "doctor", "hospital_admin")


@router.get("/patient/{patient_id}", response_model=list[ClinicalAlertRead])
async def list_patient_alerts(
    patient_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*_READ_ROLES)),
):
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    result = await session.execute(
        select(ClinicalAlert)
        .where(and_(ClinicalAlert.patient_id == patient_id, ClinicalAlert.is_active == True))  # noqa: E712
        .order_by(ClinicalAlert.severity, ClinicalAlert.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ClinicalAlertRead, status_code=status.HTTP_201_CREATED)
async def create_clinical_alert(
    payload: ClinicalAlertCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_WRITE_ROLES)),
):
    patient = await session.get(Patient, payload.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    creator_id = uuid.UUID(str(current_user["sub"]))
    alert = ClinicalAlert(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        alert_type=payload.alert_type,
        severity=payload.severity,
        description=payload.description,
        created_by_user_id=creator_id,
    )
    session.add(alert)
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="clinical_alert",
        resource_id=alert.id,
        patient_id=alert.patient_id,
        new_value=payload.model_dump(mode="json"),
    )
    await session.commit()
    await session.refresh(alert)
    return alert


@router.patch("/{alert_id}/resolve", response_model=ClinicalAlertRead)
async def resolve_clinical_alert(
    alert_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_WRITE_ROLES)),
):
    alert = await session.get(ClinicalAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Clinical alert not found")
    if not alert.is_active:
        return alert
    resolver_id = uuid.UUID(str(current_user["sub"]))
    alert.is_active = False
    alert.resolved_by_user_id = resolver_id
    alert.resolved_at = datetime.now(timezone.utc)
    record_audit(
        session,
        current_user=current_user,
        action="RESOLVE",
        resource_type="clinical_alert",
        resource_id=alert.id,
        old_value={"is_active": True},
        new_value={"is_active": False, "resolved_by_user_id": resolver_id, "resolved_at": alert.resolved_at},
    )
    await session.commit()
    await session.refresh(alert)
    return alert
