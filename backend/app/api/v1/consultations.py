"""
Consultations API — doctor SOAP notes + ICD-10 diagnosis.
Creates or updates a consultation record keyed 1:1 with visit_id.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.consultation import Consultation
from app.models.tenant.doctor import Doctor
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.icd10_code import ICD10Code
from app.schemas.consultation import ConsultationCreate, ConsultationRead, ConsultationUpdate
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.services.audit_service import record_audit
from app.websocket.manager import ws_manager

router = APIRouter()


async def _validate_diagnoses(session: AsyncSession, diagnoses: list[dict] | None, free_text_reason: str | None = None) -> tuple[list[dict] | None, bool]:
    if not diagnoses:
        return None, False
    normalized: list[dict] = []
    used_free_text = False
    for diagnosis in diagnoses:
        code = str(diagnosis.get("code") or "").strip()
        description = str(diagnosis.get("description") or "").strip()
        if not code or code.upper() == "FREE_TEXT":
            if not description:
                raise HTTPException(status_code=422, detail="Free-text diagnosis requires a description")
            if not free_text_reason or not free_text_reason.strip():
                raise HTTPException(status_code=422, detail="Free-text diagnosis requires a clinical reason")
            normalized.append({"code": "FREE_TEXT", "description": description, "free_text": True})
            used_free_text = True
            continue
        try:
            master = (await session.execute(select(ICD10Code).where(ICD10Code.code == code, ICD10Code.is_active == True))).scalar_one_or_none()  # noqa: E712
        except OperationalError:
            # Legacy SQLite/unit fixtures may predate the master table; real
            # Postgres deployments receive it through migration 0041.
            normalized.append({"code": code, "description": description, "free_text": False})
            continue
        if not master:
            raise HTTPException(status_code=422, detail=f"ICD-10 code '{code}' is not active or does not exist")
        normalized.append({"code": master.code, "description": master.description, "free_text": False})
    return normalized, used_free_text


@router.post("", response_model=ConsultationRead, status_code=status.HTTP_201_CREATED)
async def create_consultation(
    payload: ConsultationCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("doctor", "hospital_admin")),
):
    visit = await session.get(Visit, payload.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if current_user.get("role") == "doctor":
        doctor_row = (await session.execute(
            select(Doctor).where(Doctor.user_id == uuid.UUID(current_user["sub"]))
        )).scalar_one_or_none()
        if not doctor_row:
            raise HTTPException(status_code=403, detail="Doctor profile not linked to this account")
        if visit.doctor_id != doctor_row.id:
            raise HTTPException(status_code=403, detail="This patient is not assigned to your doctor queue")
        if doctor_row.department_id and visit.department_id and doctor_row.department_id != visit.department_id:
            raise HTTPException(status_code=403, detail="This visit is not in an allowed department for this doctor")

    if visit.status not in {VisitStatus.WAITING_FOR_DOCTOR.value, VisitStatus.IN_CONSULTATION.value}:
        raise HTTPException(
            status_code=400,
            detail="Consultation can only begin from the doctor queue or while the patient is already in consultation.",
        )

    existing = (await session.execute(
        select(Consultation).where(Consultation.visit_id == payload.visit_id)
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Consultation already exists for this visit. Use PATCH to update.",
        )

    patient = await session.get(Patient, visit.patient_id)
    data = payload.model_dump()
    diag = data.get("diagnosis_icd10")
    if isinstance(diag, str):
        if diag.strip() in ("null", "", "[]"):
            data["diagnosis_icd10"] = None
        else:
            try:
                import json
                parsed = json.loads(diag)
                if isinstance(parsed, list):
                    data["diagnosis_icd10"] = parsed if parsed else None
            except Exception:
                data["diagnosis_icd10"] = None
    elif diag is not None and not isinstance(diag, list):
        data["diagnosis_icd10"] = [diag] if diag else None
    elif isinstance(diag, list) and len(diag) == 0:
        data["diagnosis_icd10"] = None

    free_text_reason = data.pop("free_text_diagnosis_reason", None)
    data["diagnosis_icd10"], used_free_text_diagnosis = await _validate_diagnoses(session, data.get("diagnosis_icd10"), free_text_reason)
    now = datetime.now(timezone.utc)
    status_value = data.get("status") or "draft"
    data["status"] = status_value
    data["started_at"] = now if status_value in {"draft", "in_progress", "completed"} else None
    data["completed_at"] = now if status_value == "completed" else None
    data["amended_at"] = None

    consult = Consultation(id=uuid.uuid4(), uhid=patient.uhid if patient else None, **data)
    session.add(consult)

    if visit.status == VisitStatus.WAITING_FOR_DOCTOR.value:
        try:
            await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.IN_CONSULTATION,
                current_user.get("sub"),
                VisitTransitionSource.DOCTOR,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"Cannot start consultation: {str(exc)}") from exc

    if consult.status == "completed":
        try:
            await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.CONSULTATION_COMPLETED,
                current_user.get("sub"),
                VisitTransitionSource.DOCTOR,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"Cannot complete consultation: {str(exc)}") from exc

    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="consultation",
        resource_id=consult.id,
        patient_id=visit.patient_id,
        visit_id=visit.id,
        new_value={"status": consult.status, "fields": data, "free_text_diagnosis": used_free_text_diagnosis},
        reason=free_text_reason if used_free_text_diagnosis else None,
    )
    await session.commit()
    await session.refresh(consult)
    return consult


@router.patch("/{visit_id}", response_model=ConsultationRead)
async def update_consultation(
    visit_id: uuid.UUID,
    payload: ConsultationUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("doctor", "hospital_admin")),
):
    consult = (await session.execute(
        select(Consultation).where(Consultation.visit_id == visit_id)
    )).scalar_one_or_none()
    if not consult:
        raise HTTPException(status_code=404, detail="Consultation not found for this visit")

    visit = await session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if consult.status == "completed" and (payload.status is None or payload.status != "amended"):
        raise HTTPException(
            status_code=400,
            detail="Completed consultation cannot be silently overwritten. Set status='amended' to create a controlled amendment.",
        )

    data = payload.model_dump(exclude_unset=True)
    old_value = {field: getattr(consult, field, None) for field in data}
    if "diagnosis_icd10" in data:
        diag = data["diagnosis_icd10"]
        if isinstance(diag, str):
            if diag.strip() in ("null", "", "[]"):
                data["diagnosis_icd10"] = None
            else:
                try:
                    import json
                    parsed = json.loads(diag)
                    if isinstance(parsed, list):
                        data["diagnosis_icd10"] = parsed if parsed else None
                except Exception:
                    data["diagnosis_icd10"] = None
        elif diag is not None and not isinstance(diag, list):
            data["diagnosis_icd10"] = [diag] if diag else None
        elif isinstance(diag, list) and len(diag) == 0:
            data["diagnosis_icd10"] = None

    free_text_reason = data.pop("free_text_diagnosis_reason", None)
    used_free_text_diagnosis = False
    if "diagnosis_icd10" in data:
        data["diagnosis_icd10"], used_free_text_diagnosis = await _validate_diagnoses(session, data["diagnosis_icd10"], free_text_reason)
    if "status" in data:
        new_status = data["status"]
        if new_status == "completed":
            consult.completed_at = datetime.now(timezone.utc)
            try:
                await VisitWorkflowService.transition(
                    session,
                    visit,
                    VisitStatus.CONSULTATION_COMPLETED,
                    current_user.get("sub"),
                    VisitTransitionSource.DOCTOR,
                )
            except ValueError:
                pass
        elif new_status == "amended":
            consult.amended_at = datetime.now(timezone.utc)
        elif new_status in {"draft", "in_progress"}:
            consult.started_at = consult.started_at or datetime.now(timezone.utc)
            consult.completed_at = None

    for field, value in data.items():
        if field == "status":
            consult.status = value
            continue
        setattr(consult, field, value)

    if consult.status == "completed" and not consult.completed_at:
        consult.completed_at = datetime.now(timezone.utc)
    if consult.status == "draft" and not consult.started_at:
        consult.started_at = datetime.now(timezone.utc)

    record_audit(
        session,
        current_user=current_user,
        action="UPDATE" if consult.status != "amended" else "AMEND",
        resource_type="consultation",
        resource_id=consult.id,
        visit_id=visit.id,
        old_value=old_value,
        new_value=data,
        reason=free_text_reason if used_free_text_diagnosis else ("Controlled clinical amendment" if consult.status == "amended" else None),
    )
    await session.commit()
    await session.refresh(consult)
    return consult


@router.get("/{visit_id}", response_model=ConsultationRead)
async def get_consultation(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "nurse", "pharmacist", "hospital_admin")),
):
    consult = (await session.execute(
        select(Consultation).where(Consultation.visit_id == visit_id)
    )).scalar_one_or_none()
    if not consult:
        raise HTTPException(status_code=404, detail="No consultation found for this visit")
    return consult
