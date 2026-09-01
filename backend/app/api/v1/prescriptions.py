"""
Prescriptions API — build and retrieve prescriptions for a visit.
"""
import uuid
import re
from decimal import Decimal, InvalidOperation

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
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.medicine_master import MedicineMaster
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.route import Route
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

_FREQUENCY_UNITS = {
    "OD": Decimal("1"),
    "BD": Decimal("2"),
    "TID": Decimal("3"),
    "QID": Decimal("4"),
    "QHS": Decimal("1"),
    "Q4H": Decimal("6"),
    "Q6H": Decimal("4"),
    "Q8H": Decimal("3"),
}


def _format_quantity(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _parse_dose(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.strip().replace("½", "0.5")
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)", normalized)
    if not match:
        return None
    try:
        dose = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return dose if dose > 0 else None


def _daily_frequency_units(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized in _FREQUENCY_UNITS:
        return _FREQUENCY_UNITS[normalized]
    parts = normalized.split("-")
    if len(parts) != 4:
        return None
    try:
        slots = [Decimal(part.replace("½", "0.5")) for part in parts]
    except InvalidOperation:
        return None
    return sum(slots, Decimal("0"))


def _duration_days(value: str | None) -> int | None:
    if not value or value.strip().lower() == "ongoing":
        return None
    match = re.match(r"^\s*(\d+)\s*(day|days|month|months)\s*$", value, re.IGNORECASE)
    if not match:
        return None
    amount = int(match.group(1))
    return amount * 30 if match.group(2).lower().startswith("month") else amount


def _calculate_unit_quantity(*, dose: str | None, frequency: str | None, duration: str | None) -> str | None:
    dose_value = _parse_dose(dose)
    frequency_units = _daily_frequency_units(frequency)
    duration_days = _duration_days(duration)
    if dose_value is None or frequency_units is None or duration_days is None or frequency_units == 0:
        return None
    return _format_quantity(dose_value * frequency_units * duration_days)


def _apply_quantity_policy(data: dict, item, calculation_type: str | None = None) -> None:
    auto_quantity = None
    if calculation_type == "UNIT":
        auto_quantity = _calculate_unit_quantity(
            dose=item.dose,
            frequency=item.frequency,
            duration=item.duration,
        )
    supplied_quantity = item.quantity.strip() if item.quantity and item.quantity.strip() else None
    override_flag = bool(auto_quantity and supplied_quantity and supplied_quantity != auto_quantity)
    if override_flag and not item.quantity_override_reason:
        raise HTTPException(status_code=422, detail="Reason required when quantity overrides the calculated quantity")
    data["auto_quantity"] = auto_quantity
    data["final_quantity"] = supplied_quantity or auto_quantity
    data["quantity_override_flag"] = override_flag
    data["quantity_override_reason"] = item.quantity_override_reason.strip() if item.quantity_override_reason else None
    data["quantity"] = data["final_quantity"]


async def _normalize_medicine_item(session: AsyncSession, item) -> dict:
    data = item.model_dump(mode="json")
    if item.medicine_product_id:
        product = await session.get(MedicineProduct, item.medicine_product_id)
        if not product or not product.is_active:
            raise HTTPException(status_code=422, detail="Selected medicine product is missing or inactive")
        generic = await session.get(GenericMedicine, product.generic_medicine_id)
        dosage_form = await session.get(DosageForm, product.dosage_form_id)
        route = await session.get(Route, product.default_route_id) if product.default_route_id else None
        if not generic or not generic.is_active or not dosage_form or not dosage_form.is_active:
            raise HTTPException(status_code=422, detail="Selected medicine product has an inactive master reference")
        if product.default_route_id and (not route or not route.is_active):
            raise HTTPException(status_code=422, detail="Selected medicine product has an inactive route reference")
        data["medicine_product_id"] = str(product.id)
        data["medicine"] = product.brand_name or generic.name
        data["strength"] = item.strength or product.strength
        data["dosage_form"] = item.dosage_form or dosage_form.name
        data["generic_name_snapshot"] = generic.name
        data["brand_name_snapshot"] = product.brand_name
        data["strength_snapshot"] = product.strength
        data["dosage_form_snapshot"] = dosage_form.name
        data["route_snapshot"] = route.name if route else None
        _apply_quantity_policy(data, item, dosage_form.calculation_type)
        return data

    if item.medicine_master_id:
        master = await session.get(MedicineMaster, item.medicine_master_id)
        if not master or not master.is_active:
            raise HTTPException(status_code=422, detail="Selected medicine is missing or inactive")
        data["medicine_master_id"] = str(item.medicine_master_id)
        data["medicine"] = master.generic_name
        data["name_snapshot"] = master.brand_name or master.generic_name
        data["strength"] = item.strength or master.strength
        data["dosage_form"] = item.dosage_form or master.dosage_form
        _apply_quantity_policy(data, item)
        return data

    if not item.is_free_text or not item.free_text_reason or not item.free_text_reason.strip():
        raise HTTPException(status_code=422, detail="Select a medicine or provide a reason for free-text medicine")
    if not item.medicine.strip():
        raise HTTPException(status_code=422, detail="Free-text medicine name is required")
    data["free_text_reason"] = item.free_text_reason.strip()
    _apply_quantity_policy(data, item)
    return data


def _prescription_item_from_data(item, data: dict) -> PrescriptionItem:
    return PrescriptionItem(
        id=uuid.uuid4(),
        medicine_master_id=item.medicine_master_id,
        medicine_product_id=item.medicine_product_id,
        medicine=data.get("medicine", item.medicine),
        strength=data.get("strength", item.strength),
        dose=item.dose,
        route=item.route,
        frequency=item.frequency,
        duration=item.duration,
        quantity=data.get("quantity", item.quantity),
        auto_quantity=data.get("auto_quantity"),
        final_quantity=data.get("final_quantity"),
        quantity_override_flag=data.get("quantity_override_flag", False),
        quantity_override_reason=data.get("quantity_override_reason"),
        instructions=item.instructions,
        dosage_form=data.get("dosage_form", item.dosage_form),
        timing_relative_to_food=item.timing_relative_to_food,
        generic_name_snapshot=data.get("generic_name_snapshot"),
        brand_name_snapshot=data.get("brand_name_snapshot"),
        strength_snapshot=data.get("strength_snapshot"),
        dosage_form_snapshot=data.get("dosage_form_snapshot"),
        route_snapshot=data.get("route_snapshot"),
    )


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
        data = await _normalize_medicine_item(session, item)
        medicines_data.append(data)

    # Upsert — each visit has at most one prescription
    existing_rx = (await session.execute(
        select(Prescription).options(selectinload(Prescription.items)).where(Prescription.visit_id == payload.visit_id).limit(1)
    )).scalar_one_or_none()

    if existing_rx:
        existing_rx.medicines = medicines_data
        existing_rx.instructions = payload.instructions
        existing_rx.consultation_id = payload.consultation_id or existing_rx.consultation_id
        existing_rx.doctor_id = payload.doctor_id or visit.doctor_id or existing_rx.doctor_id
        existing_rx.status = "finalized"
        existing_rx.items = [_prescription_item_from_data(item, medicines_data[i]) for i, item in enumerate(item_source or [])]
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
        prescription.items = [_prescription_item_from_data(item, medicines_data[i]) for i, item in enumerate(item_source or [])]
        session.add(prescription)

    # If doctor included lab tests, upsert a LabOrder alongside the prescription
    # Every test must reference an active Lab Test Master entry — the server
    # snapshots code/name/category/sample_type/unit/reference_range/price;
    # client-supplied values for those fields are never authoritative.
    if payload.lab_tests:
        from app.services.lab_order_service import reject_duplicate_test_ids, snapshot_lab_test

        reject_duplicate_test_ids([item.test_id for item in payload.lab_tests])
        snapshotted_tests = [
            await snapshot_lab_test(session, item.test_id, notes=item.notes)
            for item in payload.lab_tests
        ]
        existing_order = (await session.execute(
            select(LabOrder).where(LabOrder.visit_id == payload.visit_id).limit(1)
        )).scalar_one_or_none()
        if existing_order:
            existing_order.tests = snapshotted_tests
            existing_order.status = "ordered"
        else:
            lab_order = LabOrder(
                id=uuid.uuid4(),
                visit_id=payload.visit_id,
                uhid=uhid,
                tests=snapshotted_tests,
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
            normalized_items.append(await _normalize_medicine_item(session, item))
        rx.medicines = normalized_items
        rx.items = [_prescription_item_from_data(item, normalized_items[i]) for i, item in enumerate(item_source)]
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
