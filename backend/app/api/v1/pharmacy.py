"""
Pharmacy Queue API — dispense prescribed medicines to patients.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import ensure_feature_enabled, require_role, require_feature
from app.core.pdf_service import generate_and_upload_prescription_pdf
from app.core.razorpay_service import create_razorpay_order
from app.core.sms import send_prescription_whatsapp
from app.db.engine import get_session
from app.models.tenant.consultation import Consultation
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.invoice import Invoice
from app.models.tenant.lab_order import LabOrder
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.prescription import Prescription
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.invoice import InvoiceRead, PharmacyBillCreate
from app.schemas.pharmacy import PharmacyQueueRead, PharmacyStatusUpdate
from app.services.visit_workflow import VisitTransitionSource, VisitWorkflowService
from app.websocket.manager import ws_manager
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_feature("pharmacy"))])


@router.get("", response_model=List[PharmacyQueueRead])
async def list_pharmacy_queue(
    status_filter: Optional[str] = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("pharmacist", "nurse", "receptionist", "hospital_admin")),
):
    """Returns pharmacy queue items, optionally filtered by status."""
    stmt = select(PharmacyQueue).order_by(PharmacyQueue.updated_at.asc())
    if status_filter:
        stmt = stmt.where(PharmacyQueue.status == status_filter)
    rows = (await session.execute(stmt)).scalars().all()

    items = []
    for pq in rows:
        item = PharmacyQueueRead.model_validate(pq)
        rx = await session.get(Prescription, pq.prescription_id)
        if rx:
            item.visit_id = rx.visit_id
            item.medicines = rx.medicines
            visit = await session.get(Visit, rx.visit_id)
            if visit:
                item.patient_id = visit.patient_id
                patient = await session.get(Patient, visit.patient_id)
                if patient:
                    item.patient_name = f"{patient.first_name} {patient.last_name}"
        items.append(item)
    return items


@router.patch("/{pq_id}/status", response_model=PharmacyQueueRead)
async def update_pharmacy_status(
    pq_id: uuid.UUID,
    payload: PharmacyStatusUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist", "nurse", "receptionist", "hospital_admin")),
):
    pq = await session.get(PharmacyQueue, pq_id)
    if not pq:
        raise HTTPException(status_code=404, detail="Pharmacy queue item not found")

    allowed_statuses = {"pending", "called", "dispensing", "dispensed", "partially_dispensed", "out_of_stock", "cancelled"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Unsupported pharmacy status: {payload.status}")

    old_status = pq.status
    now = datetime.now(timezone.utc)
    pq.status = payload.status
    if payload.status == "called":
        pq.called_at = pq.called_at or now
    elif payload.status == "dispensing":
        pq.dispensing_started_at = pq.dispensing_started_at or now
    elif payload.status == "dispensed":
        pq.dispensed_at = pq.dispensed_at or now
    if payload.notes is not None:
        pq.notes = payload.notes

    rx = await session.get(Prescription, pq.prescription_id)
    visit = await session.get(Visit, rx.visit_id) if rx else None
    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="pharmacy_dispense",
        resource_id=pq.id,
        patient_id=visit.patient_id if visit else None,
        visit_id=rx.visit_id if rx else None,
        old_value={"status": old_status},
        new_value={"status": pq.status, "notes": pq.notes},
    )

    await session.commit()
    await session.refresh(pq)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "pharmacy:update", {
        "event": "pharmacy_status_updated",
        "pq_id": str(pq.id),
        "status": pq.status,
    })

    item = PharmacyQueueRead.model_validate(pq)
    rx = await session.get(Prescription, pq.prescription_id)
    if rx:
        item.visit_id = rx.visit_id
        item.medicines = rx.medicines
        visit = await session.get(Visit, rx.visit_id)
        if visit:
            item.patient_id = visit.patient_id
            patient = await session.get(Patient, visit.patient_id)
            if patient:
                item.patient_name = f"{patient.first_name} {patient.last_name}"
    return item


# ── Background task ───────────────────────────────────────────────────────────

def _send_prescription_pdf_task(
    *,
    hospital_name: str,
    patient_name: str,
    uhid: str,
    gender: str,
    age: Optional[int],
    dob: Optional[str],
    phone: str,
    visit_date: str,
    department_name: Optional[str],
    doctor_name: Optional[str],
    doctor_specialization: Optional[str],
    chief_complaint: Optional[str],
    diagnosis: Optional[list],
    notes: Optional[str],
    medicines: Optional[list],
    lab_tests: Optional[list],
    follow_up_date: Optional[str],
) -> None:
    """Synchronous background task: generate PDF, upload, send WhatsApp."""
    try:
        pdf_url = generate_and_upload_prescription_pdf(
            hospital_name=hospital_name,
            patient_name=patient_name,
            uhid=uhid,
            gender=gender,
            age=age,
            dob=dob,
            phone=phone,
            visit_date=visit_date,
            department_name=department_name,
            doctor_name=doctor_name,
            doctor_specialization=doctor_specialization,
            chief_complaint=chief_complaint,
            diagnosis=diagnosis,
            notes=notes,
            medicines=medicines,
            lab_tests=lab_tests,
            follow_up_date=follow_up_date,
        )
        send_prescription_whatsapp(
            to_phone=phone,
            patient_name=patient_name,
            uhid=uhid,
            hospital_name=hospital_name,
            doctor_name=doctor_name,
            pdf_url=pdf_url,
        )
    except Exception:
        logger.exception("Failed to send prescription PDF WhatsApp for UHID=%s", uhid)


# ── Bill endpoint ─────────────────────────────────────────────────────────────

@router.post("/{pq_id}/bill", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def bill_pharmacy_dispense(
    pq_id: uuid.UUID,
    payload: PharmacyBillCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist", "hospital_admin")),
):
    """
    Create an invoice for pharmacy dispense and optionally trigger Razorpay order.
    - payment_method=cash   → marks invoice paid immediately, advances queue to dispensed,
                              sends prescription PDF via WhatsApp to patient
    - payment_method=online → creates Razorpay order, returns razorpay_order_id for frontend checkout
    """
    logger.info(
        "Pharmacy bill: Start - pq_id=%s, payment_method=%s, discount=%.2f",
        pq_id, payload.payment_method, payload.discount,
    )
    
    pq = await session.get(PharmacyQueue, pq_id)
    if not pq:
        raise HTTPException(status_code=404, detail="Pharmacy queue item not found")
    allowed_billable_statuses = {"pending", "called", "dispensing"}
    if pq.status not in allowed_billable_statuses:
        raise HTTPException(status_code=400, detail=f"Queue item is not billable in status {pq.status}")

    rx = await session.get(Prescription, pq.prescription_id)
    if not rx:
        raise HTTPException(status_code=404, detail="Prescription not found")
    visit = await session.get(Visit, rx.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    patient = await session.get(Patient, visit.patient_id) if visit else None

    # Fetch supplementary data for PDF/WhatsApp (best-effort)
    consultation = (await session.execute(
        select(Consultation).where(Consultation.visit_id == rx.visit_id)
    )).scalar_one_or_none()

    doctor: Optional[Doctor] = None
    if visit.doctor_id:
        doctor = await session.get(Doctor, visit.doctor_id)

    department: Optional[Department] = None
    if visit.department_id:
        department = await session.get(Department, visit.department_id)

    # Fetch tenant info for hospital name
    from sqlalchemy import text as sql_text
    hospital_name_row = await session.execute(
        sql_text("SELECT hospital_name FROM public.tenants WHERE schema_name = current_schema() LIMIT 1")
    )
    hospital_name = (hospital_name_row.scalar() or "Hospital")

    # Compute totals from pharmacy line items
    li_dicts = [line_item.model_dump() for line_item in payload.line_items]
    subtotal = sum(li["total"] for li in li_dicts)
    gst_total = sum(
        li["qty"] * li["mrp"] * (li["gst_pct"] / 100) * (1 - li["dis_pct"] / 100)
        for li in li_dicts
    )
    total = max(subtotal - payload.discount, 0.0)

    invoice = Invoice(
        id=uuid.uuid4(),
        visit_id=rx.visit_id,
        uhid=patient.uhid if patient else None,
        line_items=li_dicts,
        subtotal=subtotal,
        discount=payload.discount,
        tax=round(gst_total, 2),
        total=total,
        source="pharmacy",
        pharmacy_queue_id=pq_id,
        status="draft",
        billing_started_at=datetime.now(timezone.utc),
    )
    session.add(invoice)

    tenant = current_user.get("tenant_schema", "public")
    
    logger.info(
        "Pharmacy bill: Created invoice %s - payment_method=%s, total=%.2f, tenant=%s",
        invoice.id, payload.payment_method, total, tenant,
    )

    if payload.payment_method == "cash":
        logger.info("Pharmacy bill: Processing CASH payment for invoice %s", invoice.id)
        
        invoice.payment_method = "cash"
        invoice.status = "paid"
        invoice.paid_at = datetime.now(timezone.utc)
        invoice.billing_completed_at = invoice.paid_at
        
        logger.info(
            "Pharmacy bill: Set invoice to paid - status=%s, payment_method=%s, paid_at=%s",
            invoice.status, invoice.payment_method, invoice.paid_at,
        )
        # advance queue to dispensed
        pq.status = "dispensed"
        await session.commit()
        await session.refresh(invoice)
        await ws_manager.broadcast(tenant, "pharmacy:update", {
            "event": "pharmacy_status_updated",
            "pq_id": str(pq_id),
            "status": "dispensed",
        })

        # Schedule WhatsApp prescription PDF (non-blocking)
        if patient and patient.phone:
            dob_str = patient.dob.isoformat() if patient.dob else None
            follow_up_str = consultation.follow_up_date.isoformat() if consultation and consultation.follow_up_date else None
            visit_date_str = visit.created_at.strftime("%d %b %Y") if hasattr(visit, "created_at") and visit.created_at else datetime.now(timezone.utc).strftime("%d %b %Y")
            # Fetch lab orders for this visit (best-effort)
            lab_order = (await session.execute(
                select(LabOrder).where(LabOrder.visit_id == rx.visit_id)
            )).scalar_one_or_none()
            # LabOrder.tests keys are {test, notes}; PDF helper expects {test_name, notes}
            lab_tests_for_pdf = None
            if lab_order and lab_order.tests:
                lab_tests_for_pdf = [
                    {"test_name": t.get("test", t.get("test_name", "")), "notes": t.get("notes")}
                    for t in lab_order.tests
                ]
            background_tasks.add_task(
                _send_prescription_pdf_task,
                hospital_name=hospital_name,
                patient_name=f"{patient.first_name} {patient.last_name}",
                uhid=patient.uhid,
                gender=patient.gender,
                age=patient.age,
                dob=dob_str,
                phone=patient.phone,
                visit_date=visit_date_str,
                department_name=department.name if department else None,
                doctor_name=doctor.full_name if doctor else None,
                doctor_specialization=doctor.specialization if doctor else None,
                chief_complaint=consultation.chief_complaint if consultation else None,
                diagnosis=consultation.diagnosis_icd10 if consultation else None,
                notes=consultation.notes if consultation else None,
                medicines=rx.medicines,
                lab_tests=lab_tests_for_pdf,
                follow_up_date=follow_up_str,
            )
    else:
        # online — create Razorpay order and broadcast payment request to POS kiosk
        await ensure_feature_enabled("razorpay", current_user, session)
        logger.info("Pharmacy bill: Processing ONLINE payment for invoice %s", invoice.id)
        
        await session.commit()
        await session.refresh(invoice)
        logger.info("Pharmacy bill: Committed invoice to DB, now creating Razorpay order")
        
        rz_order = create_razorpay_order(
            amount_rupees=total,
            receipt=str(invoice.id)[:40],
            notes={"tenant_schema": tenant, "source": "pharmacy"},
        )
        logger.info("Pharmacy bill: Razorpay order created: %s", rz_order)
        
        if rz_order:
            invoice.razorpay_order_id = rz_order["id"]
            logger.info("Pharmacy bill: Set razorpay_order_id=%s on invoice", rz_order["id"])
            
            await session.commit()
            logger.info("Pharmacy bill: Committed razorpay_order_id to DB")
            
            await session.refresh(invoice)
            logger.info(
                "Pharmacy bill: Refreshed invoice - razorpay_order_id=%s, status=%s",
                invoice.razorpay_order_id, invoice.status,
            )

            # Validate Razorpay is configured before broadcasting
            if not settings.RAZORPAY_KEY_ID:
                logger.error("❌ Razorpay online payment requested but RAZORPAY_KEY_ID not configured in environment!")
                raise HTTPException(
                    status_code=500, 
                    detail="Razorpay payment gateway is not configured. Contact administrator."
                )

            # Broadcast payment request to POS screen (kiosk)
            broadcast_payload = {
                "event": "payment_request",
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                "razorpay_order_id": rz_order["id"],
                "invoice_id": str(invoice.id),
                "amount": int(float(total) * 100),  # paise
                "amount_display": f"₹{float(total):.0f}",
                "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Patient",
                "uhid": patient.uhid if patient else "",
                "description": f"Pharmacy Dispense — {patient.first_name} {patient.last_name}" if patient else "Patient",
            }
            
            # Log exactly what's being broadcast
            logger.info(
                "Pharmacy bill: Broadcasting payload - %s",
                json.dumps({
                    "event": broadcast_payload.get("event"),
                    "razorpay_key_id": broadcast_payload.get("razorpay_key_id"),
                    "razorpay_order_id": broadcast_payload.get("razorpay_order_id"),
                    "invoice_id": broadcast_payload.get("invoice_id"),
                    "tenant": tenant,
                })
            )
            
            await ws_manager.broadcast(tenant, "pos:payment", broadcast_payload)
            logger.info("Pharmacy bill: Broadcasted payment_request to POS")
        else:
            logger.error("Pharmacy bill: Failed to create Razorpay order for invoice %s", invoice.id)

    logger.info(
        "Pharmacy bill: Returning invoice %s - status=%s, razorpay_order_id=%s, payment_method=%s",
        invoice.id, invoice.status, invoice.razorpay_order_id, invoice.payment_method,
    )
    return invoice

@router.patch("/{pq_id}/verify-payment", response_model=dict)
async def verify_pharmacy_payment(
    pq_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("pharmacist", "hospital_admin")),
):
    """
    Verify if Razorpay payment was captured for a pharmacy dispense.
    Used as fallback when webhook misses or modal needs to confirm payment status.
    
    Returns:
    - {success: true, status: "dispensed"} if payment captured and queue advanced
    - {success: false, status: "pending", reason: "..."} if payment not yet captured
    """
    pq = await session.get(PharmacyQueue, pq_id)
    if not pq:
        raise HTTPException(status_code=404, detail="Pharmacy queue item not found")

    # Find the invoice for this pharmacy queue
    invoice = (await session.execute(
        select(Invoice).where(Invoice.pharmacy_queue_id == pq_id)
    )).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found for this pharmacy order")

    # If already dispensed, no need to verify
    if pq.status == "dispensed":
        return {"success": True, "status": "dispensed"}

    # If invoice already paid, just advance the queue (shouldn't happen but check)
    if invoice.status == "paid":
        if pq.status != "dispensed":
            pq.status = "dispensed"
            await session.commit()
        return {"success": True, "status": "dispensed"}

    # Check if Razorpay order exists and has payment
    if not invoice.razorpay_order_id:
        return {"success": False, "status": "pending", "reason": "No Razorpay order created"}

    payment = fetch_order_payments(invoice.razorpay_order_id)
    if not payment:
        return {"success": False, "status": "pending", "reason": "No captured payment found on Razorpay"}

    # Payment captured! Mark invoice and queue as paid/dispensed
    invoice.razorpay_payment_id = payment.get("id")
    invoice.payment_method = payment.get("method", "razorpay")
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    pq.status = "dispensed"

    # Pharmacy queue is treated as a domain-specific workflow, not a visit-state mutation.
    rx = await session.get(Prescription, pq.prescription_id)

    await session.commit()
    await session.refresh(invoice)
    await session.refresh(pq)

    # Send prescription PDF in background (same as cash flow)
    if rx:
        visit = await session.get(Visit, rx.visit_id)
        patient = await session.get(Patient, visit.patient_id) if visit else None

        if patient and patient.phone:
            consultation = (await session.execute(
                select(Consultation).where(Consultation.visit_id == rx.visit_id)
            )).scalar_one_or_none()
            doctor = await session.get(Doctor, visit.doctor_id) if visit.doctor_id else None
            department = await session.get(Department, visit.department_id) if visit.department_id else None

            hospital_name_row = await session.execute(
                sql_text("SELECT hospital_name FROM public.tenants WHERE schema_name = current_schema() LIMIT 1")
            )
            hospital_name = (hospital_name_row.scalar() or "Hospital")

            dob_str = patient.dob.isoformat() if patient.dob else None
            follow_up_str = consultation.follow_up_date.isoformat() if consultation and consultation.follow_up_date else None
            visit_date_str = visit.created_at.strftime("%d %b %Y") if hasattr(visit, "created_at") and visit.created_at else datetime.now(timezone.utc).strftime("%d %b %Y")

            lab_order = (await session.execute(
                select(LabOrder).where(LabOrder.visit_id == rx.visit_id)
            )).scalar_one_or_none()
            lab_tests_for_pdf = None
            if lab_order and lab_order.tests:
                lab_tests_for_pdf = [
                    {"test_name": t.get("test", t.get("test_name", "")), "notes": t.get("notes")}
                    for t in lab_order.tests
                ]

            # Note: BackgroundTasks not available in this context, so run inline
            try:
                pdf_url = generate_and_upload_prescription_pdf(
                    hospital_name=hospital_name,
                    patient_name=f"{patient.first_name} {patient.last_name}",
                    uhid=patient.uhid,
                    gender=patient.gender,
                    age=patient.age,
                    dob=dob_str,
                    phone=patient.phone,
                    visit_date=visit_date_str,
                    department_name=department.name if department else None,
                    doctor_name=doctor.full_name if doctor else None,
                    doctor_specialization=doctor.specialization if doctor else None,
                    chief_complaint=consultation.chief_complaint if consultation else None,
                    diagnosis=consultation.diagnosis_icd10 if consultation else None,
                    notes=consultation.notes if consultation else None,
                    medicines=rx.medicines,
                    lab_tests=lab_tests_for_pdf,
                    follow_up_date=follow_up_str,
                )
                send_prescription_whatsapp(
                    to_phone=patient.phone,
                    patient_name=f"{patient.first_name} {patient.last_name}",
                    uhid=patient.uhid,
                    hospital_name=hospital_name,
                    doctor_name=doctor.full_name if doctor else None,
                    pdf_url=pdf_url,
                )
            except Exception:
                logger.exception("Failed to send prescription PDF WhatsApp for UHID=%s after payment verify", patient.uhid)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "pharmacy:update", {
        "event": "pharmacy_status_updated",
        "pq_id": str(pq_id),
        "status": "dispensed",
    })

    return {"success": True, "status": "dispensed"}