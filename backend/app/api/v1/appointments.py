"""
Appointments API — booking, slot availability, reschedule, cancel, check-in.

Check-in flow:
  appointment → confirmed/scheduled → creates Visit + QueueToken (consultation)
             → broadcasts queue:update → marks appointment checked_in
"""
import uuid
import asyncio
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role, require_feature
from app.db.engine import get_session
from app.models.tenant.appointment import Appointment
from app.models.tenant.doctor import Doctor
from app.models.tenant.doctor_schedule import DoctorSchedule
from app.models.tenant.doctor_schedule_exception import DoctorScheduleException
from app.models.tenant.invoice import Invoice
from app.models.tenant.patient import Patient
from app.models.tenant.queue_token import QueueToken
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentReschedule,
    AppointmentStatusUpdate,
    CheckInBody,
    CheckInResult,
    SlotInfo,
)
from app.core.razorpay_service import create_razorpay_order
from app.core.sms import send_appointment_confirmation
from app.models.public.user import Tenant
from app.services.token_allocation import TokenAllocationConflict, allocate_and_create_token
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.services.doctor_availability_service import available_slots, validate_slot
from app.websocket.manager import ws_manager

router = APIRouter(dependencies=[Depends(require_feature("appointments"))])

_VALID_CHECK_IN_STATUSES = {"scheduled", "confirmed"}
_IST = timezone(timedelta(hours=5, minutes=30))
_DAY_START_HOUR = 0
_DAY_END_HOUR = 23
_BOOKING_SLOT_LOCKS: dict[str, asyncio.Lock] = {}
_BOOKING_SLOT_LOCKS_GUARD = threading.Lock()


def _booking_slot_lock_key(doctor_id: uuid.UUID, slot_time: datetime) -> str:
    return f"{doctor_id}:{_normalize_utc(slot_time).isoformat()}"


async def _booking_slot_lock(doctor_id: uuid.UUID, slot_time: datetime) -> asyncio.Lock:
    key = _booking_slot_lock_key(doctor_id, slot_time)
    with _BOOKING_SLOT_LOCKS_GUARD:
        lock = _BOOKING_SLOT_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _BOOKING_SLOT_LOCKS[key] = lock
    return lock


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _resolve_active_schedule_rows(session: AsyncSession, doctor_id: uuid.UUID, target_date: date) -> List[DoctorSchedule]:
    weekday = target_date.weekday()
    stmt = select(DoctorSchedule).where(
        and_(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.is_active == True,
            DoctorSchedule.weekday == weekday,
            or_(
                DoctorSchedule.effective_from.is_(None),
                DoctorSchedule.effective_from <= target_date,
            ),
            or_(
                DoctorSchedule.effective_to.is_(None),
                DoctorSchedule.effective_to >= target_date,
            ),
        )
    ).order_by(DoctorSchedule.start_time)
    return (await session.execute(stmt)).scalars().all()


def _slot_generator(start_time: time, end_time: time, slot_minutes: int, target_date: date) -> List[datetime]:
    start_dt = datetime.combine(target_date, start_time, tzinfo=_IST)
    end_dt = datetime.combine(target_date, end_time, tzinfo=_IST)
    slots: List[datetime] = []
    while start_dt < end_dt:
        slots.append(start_dt.astimezone(timezone.utc))
        start_dt += timedelta(minutes=slot_minutes)
    return slots


async def _doctor_slot_times(session: AsyncSession, doctor_id: uuid.UUID, target_date: date) -> List[datetime]:
    schedules = await _resolve_active_schedule_rows(session, doctor_id, target_date)
    if not schedules:
        return []

    all_slots: List[datetime] = []
    for schedule in schedules:
        for slot in _slot_generator(schedule.start_time, schedule.end_time, schedule.slot_duration_minutes, target_date):
            all_slots.append(slot)

    if not all_slots:
        return []

    blocked_stmt = select(DoctorScheduleException).where(
        and_(
            DoctorScheduleException.doctor_id == doctor_id,
            DoctorScheduleException.is_active == True,
            DoctorScheduleException.start_datetime < datetime.combine(target_date, time(23, 59, 59), tzinfo=_IST).astimezone(timezone.utc),
            DoctorScheduleException.end_datetime > datetime.combine(target_date, time(0, 0, 0), tzinfo=_IST).astimezone(timezone.utc),
        )
    )
    blocked_ranges = (await session.execute(blocked_stmt)).scalars().all()
    if blocked_ranges:
        filtered: List[datetime] = []
        for slot in all_slots:
            slot_start = slot
            slot_end = slot + timedelta(minutes=min(s.slot_duration_minutes for s in schedules))
            if any(
                ex.start_datetime < slot_end and ex.end_datetime > slot_start
                for ex in blocked_ranges
            ):
                continue
            filtered.append(slot)
        all_slots = filtered

    return sorted(set(all_slots))


async def _enrich(appt: Appointment, session: AsyncSession) -> AppointmentRead:
    read = AppointmentRead.model_validate(appt)
    patient = await session.get(Patient, appt.patient_id)
    if patient:
        read.patient_name = f"{patient.first_name} {patient.last_name}"
        read.patient_uhid = patient.uhid
    doctor = await session.get(Doctor, appt.doctor_id)
    if doctor:
        read.doctor_name = doctor.full_name
    return read


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[AppointmentRead])
async def list_appointments(
    appt_date: Optional[date] = Query(None, alias="date"),
    doctor_id: Optional[uuid.UUID] = None,
    patient_id: Optional[uuid.UUID] = None,
    appt_status: Optional[str] = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(
        "receptionist", "nurse", "doctor", "hospital_admin",
    )),
):
    stmt = select(Appointment).order_by(Appointment.slot_time)
    if appt_date:
        day_start = datetime.combine(appt_date, time(_DAY_START_HOUR, 0), tzinfo=_IST).astimezone(timezone.utc)
        day_end = datetime.combine(appt_date, time(_DAY_END_HOUR, 0), tzinfo=_IST).astimezone(timezone.utc)
        stmt = stmt.where(and_(
            Appointment.slot_time >= day_start,
            Appointment.slot_time <= day_end,
        ))
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if patient_id:
        stmt = stmt.where(Appointment.patient_id == patient_id)
    if appt_status:
        stmt = stmt.where(Appointment.status == appt_status)
    rows = (await session.execute(stmt)).scalars().all()
    return [await _enrich(a, session) for a in rows]


# ── Slot availability ─────────────────────────────────────────────────────────

@router.get("/slots", response_model=List[SlotInfo])
async def get_slots(
    doctor_id: uuid.UUID,
    slot_date: date = Query(..., alias="date"),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(
        "receptionist", "hospital_admin",
    )),
):
    _, generated = await available_slots(session, doctor_id, slot_date, tenant_schema=_.get("tenant_schema"))
    return [SlotInfo.model_validate(slot.model_dump()) for slot in generated]


# ── Create / Book ─────────────────────────────────────────────────────────────

@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    payload: AppointmentCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(
        "receptionist", "hospital_admin",
    )),
):
    # Verify patient and doctor exist
    patient = await session.get(Patient, payload.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    doctor = await session.get(Doctor, payload.doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    normalized_slot_time = _normalize_utc(payload.slot_time)

    slot_lock = await _booking_slot_lock(payload.doctor_id, payload.slot_time)
    async with slot_lock:
        try:
            matching_slot, matching_schedule = await validate_slot(
                session, payload.doctor_id, payload.slot_time,
                tenant_schema=current_user.get("tenant_schema"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # Hold the schedule row in the same transaction as the capacity read and insert.
        # This prevents competing calls from both seeing the final seat as available.
        backend_name = session.bind.url.get_backend_name() if session.bind is not None else ""
        if backend_name == "sqlite" and not session.in_transaction():
            await session.execute(text("BEGIN IMMEDIATE"))
        elif backend_name != "sqlite":
            await session.execute(
                select(DoctorSchedule).where(DoctorSchedule.id == matching_schedule.id).with_for_update()
            )

        booked_count = (await session.execute(
            select(func.count(Appointment.id)).where(
                and_(
                    Appointment.doctor_id == payload.doctor_id,
                    Appointment.slot_time == normalized_slot_time,
                    Appointment.status.notin_(["cancelled", "no_show"]),
                )
            )
        )).scalar() or 0
        if booked_count >= matching_slot.capacity:
            raise HTTPException(status_code=409, detail="Slot capacity reached for this doctor")

        booked_by_user_id = None
        if current_user.get("sub") is not None:
            try:
                booked_by_user_id = uuid.UUID(str(current_user["sub"]))
            except (TypeError, ValueError):
                booked_by_user_id = None

        appt = Appointment(
            id=uuid.uuid4(),
            patient_id=payload.patient_id,
            uhid=patient.uhid,
            doctor_id=payload.doctor_id,
            department_id=doctor.department_id if doctor else None,
            slot_time=payload.slot_time,
            type=payload.type,
            notes=payload.notes,
            status="scheduled",
            booked_by_user_id=booked_by_user_id,
        )
        session.add(appt)
        await session.commit()
        await session.refresh(appt)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "appointment:update", {
        "event": "appointment_booked",
        "appointment_id": str(appt.id),
        "slot_time": appt.slot_time.isoformat(),
    })

    # ── WhatsApp confirmation ─────────────────────────────────────────────
    tenant_row = None
    try:
        tenant_row = (await session.execute(
            select(Tenant).where(Tenant.schema_name == tenant)
        )).scalar_one_or_none()
    except Exception:
        tenant_row = None
    hospital_name = tenant_row.hospital_name if tenant_row else tenant
    send_appointment_confirmation(
        to_phone=patient.phone,
        patient_name=f"{patient.first_name} {patient.last_name}",
        uhid=patient.uhid,
        slot_time_utc=appt.slot_time,
        doctor_name=doctor.full_name if doctor else None,
        appt_type=appt.type,
        hospital_name=hospital_name,
    )

    return await _enrich(appt, session)


# ── Single get ────────────────────────────────────────────────────────────────

@router.get("/{appt_id}", response_model=AppointmentRead)
async def get_appointment(
    appt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(
        "receptionist", "nurse", "doctor", "hospital_admin",
    )),
):
    appt = await session.get(Appointment, appt_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return await _enrich(appt, session)


# ── Reschedule ────────────────────────────────────────────────────────────────

@router.patch("/{appt_id}/reschedule", response_model=AppointmentRead)
async def reschedule_appointment(
    appt_id: uuid.UUID,
    payload: AppointmentReschedule,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(
        "receptionist", "hospital_admin",
    )),
):
    appt = await session.get(Appointment, appt_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status in ("cancelled", "completed", "checked_in"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reschedule appointment with status '{appt.status}'",
        )

    try:
        matching_slot, schedule = await validate_slot(
            session, appt.doctor_id, payload.slot_time,
            tenant_schema=current_user.get("tenant_schema"),
            exclude_appointment_id=appt.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.execute(select(DoctorSchedule).where(DoctorSchedule.id == schedule.id).with_for_update())
    booked_count = (await session.execute(select(func.count(Appointment.id)).where(
        Appointment.doctor_id == appt.doctor_id,
        Appointment.slot_time == _normalize_utc(payload.slot_time),
        Appointment.id != appt.id,
        Appointment.status.notin_(["cancelled", "no_show"]),
    ))).scalar() or 0
    if booked_count >= matching_slot.capacity:
        raise HTTPException(status_code=409, detail="New slot capacity reached for this doctor")

    appt.slot_time = _normalize_utc(payload.slot_time)
    if payload.notes is not None:
        appt.notes = payload.notes
    appt.status = "scheduled"

    await session.commit()
    await session.refresh(appt)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "appointment:update", {
        "event": "appointment_rescheduled",
        "appointment_id": str(appt.id),
        "new_slot_time": appt.slot_time.isoformat(),
    })

    return await _enrich(appt, session)


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.patch("/{appt_id}/cancel", response_model=AppointmentRead)
async def cancel_appointment(
    appt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(
        "receptionist", "hospital_admin",
    )),
):
    appt = await session.get(Appointment, appt_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status in ("cancelled", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel appointment with status '{appt.status}'",
        )
    appt.status = "cancelled"
    await session.commit()
    await session.refresh(appt)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "appointment:update", {
        "event": "appointment_cancelled",
        "appointment_id": str(appt.id),
    })

    return await _enrich(appt, session)


# ── Check-in (→ Visit + QueueToken) ──────────────────────────────────────────

@router.post("/{appt_id}/checkin", response_model=CheckInResult)
async def checkin_appointment(
    appt_id: uuid.UUID,
    body: CheckInBody = CheckInBody(),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(
        "receptionist", "hospital_admin",
    )),
):
    appt = await session.get(Appointment, appt_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status not in _VALID_CHECK_IN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Appointment status '{appt.status}' cannot be checked in (need scheduled/confirmed)",
        )

    # Check no duplicate open visit
    existing_visit = (await session.execute(
        select(Visit).where(
            and_(
                Visit.appointment_id == appt_id,
                Visit.status != VisitStatus.CLOSED.value,
            )
        )
    )).scalar_one_or_none()
    if existing_visit:
        # Already checked in — return existing token
        existing_token = (await session.execute(
            select(QueueToken).where(QueueToken.appointment_id == appt_id)
        )).scalar_one_or_none()
        if existing_token:
            return CheckInResult(
                appointment_id=appt_id,
                visit_id=existing_visit.id,
                token_id=existing_token.id,
                token_no=existing_token.token_no,
                queue_type=existing_token.queue_type,
            )
        raise HTTPException(status_code=409, detail="Visit already opened for this appointment")

    # Determine priority based on patient age / flags (simple: always normal for now)
    patient = await session.get(Patient, appt.patient_id)
    priority = "normal"
    if patient and patient.dob:
        from datetime import date as _date
        age = (_date.today() - patient.dob).days // 365
        if age >= 60:
            priority = "senior_citizen"

    # Derive department from doctor
    doctor = await session.get(Doctor, appt.doctor_id)
    department_id = doctor.department_id if doctor else None

    # Determine whether consultation fee applies
    consultation_fee = float(doctor.consultation_fee) if doctor and doctor.consultation_fee else 0.0
    needs_payment = consultation_fee > 0 and not body.waive_fee

    # Create Visit in the canonical OPD lifecycle; billing remains a separate downstream concern.
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=appt.patient_id,
        uhid=patient.uhid if patient else None,
        doctor_id=appt.doctor_id,
        appointment_id=appt_id,
        department_id=department_id,
        status=VisitStatus.REGISTERED.value,
    )
    session.add(visit)
    await session.flush()  # ensure visit.id exists before invoice FK

    # Reception hands off to the nurse queue; must not skip ahead to doctor consultation.
    await VisitWorkflowService.transition(
        session,
        visit,
        VisitStatus.WAITING_FOR_NURSE,
        current_user.get("sub"),
        VisitTransitionSource.RECEPTION,
    )

    # Create Invoice (draft) if fee applies, or ₹0 paid record if waived
    invoice = None
    now = datetime.now(timezone.utc)
    if needs_payment and doctor:
        invoice = Invoice(
            id=uuid.uuid4(),
            visit_id=visit.id,
            uhid=patient.uhid if patient else None,
            line_items=[{"description": f"Consultation Fee — Dr. {doctor.full_name}", "amount": consultation_fee}],
            subtotal=consultation_fee,
            discount=0.0,
            tax=0.0,
            total=consultation_fee,
            status="draft",
        )
        session.add(invoice)
    elif body.waive_fee and consultation_fee > 0 and doctor:
        invoice = Invoice(
            id=uuid.uuid4(),
            visit_id=visit.id,
            uhid=patient.uhid if patient else None,
            line_items=[{"description": f"Follow-up Consultation — Dr. {doctor.full_name} (fee waived)", "amount": 0.0}],
            subtotal=0.0,
            discount=consultation_fee,
            tax=0.0,
            total=0.0,
            status="paid",
            payment_method="follow_up",
            paid_at=now,
        )
        session.add(invoice)

    # Create QueueToken — numbered per department when available, via the
    # shared concurrency-safe allocation service (same one used by walk-ins).
    def _build_token(token_no: int, token_scope: str, token_date) -> QueueToken:
        return QueueToken(
            id=uuid.uuid4(),
            patient_id=appt.patient_id,
            uhid=patient.uhid if patient else None,
            appointment_id=appt_id,
            visit_id=visit.id,
            department_id=department_id,
            doctor_id=appt.doctor_id,
            token_no=token_no,
            token_scope=token_scope,
            token_date=token_date,
            queue_type="consultation",
            priority=priority,
            status="checked_in",
            issued_at=now,
        )

    try:
        token = await allocate_and_create_token(
            session,
            _build_token,
            "consultation",
            department_id,
            current_user.get("timezone"),
        )
    except TokenAllocationConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not allocate a unique token number right now; please retry.",
        ) from exc
    token_no = token.token_no

    # Mark appointment checked_in
    appt.status = "checked_in"

    await session.commit()
    await session.refresh(visit)
    await session.refresh(token)

    tenant = current_user.get("tenant_schema", "public")

    # Razorpay order + POS broadcast if payment needed
    if invoice and needs_payment and doctor:
        razorpay_order = create_razorpay_order(
            amount_rupees=consultation_fee,
            receipt=str(invoice.id)[:40],
            notes={
                "tenant_schema": tenant,
                "invoice_id": str(invoice.id),
                "uhid": patient.uhid if patient else "",
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
            "amount": int(consultation_fee * 100),
            "amount_display": f"₹{consultation_fee:.0f}",
            "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "",
            "uhid": patient.uhid if patient else "",
            "description": f"Consultation Fee — Dr. {doctor.full_name}",
        })

    # Broadcast real-time updates
    await ws_manager.broadcast(tenant, "queue:update", {
        "event": "token_issued",
        "token_id": str(token.id),
        "token_no": token_no,
        "queue_type": "consultation",
        "department_id": str(department_id) if department_id else None,
        "priority": priority,
        "appointment_id": str(appt_id),
    })
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "visit_registered",
        "visit_id": str(visit.id),
        "appointment_id": str(appt_id),
        "patient_id": str(visit.patient_id),
        "doctor_id": str(visit.doctor_id),
        "department_id": str(department_id) if department_id else None,
    })

    return CheckInResult(
        appointment_id=appt_id,
        visit_id=visit.id,
        token_id=token.id,
        token_no=token_no,
        queue_type="consultation",
        needs_payment=needs_payment,
        invoice_id=invoice.id if invoice else None,
    )
