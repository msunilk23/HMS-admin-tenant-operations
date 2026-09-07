from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant.consultation import Consultation
from app.models.tenant.doctor import Doctor
from app.models.tenant.document_request import PrescriptionDocumentRequest
from app.models.tenant.patient import Patient
from app.models.tenant.patient_route import PatientRoute
from app.models.tenant.prescription import Prescription
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.core.prescription_pdf_service import canonical_prescription_snapshot
from app.services.audit_service import record_audit
from app.services.patient_routing import ensure_route
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService


def _document_snapshot(prescription: Prescription, visit: Visit, patient: Patient | None, doctor: Doctor | None) -> dict:
    medicines = [{
        "medicine": item.medicine,
        "name_snapshot": item.medicine,
        "medicine_product_id": str(item.medicine_product_id) if item.medicine_product_id else None,
        "generic_name_snapshot": item.generic_name_snapshot,
        "brand_name_snapshot": item.brand_name_snapshot,
        "strength": item.strength,
        "strength_snapshot": item.strength_snapshot,
        "dosage_form": item.dosage_form,
        "dosage_form_snapshot": item.dosage_form_snapshot,
        "route": item.route,
        "route_snapshot": item.route_snapshot,
        "dose": item.dose,
        "frequency": item.frequency,
        "duration": item.duration,
        "quantity": item.quantity,
        "instructions": item.instructions,
    } for item in prescription.items]
    return canonical_prescription_snapshot({
        "id": prescription.id, "visit_id": visit.id, "uhid": prescription.uhid,
        "status": prescription.status, "instructions": prescription.instructions,
        "medicines": medicines, "created_at": prescription.created_at,
        "patient_id": patient.id if patient else None,
        "patient_name": f"{patient.first_name} {patient.last_name}" if patient else None,
        "doctor_id": doctor.id if doctor else prescription.doctor_id,
        "doctor_name": doctor.full_name if doctor else None,
        "version": prescription.version,
    })


async def complete_consultation(session: AsyncSession, visit_id: uuid.UUID, current_user: dict, *, now: datetime | None = None) -> tuple[Visit, PatientRoute]:
    now = now or datetime.now(timezone.utc)
    visit = (await session.execute(select(Visit).where(Visit.id == visit_id).with_for_update())).scalar_one_or_none()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    if current_user.get("role") == "doctor":
        doctor = (await session.execute(select(Doctor).where(Doctor.user_id == uuid.UUID(str(current_user["sub"]))))).scalar_one_or_none()
        if not doctor or visit.doctor_id != doctor.id:
            raise HTTPException(status_code=403, detail="This visit is not assigned to your doctor")

    consultation = (await session.execute(select(Consultation).where(Consultation.visit_id == visit.id).with_for_update())).scalar_one_or_none()
    if not consultation:
        raise HTTPException(status_code=422, detail="Consultation is required before completion")
    if consultation.status not in {"completed", "amended"}:
        raise HTTPException(status_code=422, detail="Consultation must be finalized before completion")
    prescription = (await session.execute(select(Prescription).options(selectinload(Prescription.items)).where(Prescription.visit_id == visit.id).with_for_update())).scalar_one_or_none()
    if prescription and prescription.status != "finalized":
        raise HTTPException(status_code=422, detail="Prescription must be finalized before completion")

    if visit.status == VisitStatus.CLOSED.value:
        route = (await session.execute(select(PatientRoute).where(PatientRoute.visit_id == visit.id))).scalar_one_or_none()
        if not route:
            route = await ensure_route(session, visit, consultation, current_user, now=now)
        return visit, route
    if visit.status != VisitStatus.IN_CONSULTATION.value:
        raise HTTPException(status_code=409, detail=f"Consultation cannot be completed from {visit.status}")

    consultation.completed_at = consultation.completed_at or now
    consultation.status = "completed"
    await VisitWorkflowService.transition(session, visit, VisitStatus.CONSULTATION_COMPLETED, current_user.get("sub"), VisitTransitionSource.DOCTOR)
    await VisitWorkflowService.transition(session, visit, VisitStatus.CLOSED, current_user.get("sub"), VisitTransitionSource.DOCTOR)
    token = (await session.execute(select(QueueToken).where(QueueToken.visit_id == visit.id).with_for_update())).scalar_one_or_none()
    if token:
        token.status = "completed"
        token.completed_at = token.completed_at or now

    route = await ensure_route(session, visit, consultation, current_user, now=now)
    if prescription and (prescription.items or prescription.medicines):
        existing_request = (await session.execute(select(PrescriptionDocumentRequest).where(PrescriptionDocumentRequest.prescription_id == prescription.id).with_for_update())).scalar_one_or_none()
        if not existing_request:
            patient = await session.get(Patient, visit.patient_id)
            doctor = await session.get(Doctor, prescription.doctor_id) if prescription.doctor_id else None
            session.add(PrescriptionDocumentRequest(id=uuid.uuid4(), prescription_id=prescription.id, visit_id=visit.id, snapshot_json=_document_snapshot(prescription, visit, patient, doctor), status="PENDING_GENERATION"))
    record_audit(session, current_user=current_user, action="UPDATE", resource_type="consultation_completion", resource_id=consultation.id, patient_id=visit.patient_id, visit_id=visit.id, new_value={"visit_status": visit.status, "route_id": str(route.id)})
    return visit, route