"""
Billing API — invoice creation, line-item management, and payment processing.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission, require_role, require_feature
from app.core.config import settings
from app.core.invoice_pdf_service import (
    build_invoice_pdf,
    canonical_invoice_snapshot,
)
from app.core.razorpay_service import create_razorpay_order, fetch_order_payments, verify_webhook_signature
from app.db.engine import AsyncSessionLocal, get_session, tenant_schema_var
from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
from app.models.tenant.invoice import Invoice, Payment, Refund, invoice_status_for_payment
from app.models.public.user import Tenant
from app.models.tenant.patient import Patient
from app.models.tenant.pharmacy_queue import PharmacyQueue
from app.models.tenant.pharmacy_dispense import PharmacyDispense
from app.models.tenant.visit import Visit
from app.schemas.document import DocumentVersionRead
from app.schemas.invoice import InvoiceCreate, InvoicePayment, InvoiceRead, PaymentRead, RefundCreate
from app.services.document_service import (
    DocumentFinalizationError,
    DocumentIntegrityError,
    finalize_document,
    get_version as get_document_version,
    list_versions as list_document_versions,
    read_document_bytes,
)
from app.services.document_storage import LocalFileDocumentStorage
from app.services.audit_service import record_audit
from app.services.pharmacy_dispensing import confirm_dispense_stock_consumption, release_dispense_reservations
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

_invoice_document_storage = LocalFileDocumentStorage()


def _extract_razorpay_context(event_data: dict) -> dict:
    """Return the normalized Razorpay order/payment metadata for webhook handling."""
    payment_entity = event_data.get("payload", {}).get("payment", {}).get("entity", {})
    order_entity = event_data.get("payload", {}).get("order", {}).get("entity", {})
    order_notes = order_entity.get("notes") or {}
    payment_notes = payment_entity.get("notes") or {}
    order_tenant = order_notes.get("tenant_schema")
    payment_tenant = payment_notes.get("tenant_schema")
    tenant_schema = (order_tenant or payment_tenant or "")

    return {
        "order_id": payment_entity.get("order_id") or order_entity.get("id"),
        "payment_id": payment_entity.get("id"),
        "payment_method": payment_entity.get("method"),
        "tenant_schema": tenant_schema,
        "order_notes": order_notes,
        "payment_notes": payment_notes,
        "tenant_conflict": bool(order_tenant and payment_tenant and order_tenant != payment_tenant),
    }


# Protected router — requires billing feature enabled in tenant's plan
router = APIRouter(dependencies=[Depends(require_feature("billing"))])

# Public router — Razorpay webhook must be reachable without JWT
# (Razorpay's servers call this directly; auth is via HMAC signature)
webhook_router = APIRouter()


async def _require_pharmacy_permission(session: AsyncSession, current_user: dict, permission: str) -> None:
    from app.models.public.permission import Permission, RolePermission

    allowed = await session.scalar(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id).where(
        RolePermission.role == current_user.get("role"), Permission.code == permission, Permission.is_active == True,  # noqa: E712
    ))
    if allowed is None:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


@router.get("/public-config")
async def public_billing_config(
    _: dict = Depends(require_role("pharmacist", "receptionist", "billing_officer", "nurse", "hospital_admin")),
):
    """Returns public Razorpay key ID so the frontend can open checkout."""
    return {"razorpay_key_id": settings.RAZORPAY_KEY_ID}


@router.get("", response_model=List[InvoiceRead])
async def list_invoices(
    visit_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "hospital_admin")),
):
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if visit_id:
        stmt = stmt.where(Invoice.visit_id == visit_id)
    rows = (await session.execute(stmt)).scalars().all()
    return rows


def _compute_totals(line_items: list | None, discount: float, tax: float) -> float:
    if discount < 0 or tax < 0:
        raise HTTPException(status_code=400, detail="Discount and tax cannot be negative")
    subtotal = sum(item.get("amount", 0) for item in (line_items or []))
    if discount > subtotal:
        raise HTTPException(status_code=400, detail="Discount cannot exceed subtotal")
    total = subtotal - discount + tax
    return subtotal, max(total, 0.0)


def _invoice_to_snapshot(invoice: Invoice, visit: Visit | None, patient: Patient | None) -> dict:
    return canonical_invoice_snapshot(
        {
            "id": invoice.id,
            "visit_id": invoice.visit_id,
            "uhid": invoice.uhid,
            "line_items": invoice.line_items,
            "subtotal": invoice.subtotal,
            "discount": invoice.discount,
            "tax": invoice.tax,
            "total": invoice.total,
            "paid_amount": invoice.paid_amount,
            "status": invoice.status,
            "payment_method": invoice.payment_method,
            "receipt_number": invoice.receipt_number,
            "source": invoice.source,
            "pharmacy_queue_id": invoice.pharmacy_queue_id,
            "pharmacy_dispense_id": invoice.pharmacy_dispense_id,
            "created_at": invoice.created_at,
            "paid_at": invoice.paid_at,
            "patient_id": patient.id if patient else None,
            "patient_name": f"{patient.first_name} {patient.last_name}" if patient else None,
            "patient_phone": patient.phone if patient else None,
            "doctor_id": visit.doctor_id if visit else None,
            "department_id": visit.department_id if visit else None,
        }
    )


async def _record_payment(
    invoice: Invoice,
    payload: InvoicePayment,
    session: AsyncSession,
    current_user: dict | None = None,
) -> Payment:
    if invoice.status in ("cancelled", "refunded", "paid"):
        raise HTTPException(status_code=400, detail=f"Invoice already {invoice.status}")
    amount = payload.amount if payload.amount is not None else invoice.balance
    if amount <= 0 or amount > invoice.balance:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero and no more than the balance")
    payment = Payment(
        id=uuid.uuid4(), invoice_id=invoice.id, amount=amount,
        payment_method=payload.payment_method, transaction_reference=payload.transaction_reference,
        gateway="razorpay" if payload.payment_method == "razorpay" else None,
        paid_at=datetime.now(timezone.utc),
    )
    if invoice.source == "pharmacy_dispense":
        record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_INITIATED", resource_type="invoice", resource_id=invoice.id, visit_id=invoice.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(invoice.pharmacy_dispense_id), "payment_method": payload.payment_method, "amount": amount})
    visit = await session.get(Visit, invoice.visit_id)
    session.add(payment)
    invoice.paid_amount = float(invoice.paid_amount) + amount
    invoice.payment_method = payload.payment_method
    invoice.status = invoice_status_for_payment(float(invoice.total), float(invoice.paid_amount))
    if invoice.status == "paid":
        invoice.paid_at = payment.paid_at
        invoice.billing_completed_at = payment.paid_at
        invoice.receipt_number = invoice.receipt_number or f"RCT-{datetime.now(timezone.utc):%Y%m%d}-{str(invoice.id)[:8].upper()}"
        if invoice.source == "pharmacy_dispense":
            record_audit(session, current_user=current_user, action="PHARMACY_PAYMENT_COMPLETED", resource_type="invoice", resource_id=invoice.id, visit_id=invoice.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(invoice.pharmacy_dispense_id), "paid_amount": str(invoice.paid_amount), "payment_method": payload.payment_method})
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="payment",
        resource_id=payment.id,
        patient_id=visit.patient_id if visit else None,
        visit_id=invoice.visit_id,
        new_value={
            "invoice_id": invoice.id,
            "amount": amount,
            "payment_method": payload.payment_method,
            "status": invoice.status,
        },
    )
    return payment


async def _authorize_linked_pharmacy_dispense(
    invoice: Invoice,
    session: AsyncSession,
    *,
    confirmed_by: uuid.UUID | None = None,
    current_user: dict | None = None,
) -> None:
    """Authorize a linked pharmacy dispense after the invoice is fully paid."""
    if invoice.status != "paid" or not invoice.pharmacy_dispense_id:
        return
    dispense = await session.get(PharmacyDispense, invoice.pharmacy_dispense_id)
    if dispense is None:
        raise HTTPException(status_code=409, detail="Pharmacy dispense linked to invoice was not found")
    if dispense.status == "CONFIRMED" and dispense.billing_status == "AUTHORIZED":
        return
    try:
        await confirm_dispense_stock_consumption(
            session,
            dispense_id=dispense.id,
            tenant_id=dispense.tenant_id,
            facility_id=dispense.facility_id,
            confirmed_by=confirmed_by,
            billing_authorized=True,
        )
        record_audit(
            session,
            current_user=current_user,
            action="PHARMACY_DISPENSE_AUTHORIZED",
            resource_type="pharmacy_dispense",
            resource_id=dispense.id,
            patient_id=dispense.patient_id,
            visit_id=dispense.visit_id,
            new_value={"invoice_id": str(invoice.id), "status": dispense.status, "billing_status": dispense.billing_status},
        )
        if dispense.status == "CONFIRMED":
            record_audit(
                session,
                current_user=current_user,
                action="PHARMACY_DISPENSE_CONFIRMED",
                resource_type="pharmacy_dispense",
                resource_id=dispense.id,
                patient_id=dispense.patient_id,
                visit_id=dispense.visit_id,
                new_value={"invoice_id": str(invoice.id), "status": dispense.status},
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "billing_officer", "hospital_admin")),
):
    visit = await session.get(Visit, payload.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    # Check for duplicate draft invoice
    existing = (await session.execute(
        select(Invoice).where(Invoice.visit_id == payload.visit_id, Invoice.status == "draft")
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A draft invoice already exists for this visit")

    patient = await session.get(Patient, visit.patient_id)
    li_dicts = [item.model_dump() for item in (payload.line_items or [])]
    subtotal, total = _compute_totals(li_dicts, payload.discount, payload.tax)

    invoice = Invoice(
        id=uuid.uuid4(),
        visit_id=payload.visit_id,
        uhid=patient.uhid if patient else None,
        line_items=li_dicts,
        subtotal=subtotal,
        discount=payload.discount,
        tax=payload.tax,
        total=total,
        status="draft",
    )
    invoice.billing_started_at = datetime.now(timezone.utc)
    session.add(invoice)
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="invoice",
        resource_id=invoice.id,
        visit_id=invoice.visit_id,
        new_value={
            "line_items": li_dicts,
            "subtotal": subtotal,
            "discount": payload.discount,
            "tax": payload.tax,
            "total": total,
            "status": invoice.status,
        },
    )

    # Billing is a separate downstream workflow; it does not mutate OPD visit state.

    await session.commit()
    await session.refresh(invoice)
    return invoice


@router.get("/visit/{visit_id}", response_model=InvoiceRead)
async def get_invoice_by_visit(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "nurse", "doctor", "hospital_admin")),
):
    invoice = (await session.execute(
        select(Invoice)
        .where(Invoice.visit_id == visit_id)
        .order_by(Invoice.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found for this visit")
    return invoice


@router.post("/{invoice_id}/pay", response_model=InvoiceRead)
async def pay_invoice(
    invoice_id: uuid.UUID,
    payload: InvoicePayment,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "billing_officer", "hospital_admin")),
):
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.source == "pharmacy_dispense":
        await _require_pharmacy_permission(session, current_user, "PHARMACY_BILLING_PAYMENT")
    await _record_payment(invoice, payload, session, current_user)
    await _authorize_linked_pharmacy_dispense(
        invoice,
        session,
        confirmed_by=uuid.UUID(str(current_user["sub"])),
        current_user=current_user,
    )

    await session.commit()
    await session.refresh(invoice)

    # Notify → feedback trigger (Phase 4)
    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "invoice_paid",
        "invoice_id": str(invoice.id),
        "visit_id": str(invoice.visit_id),
    })

    return invoice


@router.post("/{invoice_id}/payments", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def record_invoice_payment(
    invoice_id: uuid.UUID,
    payload: InvoicePayment,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "hospital_admin")),
):
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.source == "pharmacy_dispense":
        await _require_pharmacy_permission(session, _, "PHARMACY_BILLING_PAYMENT")
    payment = await _record_payment(invoice, payload, session, _)
    await _authorize_linked_pharmacy_dispense(invoice, session, current_user=_)
    await session.commit()
    await session.refresh(payment)
    return payment


@router.get("/{invoice_id}/payments", response_model=List[PaymentRead])
async def list_invoice_payments(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "hospital_admin")),
):
    if not await session.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found")
    return (await session.execute(
        select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.paid_at)
    )).scalars().all()


@router.get("/{invoice_id}/receipt", response_model=InvoiceRead)
async def get_invoice_receipt(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "nurse", "hospital_admin")),
):
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status not in ("paid", "refunded"):
        raise HTTPException(status_code=400, detail="Receipt is available after full payment")
    return invoice


@router.post("/{invoice_id}/documents/finalize", response_model=DocumentVersionRead, status_code=status.HTTP_201_CREATED)
async def finalize_invoice_document(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "billing_officer", "hospital_admin")),
):
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status not in ("paid", "refunded"):
        raise HTTPException(status_code=400, detail="Invoice document can be finalized only after payment")

    visit = await session.get(Visit, invoice.visit_id)
    patient = await session.get(Patient, visit.patient_id) if visit else None
    snapshot = _invoice_to_snapshot(invoice, visit, patient)

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
            document_type=DOCUMENT_TYPE_INVOICE,
            parent_id=invoice.id,
            snapshot=snapshot,
            render_pdf=build_invoice_pdf,
            storage=_invoice_document_storage,
            generated_by_user_id=generated_by_user_id,
        )
    except DocumentFinalizationError as exc:
        raise HTTPException(status_code=409, detail="Could not finalize invoice document, please retry") from exc

    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="invoice_document",
        resource_id=document.id,
        patient_id=visit.patient_id if visit else None,
        visit_id=invoice.visit_id,
        new_value={
            "invoice_id": str(invoice.id),
            "version": document.version,
            "checksum_sha256": document.checksum_sha256,
            "storage_key": document.storage_key,
        },
    )
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/{invoice_id}/documents", response_model=List[DocumentVersionRead])
async def list_invoice_documents(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "nurse", "doctor", "hospital_admin")),
):
    if not await session.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found")
    return await list_document_versions(session, DOCUMENT_TYPE_INVOICE, invoice_id)


@router.get("/{invoice_id}/documents/{version}/download")
async def download_invoice_document(
    invoice_id: uuid.UUID,
    version: int,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "billing_officer", "nurse", "doctor", "hospital_admin")),
):
    if not await session.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found")
    document = await get_document_version(session, DOCUMENT_TYPE_INVOICE, invoice_id, version)
    if not document:
        raise HTTPException(status_code=404, detail="Invoice document version not found")

    try:
        pdf_bytes = read_document_bytes(_invoice_document_storage, document)
    except DocumentIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{invoice_id}-v{version}.pdf"'},
    )


@router.post("/{invoice_id}/refund", response_model=InvoiceRead)
async def refund_invoice(
    invoice_id: uuid.UUID,
    payload: RefundCreate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("billing_officer", "hospital_admin")),
):
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.source == "pharmacy_dispense":
        await _require_pharmacy_permission(session, _, "PHARMACY_BILLING_PAYMENT")
    if invoice.status != "paid":
        raise HTTPException(status_code=400, detail="Only fully paid invoices can be refunded")
    if payload.amount is not None and payload.amount != float(invoice.paid_amount):
        raise HTTPException(status_code=400, detail="Only full invoice refunds are supported")
    session.add(Refund(
        id=uuid.uuid4(), invoice_id=invoice.id, amount=invoice.paid_amount,
        reason=payload.reason, refunded_at=datetime.now(timezone.utc),
    ))
    invoice.status = "refunded"
    record_audit(
        session,
        current_user=_,
        action="REFUND",
        resource_type="invoice",
        resource_id=invoice.id,
        visit_id=invoice.visit_id,
        old_value={"status": "paid", "paid_amount": invoice.paid_amount},
        new_value={"status": "refunded", "refund_amount": invoice.paid_amount},
        reason=payload.reason,
    )
    await session.commit()
    await session.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/cancel", response_model=InvoiceRead)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    payload: RefundCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("billing_officer", "hospital_admin")),
):
    """Cancel an unpaid invoice and release any linked Pharmacy reservation."""
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.source == "pharmacy_dispense":
        await _require_pharmacy_permission(session, current_user, "PHARMACY_BILLING_CANCEL")
    if invoice.status in ("paid", "refunded"):
        raise HTTPException(status_code=409, detail="Paid invoices must use the refund workflow")
    if invoice.status == "cancelled":
        return invoice
    old_status = invoice.status

    if invoice.pharmacy_dispense_id:
        dispense = await session.get(PharmacyDispense, invoice.pharmacy_dispense_id)
        if dispense is None:
            raise HTTPException(status_code=409, detail="Pharmacy dispense linked to invoice was not found")
        try:
            await release_dispense_reservations(
                session,
                dispense_id=dispense.id,
                tenant_id=dispense.tenant_id,
                facility_id=dispense.facility_id,
                released_by=uuid.UUID(str(current_user["sub"])),
                reason=payload.reason,
            )
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    invoice.status = "cancelled"
    record_audit(
        session,
        current_user=current_user,
        action="CANCEL",
        resource_type="invoice",
        resource_id=invoice.id,
        visit_id=invoice.visit_id,
        old_value={"status": old_status},
        new_value={"status": "cancelled"},
        reason=payload.reason,
    )
    if invoice.source == "pharmacy_dispense":
        record_audit(session, current_user=current_user, action="PHARMACY_BILLING_CANCELLED", resource_type="invoice", resource_id=invoice.id, visit_id=invoice.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(invoice.pharmacy_dispense_id), "old_status": old_status, "new_status": "cancelled", "reason": payload.reason})
        record_audit(session, current_user=current_user, action="PHARMACY_RESERVATION_RELEASED_FOR_BILLING_CANCELLATION", resource_type="pharmacy_dispense", resource_id=invoice.pharmacy_dispense_id, visit_id=invoice.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(invoice.pharmacy_dispense_id), "reason": payload.reason})
    await session.commit()
    await session.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/sync-payment", response_model=InvoiceRead)
async def sync_razorpay_payment(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "billing_officer", "nurse", "hospital_admin")),
):
    """
    Fallback for missed webhooks (ngrok down, stale URL, etc.).
    Calls the Razorpay API directly to check if the order was paid,
    and updates the invoice + visit if so.
    """
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.source == "pharmacy_dispense":
        await _require_pharmacy_permission(session, current_user, "PHARMACY_BILLING_VERIFY")
    if invoice.status == "paid":
        # Invoice already paid — keep the OPD lifecycle canonical and do not mutate
        # visit.status through legacy billing-state repair logic.
        return invoice
    if not invoice.razorpay_order_id:
        raise HTTPException(status_code=400, detail="No Razorpay order linked to this invoice")

    payment = fetch_order_payments(invoice.razorpay_order_id)
    if not payment:
        raise HTTPException(status_code=402, detail="No captured payment found on Razorpay for this order")

    invoice.razorpay_payment_id = payment.get("id")
    invoice.payment_method = payment.get("method", "razorpay")
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)

    await _authorize_linked_pharmacy_dispense(invoice, session, current_user=current_user)

    await session.commit()
    await session.refresh(invoice)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "pos:payment", {
        "event": "payment_success",
        "razorpay_order_id": invoice.razorpay_order_id,
        "razorpay_payment_id": invoice.razorpay_payment_id,
        "payment_method": invoice.payment_method,
    })
    logger.info("Payment synced manually: invoice=%s order=%s", invoice_id, invoice.razorpay_order_id)
    return invoice


@router.post("/{invoice_id}/resend-pos", response_model=InvoiceRead)
async def resend_pos_request(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "nurse", "hospital_admin")),
):
    """
    Re-broadcast the Razorpay POS payment request to the kiosk screen.
    Used when the POS screen was missed or timed out.
    """
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Invoice already paid")
    if not invoice.razorpay_order_id:
        raise HTTPException(status_code=400, detail="No Razorpay order linked to this invoice")

    visit = await session.get(Visit, invoice.visit_id)
    patient = await session.get(Patient, visit.patient_id) if visit else None

    tenant = current_user.get("tenant_schema", "public")
    
    # Validate Razorpay is configured
    if not settings.RAZORPAY_KEY_ID:
        logger.error("❌ Razorpay payment requested but RAZORPAY_KEY_ID not configured in environment!")
        raise HTTPException(
            status_code=500,
            detail="Razorpay payment gateway is not configured. Contact administrator."
        )
    
    broadcast_payload = {
        "event": "payment_request",
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "razorpay_order_id": invoice.razorpay_order_id,
        "invoice_id": str(invoice.id),
        "amount": int(float(invoice.total) * 100),
        "amount_display": f"₹{float(invoice.total):.0f}",
        "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Patient",
        "uhid": invoice.uhid or "",
        "description": invoice.line_items[0]["description"] if invoice.line_items else "Consultation Fee",
    }
    
    logger.info(
        "Broadcasting to pos:payment - Payload: %s",
        json.dumps({
            "event": broadcast_payload.get("event"),
            "razorpay_key_id": broadcast_payload.get("razorpay_key_id"),
            "razorpay_order_id": broadcast_payload.get("razorpay_order_id"),
            "invoice_id": broadcast_payload.get("invoice_id"),
            "tenant": tenant,
        })
    )
    
    await ws_manager.broadcast(tenant, "pos:payment", broadcast_payload)
    logger.info("POS payment request re-sent: invoice=%s", invoice_id)
    return invoice


@router.post("/{invoice_id}/admit-patient", response_model=InvoiceRead)
async def admit_patient_manually(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("receptionist", "nurse", "hospital_admin", "super_admin")),
):
    """
    Nurse manually marks an invoice as paid (cash collected at desk)
    and advances the visit from pre_billing → registered so it appears
    in the nurse vitals queue.
    """
    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "paid":
        return invoice

    invoice.payment_method = "cash"
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)

    await _authorize_linked_pharmacy_dispense(
        invoice,
        session,
        confirmed_by=uuid.UUID(str(current_user["sub"])),
    )

    await session.commit()
    await session.refresh(invoice)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "visit:update", {
        "event": "invoice_paid",
        "invoice_id": str(invoice.id),
        "visit_id": str(invoice.visit_id),
    })
    logger.info("Patient manually admitted by nurse: invoice=%s", invoice_id)
    return invoice


@webhook_router.post("/razorpay/webhook", include_in_schema=True, status_code=200)
async def razorpay_webhook(request: Request):
    """
    Razorpay webhook receiver.
    Handles `payment.captured` events to mark invoices paid and advance the visit.

    The tenant schema is embedded in the Razorpay order notes at order creation time
    (key: 'tenant_schema'), so this endpoint works for all tenants without JWT.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    
    logger.info("Webhook: Received Razorpay webhook. Signature header present: %s", bool(signature))

    if not verify_webhook_signature(body, signature):
        logger.warning("Razorpay webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event_data = json.loads(body)
        logger.info("Webhook: Parsed event: %s", event_data.get("event"))
    except json.JSONDecodeError:
        logger.error("Webhook: Failed to parse JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle both captured (live/auto-capture) and authorized (test mode default)
    if event_data.get("event") not in ("payment.captured", "payment.authorized"):
        logger.info("Webhook: Ignoring event type: %s", event_data.get("event"))
        return {"status": "ignored"}

    razorpay_context = _extract_razorpay_context(event_data)
    order_id = razorpay_context["order_id"]
    payment_id = razorpay_context["payment_id"]
    payment_method = razorpay_context["payment_method"]  # upi / card / netbanking
    tenant_schema = razorpay_context["tenant_schema"]
    order_notes = razorpay_context["order_notes"]
    payment_notes = razorpay_context["payment_notes"]

    if razorpay_context.get("tenant_conflict"):
        logger.warning("Razorpay webhook: conflicting tenant notes for order_id=%s", order_id)
        raise HTTPException(status_code=400, detail="Conflicting webhook tenant context")

    logger.info(
        "Webhook: Extracted data: order_id=%s, payment_id=%s, tenant=%s, method=%s, order_notes=%s, payment_notes=%s",
        order_id, payment_id, tenant_schema, payment_method, order_notes, payment_notes,
    )

    if not order_id or not payment_id:
        logger.warning("Razorpay webhook: missing order or payment identity")
        raise HTTPException(status_code=400, detail="Webhook payment identity is missing")

    if not tenant_schema or not tenant_schema.replace("_", "").isalnum():
        logger.warning(
            "Razorpay webhook: missing or invalid tenant_schema. order_id=%s tenant=%s order_notes=%s payment_notes=%s",
            order_id, tenant_schema, order_notes, payment_notes,
        )
        raise HTTPException(status_code=400, detail="Webhook tenant context is invalid")

    # Manually acquire a session scoped to the correct tenant schema
    ctx_token = tenant_schema_var.set(tenant_schema)
    try:
        async with AsyncSessionLocal() as session:
            tenant = await session.scalar(select(Tenant).where(
                Tenant.schema_name == tenant_schema,
                Tenant.is_active.is_(True),
            ))
            if tenant is None:
                raise HTTPException(status_code=400, detail="Webhook tenant context is invalid")
            await session.execute(text(f'SET search_path TO "{tenant_schema}", public'))

            logger.info(
                "Webhook: Looking for invoice with order_id=%s in tenant=%s",
                order_id, tenant_schema,
            )

            invoice = (await session.execute(
                select(Invoice).where(Invoice.razorpay_order_id == order_id).with_for_update()
            )).scalar_one_or_none()

            if not invoice:
                logger.error(
                    "Webhook: Invoice not found for order_id=%s tenant=%s. Cannot process payment.",
                    order_id, tenant_schema,
                )
                raise HTTPException(status_code=400, detail="Webhook order is not linked to an invoice")

            noted_invoice_id = order_notes.get("invoice_id") or payment_notes.get("invoice_id")
            if noted_invoice_id and str(noted_invoice_id) != str(invoice.id):
                raise HTTPException(status_code=400, detail="Webhook invoice identity does not match")

            payment_entity = event_data.get("payload", {}).get("payment", {}).get("entity", {})
            event_amount = payment_entity.get("amount")
            event_currency = payment_entity.get("currency")
            event_status = payment_entity.get("status")
            expected_amount = int(Decimal(str(invoice.total)) * 100)
            if event_amount != expected_amount or event_currency != "INR":
                raise HTTPException(status_code=400, detail="Webhook payment amount or currency does not match")
            expected_status = "captured" if event_data.get("event") == "payment.captured" else "authorized"
            if event_status != expected_status:
                raise HTTPException(status_code=400, detail="Webhook payment status does not match the event")
            
            if invoice.status == "paid":
                if invoice.razorpay_payment_id != payment_id:
                    raise HTTPException(status_code=409, detail="Invoice was already paid by a different payment")
                logger.info(
                    "Webhook: Invoice %s already paid. Skipping duplicate.",
                    invoice.id,
                )
                return {"status": "ok"}

            logger.info(
                "Webhook: Processing payment for invoice %s (source=%s, pharmacy_queue=%s)",
                invoice.id, invoice.source, invoice.pharmacy_queue_id,
            )

            # Update invoice payment fields
            invoice.razorpay_payment_id = payment_id
            invoice.payment_method = payment_method
            invoice.status = "paid"
            invoice.paid_at = datetime.now(timezone.utc)
            invoice.paid_amount = invoice.total
            invoice.receipt_number = invoice.receipt_number or f"RCT-{datetime.now(timezone.utc):%Y%m%d}-{str(invoice.id)[:8].upper()}"
            if invoice.source == "pharmacy_dispense":
                record_audit(session, current_user=None, action="PHARMACY_PAYMENT_COMPLETED", resource_type="invoice", resource_id=invoice.id, visit_id=invoice.visit_id, new_value={"invoice_id": str(invoice.id), "dispense_id": str(invoice.pharmacy_dispense_id), "paid_amount": str(invoice.paid_amount), "payment_method": payment_method})

            if payment_id:
                existing_payment = (await session.execute(
                    select(Payment).where(Payment.transaction_reference == payment_id)
                )).scalar_one_or_none()
                if not existing_payment:
                    session.add(Payment(
                        id=uuid.uuid4(),
                        invoice_id=invoice.id,
                        amount=invoice.total,
                        payment_method=payment_method or "razorpay",
                        transaction_reference=payment_id,
                        gateway="razorpay",
                        paid_at=invoice.paid_at,
                    ))
            
            logger.info(
                "Webhook: Set invoice fields — razorpay_payment_id=%s, payment_method=%s, status=paid, paid_at=%s",
                payment_id, payment_method, invoice.paid_at,
            )

            # If this was a pharmacy dispense invoice, advance the queue
            if invoice.source == "pharmacy" and invoice.pharmacy_queue_id:
                pq = await session.get(PharmacyQueue, invoice.pharmacy_queue_id)
                if pq and pq.status != "dispensed":
                    pq.status = "dispensed"
                    logger.info(
                        "Webhook: Marked pharmacy queue %s as dispensed",
                        invoice.pharmacy_queue_id,
                    )

            await _authorize_linked_pharmacy_dispense(invoice, session)

            await session.commit()
            logger.info(
                "Webhook: Committed invoice payment",
            )
            
            # Verify the update was committed by re-querying from database
            refreshed_invoice = (await session.execute(
                select(Invoice).where(Invoice.id == invoice.id)
            )).scalar_one_or_none()
            
            if refreshed_invoice:
                logger.info(
                    "Webhook: Verified invoice in DB — status=%s, payment_method=%s, paid_at=%s, razorpay_payment_id=%s",
                    refreshed_invoice.status, refreshed_invoice.payment_method, refreshed_invoice.paid_at, refreshed_invoice.razorpay_payment_id,
                )
            else:
                logger.error("Webhook: Invoice disappeared from DB after commit! id=%s", invoice.id)

        # Notify POS screen of payment success
        try:
            await ws_manager.broadcast(tenant_schema, "pos:payment", {
                "event": "payment_success",
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "payment_method": payment_method,
            })
            logger.info("Webhook: Broadcasted payment_success to pos:payment")
        except Exception as e:
            logger.error("Webhook: Failed to broadcast pos:payment: %s", e)
        
        # Notify queue listeners (visit moved to registered)
        try:
            await ws_manager.broadcast(tenant_schema, "queue:update", {
                "event": "visit_registered",
            })
            logger.info("Webhook: Broadcasted visit_registered to queue:update")
        except Exception as e:
            logger.error("Webhook: Failed to broadcast queue:update: %s", e)
        
        # Notify pharmacy page if it was a pharmacy dispense payment
        if invoice.source == "pharmacy":
            try:
                await ws_manager.broadcast(tenant_schema, "pharmacy:update", {
                    "event": "pharmacy_online_paid",
                    "razorpay_order_id": order_id,
                })
                logger.info(
                    "Webhook: Pharmacy payment success broadcast: order=%s payment=%s tenant=%s",
                    order_id, payment_id, tenant_schema,
                )
            except Exception as e:
                logger.error("Webhook: Failed to broadcast pharmacy:update: %s", e)

        logger.info(
            "Webhook: Razorpay payment captured: order=%s payment=%s tenant=%s source=%s",
            order_id, payment_id, tenant_schema, invoice.source,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Webhook: Unexpected error processing order_id=%s tenant=%s: %s",
            order_id, tenant_schema, e, exc_info=True,
        )
        # Still acknowledge to Razorpay so it stops retrying
        return {"status": "ok"}
    finally:
        tenant_schema_var.reset(ctx_token)

    return {"status": "ok"}
