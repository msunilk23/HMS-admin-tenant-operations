"""
Visits API — create and manage OPD visits (visit lifecycle state machine).
"""
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription
from app.models.tenant.nurse_department import NurseDepartment
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.visit import VisitCreate, VisitDispatch, VisitRead, VisitStatusUpdate
from app.schemas.tat import VisitTATRead
from app.services.tat import build_visit_tat
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.websocket.manager import ws_manager

router = APIRouter()

ALLOWED_ROLES = ("receptionist", "nurse", "doctor", "billing_officer", "hospital_admin")


async def _complete_queue_token(visit: Visit, session: AsyncSession) -> None:
    """Mark this visit's checked-in queue token as completed."""
    token = (await session.execute(
        select(QueueToken)
        .where(
            and_(
                QueueToken.visit_id == visit.id,
                QueueToken.status == "checked_in",
            )
        )
        .order_by(QueueToken.issued_at.desc())
        .limit(1)
    )).scalars().first()
    if not token:
        # Legacy fallback for tokens issued before visit_id linkage existed.
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        token = (await session.execute(
            select(QueueToken)
            .where(
                and_(
                    QueueToken.visit_id.is_(None),
                    QueueToken.patient_id == visit.patient_id,
                    QueueToken.status == "checked_in",
                    QueueToken.issued_at >= today_start,
                )
            )
            .order_by(QueueToken.issued_at.desc())
            .limit(1)
        )).scalars().first()
    if token:
        token.status = "completed"
        token.completed_at = datetime.now(timezone.utc)


@router.post("", response_model=VisitRead, status_code=status.HTTP_201_CREATED)
async def create_visit(
    payload: VisitCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    now = datetime.now(timezone.utc)
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        doctor_id=payload.doctor_id,
        appointment_id=payload.appointment_id,
        department_id=payload.department_id,
        status=VisitStatus.REGISTERED.value,
        arrived_at=now,
        registered_at=now,
    )
    session.add(visit)
    await session.commit()
    await session.refresh(visit)

    patient = await session.get(Patient, visit.patient_id)
    doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
    dept = await session.get(Department, visit.department_id) if visit.department_id else None

    result = VisitRead.model_validate(visit)
    result.patient_name = f"{patient.first_name} {patient.last_name}" if patient else None
    result.doctor_name = doctor.full_name if doctor else None
    result.department_name = dept.name if dept else None
    result.doctor_consultation_fee = float(doctor.consultation_fee) if doctor else None
    return result


@router.get("", response_model=List[VisitRead])
async def list_visits(
    patient_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    department_id: Optional[uuid.UUID] = Query(None),
    open_only: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    # Normalize so case/legacy-alias differences between frontend and backend
    # (e.g. "registered" vs "REGISTERED") never silently return an empty list.
    if status_filter:
        try:
            status_filter = VisitStatus.normalize(status_filter).value
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown visit status '{status_filter}'.")

    stmt = select(Visit)
    if patient_id:
        stmt = stmt.where(Visit.patient_id == patient_id)
    if status_filter:
        stmt = stmt.where(Visit.status == status_filter)
    if open_only:
        stmt = stmt.where(Visit.closed_at == None)  # noqa: E711

    # Nurses are restricted to only their assigned departments — enforced server-side
    if current_user.get("role") == "nurse":
        nurse_id = uuid.UUID(current_user["sub"])
        nd_rows = (await session.execute(
            select(NurseDepartment.department_id).where(NurseDepartment.user_id == nurse_id)
        )).scalars().all()
        assigned_dept_ids = list(nd_rows)
        if not assigned_dept_ids:
            return []  # Nurse has no departments assigned — show nothing
        # If caller also passed a specific department_id, honour it only if it's in the nurse's list
        if department_id:
            if department_id not in assigned_dept_ids:
                return []  # Requested dept not assigned to this nurse
            stmt = stmt.where(Visit.department_id == department_id)
        else:
            stmt = stmt.where(Visit.department_id.in_(assigned_dept_ids))
    # Doctors are restricted to their own patients and only the doctor-ready queue
    elif current_user.get("role") == "doctor":
        doctor_row = (await session.execute(
            select(Doctor).where(Doctor.user_id == uuid.UUID(current_user["sub"]))
        )).scalar_one_or_none()
        if not doctor_row:
            return []  # Doctor account not linked to a Doctor record
        stmt = stmt.where(Visit.doctor_id == doctor_row.id)
        if status_filter:
            stmt = stmt.where(Visit.status == status_filter)
        else:
            stmt = stmt.where(Visit.status == VisitStatus.WAITING_FOR_DOCTOR.value)
        if department_id:
            stmt = stmt.where(Visit.department_id == department_id)
    elif department_id:
        stmt = stmt.where(Visit.department_id == department_id)

    stmt = stmt.order_by(Visit.created_at.desc())

    rows = (await session.execute(stmt)).scalars().all()

    # Batch-fetch today's queue tokens to enrich visits with priority & token_no.
    # Keyed by visit_id first since a patient may have multiple same-day visits.
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    token_by_visit: dict[uuid.UUID, QueueToken] = {}
    token_by_patient: dict[uuid.UUID, QueueToken] = {}
    if rows:
        visit_ids = [v.id for v in rows]
        patient_ids = [v.patient_id for v in rows]
        token_rows = (await session.execute(
            select(QueueToken)
            .where(
                or_(
                    QueueToken.visit_id.in_(visit_ids),
                    and_(QueueToken.visit_id.is_(None), QueueToken.patient_id.in_(patient_ids), QueueToken.issued_at >= today_start),
                )
            )
            .order_by(QueueToken.issued_at.asc())   # earliest first → latest overwrites in dict
        )).scalars().all()
        for t in token_rows:
            if t.visit_id:
                token_by_visit[t.visit_id] = t
            else:
                token_by_patient[t.patient_id] = t

    # Batch-fetch lab order visit_ids so we can populate has_lab_order flag
    lab_visit_ids: set[uuid.UUID] = set()
    if rows:
        dispatch_visit_ids = [v.id for v in rows]
        lab_rows = (await session.execute(
            select(LabOrder.visit_id).where(LabOrder.visit_id.in_(dispatch_visit_ids))
        )).scalars().all()
        lab_visit_ids = set(lab_rows)

    items = []
    for v in rows:
        item = VisitRead.model_validate(v)
        patient = await session.get(Patient, v.patient_id)
        doctor = await session.get(Doctor, v.doctor_id) if v.doctor_id else None
        dept = await session.get(Department, v.department_id) if v.department_id else None
        item.patient_name = f"{patient.first_name} {patient.last_name}" if patient else None
        item.doctor_name = doctor.full_name if doctor else None
        item.department_name = dept.name if dept else None
        item.has_lab_order = v.id in lab_visit_ids
        item.doctor_consultation_fee = float(doctor.consultation_fee) if doctor else None
        qt = token_by_visit.get(v.id) or token_by_patient.get(v.patient_id)
        item.priority = qt.priority if qt else "normal"
        item.token_no = qt.token_no if qt else None
        items.append(item)

    # Sort by priority (emergency first), then token number ascending
    _PRIORITY_ORDER = {"emergency": 0, "senior_citizen": 1, "normal": 2}
    items.sort(key=lambda x: (_PRIORITY_ORDER.get(x.priority or "normal", 2), x.token_no or 999999))

    return items


@router.get("/{visit_id}", response_model=VisitRead)
async def get_visit(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    visit = await session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    patient = await session.get(Patient, visit.patient_id)
    doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
    dept = await session.get(Department, visit.department_id) if visit.department_id else None
    result = VisitRead.model_validate(visit)
    result.patient_name = f"{patient.first_name} {patient.last_name}" if patient else None
    result.doctor_name = doctor.full_name if doctor else None
    result.department_name = dept.name if dept else None
    result.doctor_consultation_fee = float(doctor.consultation_fee) if doctor else None
    return result


@router.get("/{visit_id}/tat", response_model=VisitTATRead)
async def get_visit_tat(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    """Return persisted operational timestamps and calculated TAT values."""
    visit = await session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    lab_order = (await session.execute(
        select(LabOrder).where(LabOrder.visit_id == visit_id).order_by(LabOrder.ordered_at.desc())
    )).scalars().first()
    invoice = (await session.execute(
        select(Invoice).where(Invoice.visit_id == visit_id).order_by(Invoice.created_at.desc())
    )).scalars().first()
    pharmacy_queue = None
    prescription = (await session.execute(
        select(Prescription).where(Prescription.visit_id == visit_id).order_by(Prescription.created_at.desc())
    )).scalars().first()
    if prescription:
        pharmacy_queue = (await session.execute(
            select(PharmacyQueue).where(PharmacyQueue.prescription_id == prescription.id)
        )).scalars().first()
    return build_visit_tat(
        visit,
        lab_order=lab_order,
        pharmacy_queue=pharmacy_queue,
        invoice=invoice,
    )


@router.patch("/{visit_id}/status", response_model=VisitRead)
async def transition_visit_status(
    visit_id: uuid.UUID,
    payload: VisitStatusUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*ALLOWED_ROLES)),
):
    visit = await session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    try:
        visit = await VisitWorkflowService.transition(
            session,
            visit,
            payload.status,
            current_user.get("sub"),
            VisitTransitionSource.RECEPTION,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if visit.status == VisitStatus.CLOSED.value:
        await _complete_queue_token(visit, session)

    await session.commit()
    await session.refresh(visit)

    tenant = current_user.get("tenant_schema", "public")
    if visit.status == VisitStatus.CLOSED.value:
        await ws_manager.broadcast(tenant, "queue:update", {"event": "token_completed", "patient_id": str(visit.patient_id)})
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "visit_status_changed",
        "visit_id": str(visit.id),
        "status": visit.status,
    })

    patient = await session.get(Patient, visit.patient_id)
    doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
    dept = await session.get(Department, visit.department_id) if visit.department_id else None
    result = VisitRead.model_validate(visit)
    result.patient_name = f"{patient.first_name} {patient.last_name}" if patient else None
    result.doctor_name = doctor.full_name if doctor else None
    result.department_name = dept.name if dept else None
    result.doctor_consultation_fee = float(doctor.consultation_fee) if doctor else None
    return result


@router.post("/{visit_id}/dispatch", response_model=VisitRead)
async def dispatch_visit(
    visit_id: uuid.UUID,
    payload: VisitDispatch,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("nurse", "hospital_admin", "super_admin")),
):
    """
    Nurse dispatch after prescription_done:
      - close    → visit → closed (hand prescription to patient, no extra billing)
      - billing  → visit → billing_pending (additional charges needed)
      - pharmacy → create PharmacyQueue + visit → dispatched_pharmacy
      - lab      → activate LabOrder + visit → dispatched_lab
    pharmacy and lab are independent — both can be dispatched for the same visit.
    """
    visit = await session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    _DISPATCH_ALLOWED = {VisitStatus.CONSULTATION_COMPLETED.value}
    if visit.status not in _DISPATCH_ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"Dispatch only allowed after consultation completion (current: {visit.status})",
        )

    if payload.action == "close":
        try:
            await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.CLOSED,
                current_user.get("sub"),
                VisitTransitionSource.DOCTOR,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await _complete_queue_token(visit, session)

    elif payload.action == "billing":
        pass

    elif payload.action == "pharmacy":
        rx = (await session.execute(
            select(Prescription).where(Prescription.visit_id == visit_id)
            .order_by(Prescription.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if not rx:
            raise HTTPException(status_code=400, detail="No prescription found for this visit")
        # Idempotent: only create if no PharmacyQueue exists yet
        existing_pq = (await session.execute(
            select(PharmacyQueue).where(PharmacyQueue.prescription_id == rx.id)
        )).scalar_one_or_none()
        if not existing_pq:
            patient = await session.get(Patient, visit.patient_id)
            session.add(PharmacyQueue(id=uuid.uuid4(), prescription_id=rx.id, uhid=patient.uhid if patient else None, status="pending"))
        # Pharmacy dispatch is tracked on its own queue; OPD visit remains in the consultation lifecycle.
        await _complete_queue_token(visit, session)

    elif payload.action == "lab":
        lab_order = (await session.execute(
            select(LabOrder).where(LabOrder.visit_id == visit_id)
        )).scalar_one_or_none()
        if not lab_order:
            raise HTTPException(status_code=400, detail="No lab order found for this visit — doctor must add lab tests first")
        # Reset to ordered so the lab technician starts fresh
        lab_order.status = "ordered"
        # Lab dispatch is tracked on its own lab order; OPD visit remains in the consultation lifecycle.
        await _complete_queue_token(visit, session)

    await session.commit()
    await session.refresh(visit)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "visit_dispatched",
        "visit_id": str(visit.id),
        "action": payload.action,
        "status": visit.status,
    })
    if payload.action == "close":
        await ws_manager.broadcast(tenant, "queue:update", {"event": "token_completed", "patient_id": str(visit.patient_id)})
    if payload.action in ("pharmacy", "lab"):
        await ws_manager.broadcast(tenant, "queue:update", {"event": "token_completed", "patient_id": str(visit.patient_id)})
    if payload.action == "pharmacy":
        await ws_manager.broadcast(tenant, "pharmacy:update", {
            "event": "pharmacy_queue_created",
            "visit_id": str(visit.id),
        })

    patient = await session.get(Patient, visit.patient_id)
    doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
    dept = await session.get(Department, visit.department_id) if visit.department_id else None
    result = VisitRead.model_validate(visit)
    result.patient_name = f"{patient.first_name} {patient.last_name}" if patient else None
    result.doctor_name = doctor.full_name if doctor else None
    result.department_name = dept.name if dept else None
    result.doctor_consultation_fee = float(doctor.consultation_fee) if doctor else None
    return result
