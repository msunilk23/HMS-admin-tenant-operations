import io
from datetime import timezone

"""Invoice PDF rendering — presentation only, no persistence/versioning here.

Persistence/versioning is handled generically by `app.services.document_service`.
"""


def canonical_invoice_snapshot(invoice: dict) -> dict:
    """Return a stable invoice snapshot suitable for checksum and versioning."""
    return {
        "invoice": {
            "id": str(invoice["id"]),
            "visit_id": str(invoice["visit_id"]),
            "uhid": invoice.get("uhid"),
            "line_items": invoice.get("line_items") or [],
            "subtotal": float(invoice.get("subtotal") or 0),
            "discount": float(invoice.get("discount") or 0),
            "tax": float(invoice.get("tax") or 0),
            "total": float(invoice.get("total") or 0),
            "paid_amount": float(invoice.get("paid_amount") or 0),
            "status": invoice.get("status"),
            "payment_method": invoice.get("payment_method"),
            "receipt_number": invoice.get("receipt_number"),
            "source": invoice.get("source"),
            "pharmacy_queue_id": str(invoice["pharmacy_queue_id"]) if invoice.get("pharmacy_queue_id") else None,
            "pharmacy_dispense_id": str(invoice["pharmacy_dispense_id"]) if invoice.get("pharmacy_dispense_id") else None,
            "created_at": invoice["created_at"].astimezone(timezone.utc).isoformat() if invoice.get("created_at") else None,
            "paid_at": invoice["paid_at"].astimezone(timezone.utc).isoformat() if invoice.get("paid_at") else None,
        },
        "patient": {
            "id": str(invoice["patient_id"]) if invoice.get("patient_id") else None,
            "name": invoice.get("patient_name"),
            "phone": invoice.get("patient_phone"),
        },
        "visit": {
            "doctor_id": str(invoice["doctor_id"]) if invoice.get("doctor_id") else None,
            "department_id": str(invoice["department_id"]) if invoice.get("department_id") else None,
        },
    }


def build_invoice_pdf(snapshot: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    invoice = snapshot["invoice"]
    patient = snapshot["patient"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Invoice Receipt", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Invoice ID: {invoice['id']}", styles["Normal"]))
    story.append(Paragraph(f"Visit ID: {invoice['visit_id']}", styles["Normal"]))
    story.append(Paragraph(f"UHID: {invoice.get('uhid') or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Patient: {patient.get('name') or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Status: {invoice.get('status')}", styles["Normal"]))
    story.append(Paragraph(f"Payment Method: {invoice.get('payment_method') or '-'}", styles["Normal"]))
    story.append(Spacer(1, 10))

    rows = [["Description", "Amount"]]
    for li in invoice.get("line_items") or []:
        rows.append([str(li.get("description", "")), f"{float(li.get('amount', 0)):.2f}"])

    rows.extend(
        [
            ["Subtotal", f"{invoice['subtotal']:.2f}"],
            ["Discount", f"{invoice['discount']:.2f}"],
            ["Tax", f"{invoice['tax']:.2f}"],
            ["Total", f"{invoice['total']:.2f}"],
            ["Paid", f"{invoice['paid_amount']:.2f}"],
        ]
    )

    table = Table(rows, colWidths=[120 * mm, 50 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buf.getvalue()
