"""
Prescriptions API — build and retrieve prescriptions for a visit.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.prescription import PrescriptionCreate, PrescriptionRead, PrescriptionUpdate
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.services.audit_service import record_audit
from app.websocket.manager import ws_manager

router = APIRouter()


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
    medicines_data = [m.model_dump() for m in item_source] if item_source else None

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
                medicine=item.medicine,
                strength=item.strength,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                duration=item.duration,
                quantity=item.quantity,
                instructions=item.instructions,
            )
            for item in item_source or []
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
                medicine=item.medicine,
                strength=item.strength,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                duration=item.duration,
                quantity=item.quantity,
                instructions=item.instructions,
            )
            for item in item_source or []
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
        rx.medicines = [m.model_dump() for m in item_source]
        rx.items = [
            PrescriptionItem(
                id=uuid.uuid4(),
                medicine=item.medicine,
                strength=item.strength,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                duration=item.duration,
                quantity=item.quantity,
                instructions=item.instructions,
            )
            for item in item_source
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
