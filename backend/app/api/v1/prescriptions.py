"""
Prescriptions API — build and retrieve prescriptions for a visit.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import require_role
from app.core.prescription_pdf_service import build_prescription_pdf, canonical_prescription_snapshot
from app.db.engine import get_session
from app.models.tenant.doctor import Doctor
from app.models.tenant.document import DOCUMENT_TYPE_PRESCRIPTION
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.visit import Visit, VisitStatus
from app.models.tenant.medicine_master import MedicineMaster
from app.schemas.document import DocumentVersionRead
from app.schemas.prescription import PrescriptionCreate, PrescriptionRead, PrescriptionUpdate
from app.services.document_service import (
    DocumentFinalizationError,
    DocumentIntegrityError,
    finalize_document,
    get_version as get_document_version,
    list_versions as list_document_versions,
    read_document_bytes,
)
from app.services.document_storage import LocalFileDocumentStorage
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.services.audit_service import record_audit
from app.websocket.manager import ws_manager

router = APIRouter()

_prescription_document_storage = LocalFileDocumentStorage()


@router.post("", response_model=PrescriptionRead, status_code=status.HTTP_201_CREATED)
async def create_prescription(
    payload: PrescriptionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("doctor", "hospital_admin")),
):
    visit = await session.get(Visit, payload.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    patient = await session.get(Patient, visit.patient_id)
    uhid = patient.uhid if patient else None

    item_source = payload.items if payload.items is not None else payload.medicines
    medicines_data = []
    for item in item_source or []:
        data = item.model_dump(mode="json")
        if item.medicine_master_id:
            master = await session.get(MedicineMaster, item.medicine_master_id)
            if not master or not master.is_active:
                raise HTTPException(status_code=422, detail="Selected medicine is missing or inactive")
            data["medicine_master_id"] = str(item.medicine_master_id)
            data["medicine"] = master.generic_name
            data["name_snapshot"] = master.brand_name or master.generic_name
            data["strength"] = item.strength or master.strength
            data["dosage_form"] = item.dosage_form or master.dosage_form
        medicines_data.append(data)

    # Upsert — each visit has at most one prescription
    existing_rx = (await session.execute(
        select(Prescription).where(Prescription.visit_id == payload.visit_id).limit(1)
    )).scalar_one_or_none()

    if existing_rx:
        existing_rx.medicines = medicines_data
        existing_rx.instructions = payload.instructions
        existing_rx.consultation_id = payload.consultation_id or existing_rx.consultation_id
        existing_rx.doctor_id = payload.doctor_id or visit.doctor_id or existing_rx.doctor_id
        existing_rx.status = "finalized"
        existing_rx.items = [
            PrescriptionItem(
                id=uuid.uuid4(),
                medicine_master_id=item.medicine_master_id,
                medicine=medicines_data[i].get("medicine", item.medicine),
                strength=item.strength,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                duration=item.duration,
                quantity=item.quantity,
                instructions=item.instructions,
                dosage_form=item.dosage_form,
                timing_relative_to_food=item.timing_relative_to_food,
            )
            for i, item in enumerate(item_source or [])
        ]
        prescription = existing_rx
    else:
        prescription = Prescription(
            id=uuid.uuid4(),
            visit_id=payload.visit_id,
            consultation_id=payload.consultation_id,
            doctor_id=payload.doctor_id or visit.doctor_id,
            uhid=uhid,
            medicines=medicines_data,
            instructions=payload.instructions,
            status="finalized",
        )
        prescription.items = [
            PrescriptionItem(
                id=uuid.uuid4(),
                medicine_master_id=item.medicine_master_id,
                medicine=medicines_data[i].get("medicine", item.medicine),
                strength=item.strength,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                duration=item.duration,
                quantity=item.quantity,
                instructions=item.instructions,
                dosage_form=item.dosage_form,
                timing_relative_to_food=item.timing_relative_to_food,
            )
            for i, item in enumerate(item_source or [])
        ]
        session.add(prescription)

    # If doctor included lab tests, upsert a LabOrder alongside the prescription
    if payload.lab_tests:
        existing_order = (await session.execute(
            select(LabOrder).where(LabOrder.visit_id == payload.visit_id).limit(1)
        )).scalar_one_or_none()
        if existing_order:
            existing_order.tests = [t.model_dump() for t in payload.lab_tests]
            existing_order.status = "ordered"
        else:
            lab_order = LabOrder(
                id=uuid.uuid4(),
                visit_id=payload.visit_id,
                uhid=uhid,
                tests=[t.model_dump() for t in payload.lab_tests],
                status="ordered",
            )
            session.add(lab_order)

    # Prescription sign-off closes the doctor workflow stage.
    if visit.status == VisitStatus.IN_CONSULTATION.value:
        try:
            await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.CONSULTATION_COMPLETED,
                current_user.get("sub"),
                VisitTransitionSource.DOCTOR,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"Cannot complete consultation via prescription: {str(exc)}") from exc

    record_audit(
        session,
        current_user=current_user,
        action="UPDATE" if existing_rx else "CREATE",
        resource_type="prescription",
        resource_id=prescription.id,
        patient_id=visit.patient_id,
        visit_id=visit.id,
        new_value={"status": prescription.status, "medicines": medicines_data, "has_lab_tests": bool(payload.lab_tests)},
    )
    await session.commit()
    loaded = await session.execute(
        select(Prescription)
        .options(selectinload(Prescription.items))
        .where(Prescription.id == prescription.id)
    )
    prescription = loaded.scalar_one()

    # Notify pharmacy and nurse dispatch queue
    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "pharmacy:update", {
        "event": "prescription_created",
        "prescription_id": str(prescription.id),
        "visit_id": str(prescription.visit_id),
        "has_lab_tests": bool(payload.lab_tests),
    })
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "prescription_saved",
        "visit_id": str(prescription.visit_id),
    })

    return prescription


@router.patch("/{visit_id}", response_model=PrescriptionRead)
async def update_prescription(
    visit_id: uuid.UUID,
    payload: PrescriptionUpdate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "hospital_admin", "super_admin")),
):
    rx = (await session.execute(
        select(Prescription).options(selectinload(Prescription.items)).where(Prescription.visit_id == visit_id)
    )).scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found for this visit")

    item_source = payload.items if payload.items is not None else payload.medicines
    if item_source is not None:
        normalized_items = []
        for item in item_source:
            item_data = item.model_dump(mode="json")
            if item.medicine_master_id:
                master = await session.get(MedicineMaster, item.medicine_master_id)
                if not master or not master.is_active:
                    raise HTTPException(status_code=422, detail="Selected medicine is missing or inactive")
                item_data["medicine_master_id"] = str(item.medicine_master_id)
                item_data["medicine"] = master.generic_name
                item_data["name_snapshot"] = master.brand_name or master.generic_name
                item_data["strength"] = item.strength or master.strength
                item_data["dosage_form"] = item.dosage_form or master.dosage_form
            normalized_items.append(item_data)
        rx.medicines = normalized_items
        rx.items = [
            PrescriptionItem(
                id=uuid.uuid4(),
                medicine=normalized_items[i].get("medicine", item.medicine),
                medicine_master_id=item.medicine_master_id,
                strength=item.strength,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                duration=item.duration,
                quantity=item.quantity,
                instructions=item.instructions,
                dosage_form=item.dosage_form,
                timing_relative_to_food=item.timing_relative_to_food,
            )
            for i, item in enumerate(item_source)
        ]
    if payload.consultation_id is not None:
        rx.consultation_id = payload.consultation_id
    if payload.doctor_id is not None:
        rx.doctor_id = payload.doctor_id
    if payload.instructions is not None:
        rx.instructions = payload.instructions

    record_audit(
        session,
        current_user=_,
        action="UPDATE",
        resource_type="prescription",
        resource_id=rx.id,
        visit_id=visit_id,
        new_value={"medicines": rx.medicines, "instructions": rx.instructions},
    )

    await session.commit()
    loaded = await session.execute(
        select(Prescription)
        .options(selectinload(Prescription.items))
        .where(Prescription.id == rx.id)
    )
    rx = loaded.scalar_one()
    return rx


@router.get("/{visit_id}", response_model=PrescriptionRead)
async def get_prescription(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "nurse", "pharmacist", "hospital_admin")),
):
    rx = (await session.execute(
        select(Prescription).options(selectinload(Prescription.items)).where(Prescription.visit_id == visit_id)
    )).scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found for this visit")

    # Fetch lab tests from the linked LabOrder (they are stored there, not on the prescription)
    lab_order = (await session.execute(
        select(LabOrder).where(LabOrder.visit_id == visit_id)
    )).scalar_one_or_none()

    data = PrescriptionRead.model_validate(rx)
    data.lab_tests = lab_order.tests if lab_order else None
    return data


def _prescription_to_snapshot(rx: Prescription, patient: Patient | None, doctor: Doctor | None) -> dict:
    return canonical_prescription_snapshot(
        {
            "id": rx.id,
            "visit_id": rx.visit_id,
            "uhid": rx.uhid,
            "status": rx.status,
            "instructions": rx.instructions,
            "medicines": rx.medicines,
            "created_at": rx.created_at,
            "patient_id": patient.id if patient else None,
            "patient_name": f"{patient.first_name} {patient.last_name}" if patient else None,
            "doctor_id": rx.doctor_id,
            "doctor_name": doctor.full_name if doctor else None,
        }
    )


@router.post("/{visit_id}/documents/finalize", response_model=DocumentVersionRead, status_code=status.HTTP_201_CREATED)
async def finalize_prescription_document(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("doctor", "hospital_admin")),
):
    rx = (await session.execute(
        select(Prescription).where(Prescription.visit_id == visit_id)
    )).scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found for this visit")
    if rx.status != "finalized":
        raise HTTPException(status_code=400, detail="Prescription document can be finalized only once the prescription is finalized")

    visit = await session.get(Visit, rx.visit_id)
    patient = await session.get(Patient, visit.patient_id) if visit else None
    doctor = await session.get(Doctor, rx.doctor_id) if rx.doctor_id else None
    snapshot = _prescription_to_snapshot(rx, patient, doctor)

    generated_by_user_id = None
    sub = current_user.get("sub")
    if sub:
        try:
            generated_by_user_id = uuid.UUID(str(sub))
        except ValueError:
            generated_by_user_id = None

    try:
        document = await finalize_document(
            session,
            document_type=DOCUMENT_TYPE_PRESCRIPTION,
            parent_id=rx.id,
            snapshot=snapshot,
            render_pdf=build_prescription_pdf,
            storage=_prescription_document_storage,
            generated_by_user_id=generated_by_user_id,
        )
    except DocumentFinalizationError as exc:
        raise HTTPException(status_code=409, detail="Could not finalize prescription document, please retry") from exc

    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="prescription_document",
        resource_id=document.id,
        patient_id=visit.patient_id if visit else None,
        visit_id=rx.visit_id,
        new_value={
            "prescription_id": str(rx.id),
            "version": document.version,
            "checksum_sha256": document.checksum_sha256,
            "storage_key": document.storage_key,
        },
    )
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/{visit_id}/documents", response_model=list[DocumentVersionRead])
async def list_prescription_documents(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "nurse", "pharmacist", "hospital_admin")),
):
    rx = (await session.execute(
        select(Prescription).where(Prescription.visit_id == visit_id)
    )).scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found for this visit")
    return await list_document_versions(session, DOCUMENT_TYPE_PRESCRIPTION, rx.id)


@router.get("/{visit_id}/documents/{version}/download")
async def download_prescription_document(
    visit_id: uuid.UUID,
    version: int,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("doctor", "nurse", "pharmacist", "hospital_admin")),
):
    rx = (await session.execute(
        select(Prescription).where(Prescription.visit_id == visit_id)
    )).scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found for this visit")
    document = await get_document_version(session, DOCUMENT_TYPE_PRESCRIPTION, rx.id, version)
    if not document:
        raise HTTPException(status_code=404, detail="Prescription document version not found")

    try:
        pdf_bytes = read_document_bytes(_prescription_document_storage, document)
    except DocumentIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="prescription-{rx.id}-v{version}.pdf"'},
    )
