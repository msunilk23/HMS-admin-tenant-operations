"""
Queue tokens API — priority-based token allocation engine.

Priority ordering for token_no assignment:
  emergency > senior_citizen > normal

Token numbering is per-department per-day when department_id is provided,
falling back to per-queue_type per-day for legacy/undepartment tokens.
Daily sequence resets at midnight.
"""
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import ensure_feature_enabled, get_current_user, require_role, require_feature
from app.core.config import settings
from app.core.razorpay_service import create_razorpay_order
from app.db.engine import get_session
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.invoice import Invoice
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.queue import CancelTokenRequest, QueueTokenCreate, QueueTokenRead, QueueTokenStatusUpdate, QueueTokenUpdate
from app.schemas.queue_summary import QueueStageSummary, QueueSummaryRead
from app.services.audit_service import record_audit
from app.services.queue_sla import queue_stage_summary
from app.services.token_allocation import TokenAllocationConflict, allocate_and_create_token
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.websocket.manager import ws_manager

router = APIRouter(dependencies=[Depends(require_feature("opd_queue"))])

_PRIORITY_ORDER = {
    "emergency": 0,
    "urgent": 1,
    "pregnant": 2,
    "disabled": 3,
    "senior_citizen": 4,
    "normal": 5,
}


def _user_uuid(user_id: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id)) if user_id is not None else None
    except (TypeError, ValueError):
        return None


@router.post("", response_model=QueueTokenRead, status_code=status.HTTP_201_CREATED)
async def issue_token(
    payload: QueueTokenCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "hospital_admin")),
):
    patient = await session.get(Patient, payload.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    now = datetime.now(timezone.utc)

    def _build_token(token_no: int, token_scope: str, token_date) -> QueueToken:
        return QueueToken(
            id=uuid.uuid4(),
            patient_id=payload.patient_id,
            uhid=patient.uhid,
            appointment_id=payload.appointment_id,
            department_id=payload.department_id,
            doctor_id=payload.doctor_id,
            token_no=token_no,
            token_scope=token_scope,
            token_date=token_date,
            queue_type=payload.queue_type,
            priority=payload.priority,
            priority_reason=payload.priority_reason,
            priority_assigned_by=_user_uuid(current_user.get("sub")),
            priority_assigned_at=now,
            status="checked_in",
            called_at=now,
        )

    try:
        token = await allocate_and_create_token(
            session,
            _build_token,
            payload.queue_type,
            payload.department_id,
            current_user.get("timezone"),
        )
    except TokenAllocationConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not allocate a unique token number right now; please retry.",
        ) from exc

    if payload.priority != "normal" or payload.priority_reason:
        record_audit(
            session,
            current_user=current_user,
            action="CREATE",
            resource_type="queue_priority",
            resource_id=token.id,
            new_value={
                "priority": payload.priority,
                "reason": payload.priority_reason,
                "assigned_at": now,
            },
        )

    # --- Determine consultation fee and whether to request upfront payment ---
    doctor = await session.get(Doctor, payload.doctor_id) if payload.doctor_id else None
    consultation_fee = float(doctor.consultation_fee) if doctor and doctor.consultation_fee else 0.0
    needs_payment = consultation_fee > 0 and not payload.waive_fee

    # Canonical OPD lifecycle — not billing state.
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        uhid=patient.uhid,
        doctor_id=payload.doctor_id,
        appointment_id=payload.appointment_id,
        department_id=payload.department_id,
        status=VisitStatus.REGISTERED.value,
        arrived_at=now,
        registered_at=now,
    )
    session.add(visit)
    # Flush visit so its PK exists in the DB before invoice FK references it
    await session.flush()

    # Persist visit_id on the token so list queries can surface payment status
    token.visit_id = visit.id

    # Reception hands off to the nurse queue; must not skip ahead to doctor consultation.
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.WAITING_FOR_NURSE,
        current_user.get("sub"),
        VisitTransitionSource.RECEPTION,
    )

    # Auto-create Invoice with consultation fee line item
    invoice = None
    if needs_payment:
        invoice = Invoice(
            id=uuid.uuid4(),
            visit_id=visit.id,
            uhid=patient.uhid,
            line_items=[{"description": f"Consultation Fee — Dr. {doctor.full_name}", "amount": consultation_fee}],
            subtotal=consultation_fee,
            discount=0.0,
            tax=0.0,
            total=consultation_fee,
            status="draft",
            billing_started_at=now,
        )
        session.add(invoice)
    elif payload.waive_fee and consultation_fee > 0:
        # Follow-up within 7 days — create a ₹0 paid invoice for record-keeping
        invoice = Invoice(
            id=uuid.uuid4(),
            visit_id=visit.id,
            uhid=patient.uhid,
            line_items=[{
                "description": f"Follow-up Consultation — Dr. {doctor.full_name} (fee waived)",
                "amount": 0.0,
            }],
            subtotal=0.0,
            discount=consultation_fee,  # shows the waived amount as a discount
            tax=0.0,
            total=0.0,
            status="paid",
            payment_method="follow_up",
            paid_at=now,
            billing_started_at=now,
            billing_completed_at=now,
        )
        session.add(invoice)

    await session.commit()
    await session.refresh(token)

    dept = await session.get(Department, payload.department_id) if payload.department_id else None
    if not doctor:  # may have been fetched above already; re-fetch only if None
        doctor = await session.get(Doctor, payload.doctor_id) if payload.doctor_id else None

    tenant = current_user.get("tenant_schema", "public")

    # Create Razorpay order and push to POS screen (if payment needed)
    if invoice and needs_payment:
        await ensure_feature_enabled("razorpay", current_user, session)
        razorpay_order = create_razorpay_order(
            amount_rupees=consultation_fee,
            receipt=str(invoice.id)[:40],
            notes={
                "tenant_schema": tenant,
                "invoice_id": str(invoice.id),
                "uhid": patient.uhid,
            },
        )
        if razorpay_order:
            invoice.razorpay_order_id = razorpay_order["id"]
            await session.commit()

        await ws_manager.broadcast(tenant, "pos:payment", {
            "event": "payment_request",
            "razorpay_key_id": __import__("app.core.config", fromlist=["settings"]).settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": invoice.razorpay_order_id,
            "invoice_id": str(invoice.id),
            "amount": int(consultation_fee * 100),  # paise
            "amount_display": f"₹{consultation_fee:.0f}",
            "patient_name": f"{patient.first_name} {patient.last_name}",
            "uhid": patient.uhid,
            "description": f"Consultation Fee — Dr. {doctor.full_name}" if doctor else "Consultation Fee",
        })

    await ws_manager.broadcast(tenant, "queue:update", {
        "event": "token_issued",
        "queue_type": token.queue_type,
        "department_id": str(token.department_id) if token.department_id else None,
        "department_name": (await session.get(Department, token.department_id)).name if token.department_id else None,
        "doctor_name": doctor.full_name if doctor else None,
        "token_no": token.token_no,
        # Neutral priority flag only (no clinical reason) — the public display
        # must never render this as "Emergency"/clinical status, only as a
        # generic priority-handling indicator.
        "is_priority": token.priority != "normal",
        # No patient_name/patient_id/uhid/phone here — this channel is readable
        # by the unauthenticated public display board (see websocket/router.py).
        # Staff screens refresh full details from the authenticated REST API.
    })
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "visit_registered",
        "visit_id": str(visit.id),
        "patient_id": str(visit.patient_id),
        "department_id": str(visit.department_id) if visit.department_id else None,
    })

    result = QueueTokenRead.model_validate(token)
    result.patient_name = f"{patient.first_name} {patient.last_name}"
    result.patient_phone = patient.phone
    result.department_name = dept.name if dept else None
    result.doctor_name = doctor.full_name if doctor else None
    result.visit_id = visit.id
    return result


@router.get("", response_model=List[QueueTokenRead])
async def list_queue(
    queue_type: Optional[str] = Query(None),
    department_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "nurse", "doctor", "hospital_admin")),
):
    """Returns today's queue, sorted by priority then token_no."""
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    stmt = (
        select(QueueToken, Patient)
        .join(Patient, QueueToken.patient_id == Patient.id)
        .where(QueueToken.issued_at >= today_start)
    )
    if queue_type:
        stmt = stmt.where(QueueToken.queue_type == queue_type)
    if department_id:
        stmt = stmt.where(QueueToken.department_id == department_id)
    if status_filter:
        stmt = stmt.where(QueueToken.status == status_filter)

    # Sort: priority ASC (emergency=0), then token_no ASC
    stmt = stmt.order_by(
        case(
            (QueueToken.priority == "emergency", 0),
            (QueueToken.priority == "urgent", 1),
            (QueueToken.priority == "pregnant", 2),
            (QueueToken.priority == "disabled", 3),
            (QueueToken.priority == "senior_citizen", 4),
            else_=5,
        ),
        QueueToken.token_no,
    )

    rows = (await session.execute(stmt)).all()
    items = []
    for token, patient in rows:
        item = QueueTokenRead.model_validate(token)
        item.patient_name = f"{patient.first_name} {patient.last_name}"
        item.patient_phone = patient.phone
        if token.department_id:
            dept = await session.get(Department, token.department_id)
            item.department_name = dept.name if dept else None
        if token.doctor_id:
            doctor = await session.get(Doctor, token.doctor_id)
            item.doctor_name = doctor.full_name if doctor else None
        items.append(item)
    return items


@router.get("/summary", response_model=QueueSummaryRead)
async def queue_summary(
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "nurse", "doctor", "hospital_admin")),
):
    visits = (await session.execute(
        select(Visit).where(
            Visit.status.in_([
                VisitStatus.WAITING_FOR_NURSE.value,
                VisitStatus.WAITING_FOR_DOCTOR.value,
            ])
        )
    )).scalars().all()
    return QueueSummaryRead(
        as_of=datetime.now(timezone.utc).isoformat(),
        waiting_for_nurse=QueueStageSummary(**queue_stage_summary(
            [visit for visit in visits if visit.status == VisitStatus.WAITING_FOR_NURSE.value],
            queue_timestamp="nurse_queue_at",
            threshold_seconds=settings.QUEUE_SLA_NURSE_MINUTES * 60,
        )),
        waiting_for_doctor=QueueStageSummary(**queue_stage_summary(
            [visit for visit in visits if visit.status == VisitStatus.WAITING_FOR_DOCTOR.value],
            queue_timestamp="doctor_queue_at",
            threshold_seconds=settings.QUEUE_SLA_DOCTOR_MINUTES * 60,
        )),
    )


@router.patch("/{token_id}", response_model=QueueTokenRead)
async def edit_token(
    token_id: uuid.UUID,
    payload: QueueTokenUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "hospital_admin")),
):
    """Edit department, doctor, or priority on a checked_in token."""
    token = await session.get(QueueToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.status != "checked_in":
        raise HTTPException(status_code=400, detail="Only checked_in tokens can be edited")

    if payload.department_id is not None:
        token.department_id = payload.department_id
    if payload.doctor_id is not None:
        token.doctor_id = payload.doctor_id
    if payload.priority is not None:
        previous_priority = token.priority
        token.priority = payload.priority
        token.priority_reason = payload.priority_reason
        token.priority_assigned_by = _user_uuid(current_user.get("sub"))
        token.priority_assigned_at = datetime.now(timezone.utc)
        if previous_priority != payload.priority or payload.priority_reason:
            record_audit(
                session,
                current_user=current_user,
                action="UPDATE",
                resource_type="queue_priority",
                resource_id=token.id,
                patient_id=token.patient_id,
                old_value={"priority": previous_priority},
                new_value={"priority": payload.priority, "reason": payload.priority_reason},
            )

    await session.commit()
    await session.refresh(token)

    patient = await session.get(Patient, token.patient_id)
    dept = await session.get(Department, token.department_id) if token.department_id else None
    doctor = await session.get(Doctor, token.doctor_id) if token.doctor_id else None

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "queue:update", {
        "event": "token_updated",
        "token_id": str(token.id),
        "token_no": token.token_no,
        "status": token.status,
    })

    result = QueueTokenRead.model_validate(token)
    if patient:
        result.patient_name = f"{patient.first_name} {patient.last_name}"
        result.patient_phone = patient.phone
    result.department_name = dept.name if dept else None
    result.doctor_name = doctor.full_name if doctor else None
    return result


@router.post("/{token_id}/cancel", response_model=QueueTokenRead)
async def cancel_token(
    token_id: uuid.UUID,
    payload: CancelTokenRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "hospital_admin")),
):
    """Cancel a checked_in token. Notes are mandatory."""
    token = await session.get(QueueToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.status != "checked_in":
        raise HTTPException(status_code=400, detail="Only checked_in tokens can be cancelled")
    if not payload.notes or not payload.notes.strip():
        raise HTTPException(status_code=422, detail="Cancellation notes are required")

    now = datetime.now(timezone.utc)
    token.status = "cancelled"
    token.notes = payload.notes.strip()
    token.cancelled_at = now

    # Cancel the associated Visit only while it is still in the early OPD flow.
    _CANCELLABLE = (VisitStatus.REGISTERED.value, VisitStatus.WAITING_FOR_NURSE.value, VisitStatus.IN_PRE_VITAL.value)
    visit = None
    if token.visit_id:
        visit = await session.get(Visit, token.visit_id)
        if visit and visit.status not in _CANCELLABLE:
            visit = None
    if not visit:
        # Legacy fallback for tokens issued before visit_id linkage existed.
        visit_stmt = select(Visit).where(
            Visit.patient_id == token.patient_id,
            Visit.status.in_(_CANCELLABLE),
        )
        if token.appointment_id:
            visit_stmt = visit_stmt.where(Visit.appointment_id == token.appointment_id)
        elif token.department_id:
            visit_stmt = visit_stmt.where(Visit.department_id == token.department_id)
        visit_result = await session.execute(visit_stmt)
        visit = visit_result.scalars().first()
    if visit:
        try:
            visit = await VisitWorkflowService.transition(
                session,
                visit,
                VisitStatus.CANCELLED,
                current_user.get("sub"),
                VisitTransitionSource.CANCELLED,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"Cannot cancel visit: {str(exc)}") from exc

    await session.commit()
    await session.refresh(token)

    patient = await session.get(Patient, token.patient_id)
    dept = await session.get(Department, token.department_id) if token.department_id else None
    doctor = await session.get(Doctor, token.doctor_id) if token.doctor_id else None

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "queue:update", {
        "event": "token_cancelled",
        "token_id": str(token.id),
        "token_no": token.token_no,
    })

    result = QueueTokenRead.model_validate(token)
    if patient:
        result.patient_name = f"{patient.first_name} {patient.last_name}"
        result.patient_phone = patient.phone
    result.department_name = dept.name if dept else None
    result.doctor_name = doctor.full_name if doctor else None
    return result


@router.patch("/{token_id}/status", response_model=QueueTokenRead)
async def update_token_status(
    token_id: uuid.UUID,
    payload: QueueTokenStatusUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "nurse", "doctor", "hospital_admin")),
):
    """Internal status transitions used by nurse/doctor flows to mark completed."""
    token = await session.get(QueueToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    token.status = payload.status
    if payload.status == "completed":
        token.completed_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(token)

    patient = await session.get(Patient, token.patient_id)
    dept = await session.get(Department, token.department_id) if token.department_id else None
    doctor = await session.get(Doctor, token.doctor_id) if token.doctor_id else None

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "queue:update", {
        "event": "token_updated",
        "token_id": str(token.id),
        "token_no": token.token_no,
        "queue_type": token.queue_type,
        "status": token.status,
    })

    result = QueueTokenRead.model_validate(token)
    if patient:
        result.patient_name = f"{patient.first_name} {patient.last_name}"
        result.patient_phone = patient.phone
    result.department_name = dept.name if dept else None
    result.doctor_name = doctor.full_name if doctor else None
    return result
