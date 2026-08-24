"""Prescription PDF rendering — presentation only, no persistence/versioning here.

Persistence/versioning is handled generically by `app.services.document_service`.
"""
import io
from datetime import timezone


def canonical_prescription_snapshot(prescription: dict) -> dict:
    """Return a stable prescription snapshot suitable for checksum and versioning.

    Built entirely from immutable clinical facts captured at finalize time
    (never re-derived from current/mutable medicine-master rows later).
    """
    return {
        "prescription": {
            "id": str(prescription["id"]),
            "visit_id": str(prescription["visit_id"]),
            "uhid": prescription.get("uhid"),
            "status": prescription.get("status"),
            "instructions": prescription.get("instructions"),
            "medicines": prescription.get("medicines") or [],
            "created_at": prescription["created_at"].astimezone(timezone.utc).isoformat()
            if prescription.get("created_at")
            else None,
        },
        "patient": {
            "id": str(prescription["patient_id"]) if prescription.get("patient_id") else None,
            "name": prescription.get("patient_name"),
        },
        "doctor": {
            "id": str(prescription["doctor_id"]) if prescription.get("doctor_id") else None,
            "name": prescription.get("doctor_name"),
        },
    }


def build_prescription_pdf(snapshot: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rx = snapshot["prescription"]
    patient = snapshot["patient"]
    doctor = snapshot["doctor"]
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

    story.append(Paragraph("Prescription", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Prescription ID: {rx['id']}", styles["Normal"]))
    story.append(Paragraph(f"Visit ID: {rx['visit_id']}", styles["Normal"]))
    story.append(Paragraph(f"UHID: {rx.get('uhid') or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Patient: {patient.get('name') or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Doctor: {doctor.get('name') or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Status: {rx.get('status')}", styles["Normal"]))
    story.append(Spacer(1, 10))

    rows = [["Medicine", "Dose", "Frequency", "Duration"]]
    for m in rx.get("medicines") or []:
        rows.append(
            [
                str(m.get("medicine") or m.get("name_snapshot") or ""),
                str(m.get("dose") or "-"),
                str(m.get("frequency") or "-"),
                str(m.get("duration") or "-"),
            ]
        )

    table = Table(rows, colWidths=[70 * mm, 35 * mm, 35 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ]
        )
    )
    story.append(table)

    if rx.get("instructions"):
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Instructions: {rx['instructions']}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()
