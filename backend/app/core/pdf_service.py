"""
Prescription PDF generator.

Builds a formatted prescription PDF using ReportLab, uploads it to Cloudinary,
and returns the public HTTPS URL.  All errors are raised — callers should handle them.
"""
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _upload_to_cloudinary(pdf_bytes: bytes, public_id: str) -> str:
    """Upload PDF bytes to Cloudinary and return the secure_url."""
    from app.core.config import settings
    import cloudinary
    import cloudinary.uploader

    if not (settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET):
        raise RuntimeError("Cloudinary not configured — cannot upload prescription PDF.")

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    result = cloudinary.uploader.upload(
        io.BytesIO(pdf_bytes),
        public_id=public_id,
        resource_type="raw",
        overwrite=True,
        type="upload",
    )
    return result["secure_url"]


# ── PDF builder ───────────────────────────────────────────────────────────────

def build_prescription_pdf(
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
    diagnosis: Optional[list],        # list of {code, description}
    notes: Optional[str],
    medicines: Optional[list],        # list of {name, dose, frequency, food_instruction, duration, route}
    lab_tests: Optional[list],        # list of {test_name, notes}
    follow_up_date: Optional[str],
) -> bytes:
    """Return a PDF as bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    W = A4[0] - 36 * mm  # usable width

    heading_style = ParagraphStyle(
        "heading",
        parent=styles["Normal"],
        fontSize=18,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1e40af"),
        spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "sub",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#6b7280"),
    )
    label_style = ParagraphStyle(
        "label",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#374151"),
    )
    value_style = ParagraphStyle(
        "value",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#111827"),
    )
    section_style = ParagraphStyle(
        "section",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1e40af"),
        spaceBefore=8,
        spaceAfter=3,
    )

    BLUE = colors.HexColor("#1e40af")
    LIGHT_BLUE = colors.HexColor("#eff6ff")
    GRAY = colors.HexColor("#e5e7eb")
    DARK = colors.HexColor("#111827")

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph(hospital_name, heading_style))
    story.append(Paragraph("Prescription / Discharge Summary", sub_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=6))

    # ── Patient info table ────────────────────────────────────────────────────
    age_str = str(age) + " yrs" if age else (dob or "—")
    patient_data = [
        [Paragraph("Patient Name", label_style), Paragraph(patient_name, value_style),
         Paragraph("UHID", label_style), Paragraph(uhid, value_style)],
        [Paragraph("Gender", label_style), Paragraph(gender.capitalize(), value_style),
         Paragraph("Age", label_style), Paragraph(age_str, value_style)],
        [Paragraph("Phone", label_style), Paragraph(phone, value_style),
         Paragraph("Visit Date", label_style), Paragraph(visit_date, value_style)],
        [Paragraph("Department", label_style), Paragraph(department_name or "—", value_style),
         Paragraph("Doctor", label_style),
         Paragraph(f"Dr. {doctor_name}" + (f" ({doctor_specialization})" if doctor_specialization else ""), value_style)],
    ]
    col = W / 4
    pt = Table(patient_data, colWidths=[col * 0.8, col * 1.2, col * 0.8, col * 1.2])
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.5, GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(pt)
    story.append(Spacer(1, 6))

    # ── Consultation notes ────────────────────────────────────────────────────
    if chief_complaint:
        story.append(Paragraph("Chief Complaint", section_style))
        story.append(Paragraph(chief_complaint, value_style))

    if diagnosis:
        story.append(Paragraph("Diagnosis", section_style))
        for d in diagnosis:
            code = d.get("code", "")
            desc = d.get("description", "")
            text = f"<b>{code}</b> — {desc}" if code else desc
            story.append(Paragraph(text, value_style))

    if notes:
        story.append(Paragraph("Doctor's Notes", section_style))
        story.append(Paragraph(notes.replace("\n", "<br/>"), value_style))

    # ── Medicines table ───────────────────────────────────────────────────────
    if medicines:
        story.append(Paragraph("Medicines", section_style))
        header = [
            Paragraph("#", label_style),
            Paragraph("Medicine", label_style),
            Paragraph("Dose", label_style),
            Paragraph("Frequency", label_style),
            Paragraph("Food", label_style),
            Paragraph("Duration", label_style),
            Paragraph("Route", label_style),
        ]
        med_rows = [header]
        for idx, m in enumerate(medicines, 1):
            med_rows.append([
                Paragraph(str(idx), value_style),
                Paragraph(m.get("name", ""), value_style),
                Paragraph(m.get("dose", ""), value_style),
                Paragraph(m.get("frequency", ""), value_style),
                Paragraph(m.get("food_instruction", "N/A"), value_style),
                Paragraph(m.get("duration", ""), value_style),
                Paragraph(m.get("route", "oral"), value_style),
            ])
        cw = W / 7
        mt = Table(med_rows, colWidths=[cw * 0.4, cw * 1.8, cw * 0.8, cw * 1.0, cw * 0.9, cw * 1.1, cw * 1.0])
        mt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ("BOX", (0, 0), (-1, -1), 0.5, GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(mt)

    # ── Lab tests ─────────────────────────────────────────────────────────────
    if lab_tests:
        story.append(Paragraph("Lab Tests Ordered", section_style))
        lt_header = [Paragraph("#", label_style), Paragraph("Test", label_style), Paragraph("Notes", label_style)]
        lt_rows = [lt_header]
        for idx, t in enumerate(lab_tests, 1):
            lt_rows.append([
                Paragraph(str(idx), value_style),
                Paragraph(t.get("test_name", ""), value_style),
                Paragraph(t.get("notes", "—") or "—", value_style),
            ])
        lt = Table(lt_rows, colWidths=[W * 0.08, W * 0.42, W * 0.50])
        lt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ("BOX", (0, 0), (-1, -1), 0.5, GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(lt)

    # ── Follow-up ─────────────────────────────────────────────────────────────
    if follow_up_date:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Follow-up Date: <b>{follow_up_date}</b>", value_style))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY))
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")
    story.append(Paragraph(
        f"Generated: {generated_at} · {hospital_name}",
        ParagraphStyle("footer", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#9ca3af"), alignment=1),
    ))

    doc.build(story)
    return buf.getvalue()


# ── Public function ───────────────────────────────────────────────────────────

def generate_and_upload_prescription_pdf(
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
) -> str:
    """Build prescription PDF, upload to Cloudinary, return public URL."""
    pdf_bytes = build_prescription_pdf(
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
    safe_name = "".join(c if c.isalnum() else "_" for c in patient_name)[:30]
    public_id = f"prescriptions/{uhid}_{safe_name}_{uuid.uuid4().hex[:8]}.pdf"
    url = _upload_to_cloudinary(pdf_bytes, public_id)
    logger.info("Prescription PDF uploaded: %s", url)
    return url
