"""Lab billing integration service - creates invoices when lab results are verified."""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.tenant.invoice import Invoice
from app.models.tenant.patient import Patient
from app.services.audit_service import record_audit


class LabPricingError(Exception):
    """Raised when a test snapshot has no server-derived price at all —
    distinct from an intentionally configured zero price, which is valid."""


async def create_lab_invoice_if_needed(
    session: AsyncSession,
    lab_order_id: uuid.UUID,
    visit_id: uuid.UUID,
    tests: list,
    patient_id: uuid.UUID,
    current_user: dict,
) -> Invoice | None:
    """
    Create an invoice for a lab order if one doesn't already exist.
    
    - Check if invoice already exists for this lab_order_id (via unique constraint)
    - Extract test prices from JSONB tests array (snapshotted at order time)
    - Create line items with test names and prices
    - Set source="lab" for tracking
    - Return existing or newly created invoice
    - Idempotent: safe to call multiple times on same lab order
    
    Args:
        session: AsyncSession
        lab_order_id: UUID of the lab order
        visit_id: UUID of the visit
        tests: JSONB array of test objects with price field
        patient_id: UUID of the patient
        current_user: Current user context for audit trail
    
    Returns:
        Invoice object if created/found, or None if skipped
    """
    # Check if invoice already exists for this lab order
    existing = await session.scalar(
        select(Invoice).where(Invoice.lab_order_id == lab_order_id)
    )
    if existing:
        return existing
    
    # Get patient for UHID
    patient = await session.get(Patient, patient_id)
    
    # Extract test prices and create line items. A test dict with no "price"
    # key at all means it was never snapshotted from the Lab Test Master
    # (e.g. a legacy free-text order) — that is a data-contract error and
    # must not silently become a zero charge. An explicit price of 0.0 (a
    # genuinely free test in the master catalog) is valid and billed as such.
    line_items = []
    total_amount = 0.0

    for test in tests:
        if "price" not in test:
            raise LabPricingError(
                f"Lab test '{test.get('test_name') or test.get('test') or test.get('test_code') or 'unknown'}' "
                "has no server-snapshotted price and cannot be billed."
            )
        test_price = float(test["price"])
        test_name = test.get("test_name") or test.get("test", "Lab Test")
        test_code = test.get("test_code", "")
        
        line_items.append({
            "description": f"{test_code}: {test_name}" if test_code else f"Lab Test: {test_name}",
            "test_id": str(test.get("test_id")) if test.get("test_id") else None,
            "test_code": test_code,
            "amount": test_price,
        })
        total_amount += test_price
    
    # Create invoice with lab charges
    invoice = Invoice(
        id=uuid.uuid4(),
        visit_id=visit_id,
        uhid=patient.uhid if patient else None,
        lab_order_id=lab_order_id,
        source="lab",
        line_items=line_items,
        subtotal=total_amount,
        discount=0.0,
        tax=0.0,
        total=total_amount,
        status="pending",
    )
    
    session.add(invoice)
    
    # Record audit trail
    record_audit(
        session,
        current_user=current_user,
        action="CREATE",
        resource_type="invoice",
        resource_id=invoice.id,
        patient_id=patient_id,
        visit_id=visit_id,
        new_value={
            "lab_order_id": str(lab_order_id),
            "line_items": line_items,
            "subtotal": total_amount,
            "total": total_amount,
            "status": invoice.status,
            "source": "lab",
        },
    )
    
    return invoice
