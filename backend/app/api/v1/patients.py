"""
Patients API — UHID registration, search, profile management.

UHID format: YYYYMMDD-NNNN  (date of registration + daily sequence)
"""
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.core.sms import send_patient_welcome
from app.db.engine import get_session, tenant_schema_var
from app.models.public.user import Tenant
from app.services.audit_service import record_audit
from app.models.tenant.consultation import Consultation
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.lab_order import LabOrder, LabResult
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription
from app.models.tenant.visit import Visit
from app.schemas.patient import (
    PatientCreate,
    PatientDuplicateCandidate,
    PatientHistoryConsultation,
    PatientHistoryItem,
    PatientHistoryLabOrder,
    PatientHistoryLabResult,
    PatientRead,
    PatientUpdate,
)

router = APIRouter()

ALLOWED_ROLES = ("receptionist", "hospital_admin", "doctor", "nurse")
STATUS_ROLES = ("receptionist", "hospital_admin")
_UHID_GENERATION_ATTEMPTS = 5


async def _generate_uhid(session: AsyncSession) -> str:
    today = date.today().strftime("%Y%m%d")
    prefix = f"UHID-{today}-"
    # Count patients registered today
    result = await session.execute(
        select(func.count()).select_from(Patient).where(Patient.uhid.like(f"{prefix}%"))
    )
    count = result.scalar() or 0
    return f"{prefix}{count + 1:04d}"


async def _find_duplicate_candidates(
    session: AsyncSession, phone: str, aadhar_number: Optional[str]
) -> List[PatientDuplicateCandidate]:
    """Find active patients that share a phone or Aadhaar number with a new registration."""
    conditions = [Patient.phone == phone]
    if aadhar_number:
        conditions.append(Patient.aadhar_number == aadhar_number)

    rows = (await session.execute(
        select(Patient).where(Patient.is_active == True, or_(*conditions))  # noqa: E712
    )).scalars().all()

    candidates = []
    for row in rows:
        matched_on = []
        if row.phone == phone:
            matched_on.append("phone")
        if aadhar_number and row.aadhar_number == aadhar_number:
            matched_on.append("aadhar_number")
        candidates.append(
            PatientDuplicateCandidate(
                id=row.id,
                uhid=row.uhid,
                first_name=row.first_name,
                last_name=row.last_name,
                phone=row.phone,
                dob=row.dob,
                aadhar_number=row.aadhar_number,
                matched_on=matched_on,
            )
        )
    return candidates


async def _record_patient_audit(
    session: AsyncSession,
    *,
    patient_id: uuid.UUID,
    action: str,
    old_value: Optional[dict],
    new_value: Optional[dict],
    current_user: dict | None,
) -> None:
    record_audit(
        session,
        current_user=current_user,
        action=action,
        resource_type="patient",
        resource_id=patient_id,
        patient_id=patient_id,
        old_value=old_value,
        new_value=new_value,
    )


@router.post("", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
async def register_patient(
    payload: PatientCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    duplicates = await _find_duplicate_candidates(session, payload.phone, payload.aadhar_number)
    if duplicates and not payload.override_duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A patient with the same phone number or Aadhaar already exists.",
                "duplicates": [c.model_dump(mode="json") for c in duplicates],
            },
        )

    data = payload.model_dump(exclude={"override_duplicate"})

    patient = None
    last_error: Optional[IntegrityError] = None
    for _attempt in range(_UHID_GENERATION_ATTEMPTS):
        uhid = await _generate_uhid(session)
        patient = Patient(id=uuid.uuid4(), uhid=uhid, **data)
        session.add(patient)
        try:
            await session.commit()
            break
        except IntegrityError as exc:
            # Concurrent registration claimed the same UHID — regenerate and retry.
            await session.rollback()
            last_error = exc
            patient = None
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a unique UHID — please try again.",
        ) from last_error

    await session.refresh(patient)

    await _record_patient_audit(
        session,
        patient_id=patient.id,
        action="CREATE",
        old_value=None,
        new_value={
            **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in data.items()},
            "uhid": patient.uhid,
            "duplicate_override": bool(duplicates and payload.override_duplicate),
        },
        current_user=current_user,
    )
    await session.commit()

    # Send WhatsApp/SMS welcome message — best-effort, never blocks registration
    if patient.phone:
        schema = tenant_schema_var.get()
        tenant = (await session.execute(
            select(Tenant).where(Tenant.schema_name == schema)
        )).scalar_one_or_none()
        hospital_name = tenant.hospital_name if tenant else schema
        send_patient_welcome(
            to_phone=patient.phone,
            patient_name=f"{patient.first_name} {patient.last_name}",
            uhid=patient.uhid,
            hospital_name=hospital_name,
        )

    return patient


@router.get("", response_model=List[PatientRead])
async def list_patients(
    q: Optional[str] = Query(None, description="Search by name, phone, or UHID"),
    include_inactive: bool = Query(False, description="Include deactivated patient records"),
    skip: int = 0,
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    stmt = select(Patient)
    if not include_inactive:
        stmt = stmt.where(Patient.is_active == True)  # noqa: E712
    if q:
        term = f"%{q}%"
        conditions = [
            Patient.uhid.ilike(term),
            Patient.phone.ilike(term),
            func.concat(Patient.first_name, " ", Patient.last_name).ilike(term),
            Patient.first_name.ilike(term),
            Patient.last_name.ilike(term),
        ]
        # Aadhaar is sensitive PII — only match on the full 12-digit number, not partials.
        digits = q.strip()
        if digits.isdigit() and len(digits) == 12:
            conditions.append(Patient.aadhar_number == digits)
        stmt = stmt.where(or_(*conditions))
    stmt = stmt.order_by(Patient.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{patient_id}", response_model=PatientRead)
async def get_patient(
    patient_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.patch("/{patient_id}", response_model=PatientRead)
async def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    patient = await session.get(Patient, patient_id)
    if not patient or not patient.is_active:
        raise HTTPException(status_code=404, detail="Patient not found")
    update_data = payload.model_dump(exclude_unset=True)

    def _serialize(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    old_value = {}
    new_value = {}
    for field, value in update_data.items():
        current = getattr(patient, field)
        if current == value:
            continue
        old_value[field] = _serialize(current)
        new_value[field] = _serialize(value)
        setattr(patient, field, value)

    if new_value:
        await _record_patient_audit(
            session,
            patient_id=patient.id,
            action="UPDATE",
            old_value=old_value,
            new_value=new_value,
            current_user=current_user,
        )

    await session.commit()
    await session.refresh(patient)
    return patient


@router.post("/{patient_id}/deactivate", response_model=PatientRead)
async def deactivate_patient(
    patient_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*STATUS_ROLES)),
):
    """Mark a patient record inactive (e.g. duplicate/merged record). Reversible."""
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not patient.is_active:
        return patient

    patient.is_active = False
    await _record_patient_audit(
        session,
        patient_id=patient.id,
        action="UPDATE",
        old_value={"is_active": True},
        new_value={"is_active": False},
        current_user=current_user,
    )
    await session.commit()
    await session.refresh(patient)
    return patient


@router.post("/{patient_id}/reactivate", response_model=PatientRead)
async def reactivate_patient(
    patient_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*STATUS_ROLES)),
):
    """Restore a previously deactivated patient record."""
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient.is_active:
        return patient

    patient.is_active = True
    await _record_patient_audit(
        session,
        patient_id=patient.id,
        action="UPDATE",
        old_value={"is_active": False},
        new_value={"is_active": True},
        current_user=current_user,
    )
    await session.commit()
    await session.refresh(patient)
    return patient


@router.get("/{patient_id}/history", response_model=List[PatientHistoryItem])
async def get_patient_history(
    patient_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    """Return all visits for a patient enriched with consultation, prescription and lab results."""
    patient = await session.get(Patient, patient_id)
    if not patient or not patient.is_active:
        raise HTTPException(status_code=404, detail="Patient not found")

    visits = (
        await session.execute(
            select(Visit)
            .where(Visit.patient_id == patient_id)
            .order_by(Visit.created_at.desc())
        )
    ).scalars().all()

    items: List[PatientHistoryItem] = []
    for visit in visits:
        doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
        dept = await session.get(Department, visit.department_id) if visit.department_id else None

        consult = (
            await session.execute(
                select(Consultation).where(Consultation.visit_id == visit.id)
            )
        ).scalar_one_or_none()

        rx = (
            await session.execute(
                select(Prescription).where(Prescription.visit_id == visit.id)
            )
        ).scalar_one_or_none()

        lab_orders_rows = (
            await session.execute(
                select(LabOrder).where(LabOrder.visit_id == visit.id)
            )
        ).scalars().all()

        lab_items: List[PatientHistoryLabOrder] = []
        for lo in lab_orders_rows:
            lab_result = (
                await session.execute(
                    select(LabResult)
                    .where(LabResult.lab_order_id == lo.id)
                    .order_by(LabResult.reported_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            lab_items.append(
                PatientHistoryLabOrder(
                    id=lo.id,
                    tests=lo.tests,
                    status=lo.status,
                    result=PatientHistoryLabResult(
                        results=lab_result.results,
                        reported_at=lab_result.reported_at,
                        report_url=lab_result.report_url,
                    ) if lab_result else None,
                )
            )

        items.append(
            PatientHistoryItem(
                visit_id=visit.id,
                visit_date=visit.created_at,
                status=visit.status,
                doctor_name=doctor.full_name if doctor else None,
                department_name=dept.name if dept else None,
                consultation=PatientHistoryConsultation(
                    chief_complaint=consult.chief_complaint,
                    examination=consult.examination,
                    diagnosis_icd10=consult.diagnosis_icd10,
                    notes=consult.notes,
                    follow_up_date=consult.follow_up_date,
                ) if consult else None,
                medicines=rx.medicines if rx else None,
                prescription_instructions=rx.instructions if rx else None,
                lab_orders=lab_items,
            )
        )

    return items
