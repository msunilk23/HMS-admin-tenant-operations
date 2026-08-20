"""
SMS / WhatsApp notification helper — Twilio provider.

Errors are always logged and swallowed — notification failures
must never block the main operation.
"""
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Twilio helpers ─────────────────────────────────────────────────────────────

def _twilio_send_sms(*, to: str, body: str) -> None:
    """Send a plain SMS via Twilio. Raises on any error — caller must catch."""
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_SMS_FROM_NUMBER

    if not (sid and token and from_number):
        logger.warning("Twilio SMS not configured — set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_SMS_FROM_NUMBER.")
        return

    from twilio.rest import Client  # lazy import
    Client(sid, token).messages.create(body=body, from_=from_number, to=to)


def _twilio_send_whatsapp(*, to: str, body: str, media_url: str | None = None) -> None:
    """Send a WhatsApp message via Twilio. Falls back to SMS if no WhatsApp from-number. Raises on error."""
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN

    if not (sid and token):
        logger.warning("Twilio not configured — skipping WhatsApp to %s.", to)
        return

    whatsapp_from = settings.TWILIO_WHATSAPP_FROM
    from twilio.rest import Client  # lazy import
    client = Client(sid, token)

    if whatsapp_from:
        kwargs: dict = dict(from_=whatsapp_from, body=body, to=f"whatsapp:{to}")
        if media_url:
            kwargs["media_url"] = [media_url]
        client.messages.create(**kwargs)
    else:
        # Fallback: plain SMS (no media)
        _twilio_send_sms(to=to, body=body)


# ── Phone number normalisation ─────────────────────────────────────────────────

def _normalise_phone(phone: str) -> str:
    """Return E.164 form for an Indian 10-digit number; leave others intact."""
    p = phone.strip().lstrip("+")
    if p.isdigit() and len(p) == 10:
        p = "91" + p
    return "+" + p


# ── Public API ─────────────────────────────────────────────────────────────────

def send_doctor_credentials(
    *,
    to_phone: str,
    full_name: str,
    username: str,
    password: str,
    hospital_name: str = "your hospital",
    send_via: str = "sms",
) -> None:
    """
    Send credentials to a newly onboarded doctor via SMS or WhatsApp.
    Never raises — errors are logged and swallowed.
    """
    normalised = _normalise_phone(to_phone)
    body = (
        f"Hello Dr. {full_name},\n\n"
        f"Your login credentials for {hospital_name}:\n"
        f"  Username : {username}\n"
        f"  Password : {password}\n\n"
        f"Please change your password after first login.\n"
        f"— Admin Team"
    )
    try:
        if send_via == "whatsapp":
            _twilio_send_whatsapp(to=normalised, body=body)
        else:
            _twilio_send_sms(to=normalised, body=body)
        logger.info("Credentials sent via %s to %s", send_via, normalised)
    except Exception:
        logger.exception("Failed to send credentials to %s", normalised)


def send_staff_credentials(
    *,
    to_phone: str,
    full_name: str,
    username: str,
    password: str,
    hospital_name: str = "your hospital",
    role: str = "",
    gender: str = "",
    is_new: bool = True,
    send_via: str = "sms",
) -> None:
    """
    Send credentials to a staff member via SMS or WhatsApp.
    Uses Dr. for doctors, Ms. for female staff, Mr. for male staff.
    Never raises — errors are logged and swallowed.
    """
    if role == "doctor":
        salutation = "Dr."
    elif gender.lower() == "female":
        salutation = "Ms."
    else:
        salutation = "Mr."
    action = "created" if is_new else "reset"
    normalised = _normalise_phone(to_phone)
    body = (
        f"Hello {salutation} {full_name},\n\n"
        f"Your login credentials for {hospital_name} have been {action}:\n"
        f"  Username : {username}\n"
        f"  Password : {password}\n\n"
        f"Please change your password after logging in.\n"
        f"— Admin Team"
    )
    try:
        if send_via == "whatsapp":
            _twilio_send_whatsapp(to=normalised, body=body)
        else:
            _twilio_send_sms(to=normalised, body=body)
        logger.info("Credentials sent via %s to %s", send_via, normalised)
    except Exception:
        logger.exception("Failed to send credentials to %s", normalised)


def send_patient_welcome(
    *,
    to_phone: str,
    patient_name: str,
    uhid: str,
    hospital_name: str = "our hospital",
) -> None:
    """
    Send a welcome message to a newly registered patient via WhatsApp (Twilio).
    Never raises — errors are logged and swallowed.
    """
    normalised = _normalise_phone(to_phone)
    body = (
        f"Welcome {patient_name},\n\n"
        f"You have successfully registered with {hospital_name}.\n"
        f"Your unique Health ID (UHID) is: {uhid}\n\n"
        f"Please quote this UHID for all future visits.\n"
        f"— {hospital_name}"
    )
    try:
        _twilio_send_whatsapp(to=normalised, body=body)
        logger.info("Welcome message sent to patient %s (%s)", uhid, normalised)
    except Exception:
        logger.exception("Failed to send welcome message to %s", normalised)


def send_appointment_confirmation(
    *,
    to_phone: str,
    patient_name: str,
    uhid: str,
    slot_time_utc,
    doctor_name: str | None = None,
    appt_type: str = "walkin",
    hospital_name: str = "our hospital",
) -> None:
    """
    Send an appointment confirmation via WhatsApp immediately after booking.
    Never raises — errors are logged and swallowed.
    """
    import datetime
    _IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    slot_ist = slot_time_utc.astimezone(_IST)
    date_str = slot_ist.strftime("%A, %d %B %Y")   # e.g. Friday, 24 April 2026
    time_str = slot_ist.strftime("%I:%M %p IST").lstrip("0")  # e.g. 1:15 PM IST

    type_labels = {"walkin": "Walk-in", "phone": "Phone", "online": "Online"}
    type_label = type_labels.get(appt_type, appt_type.capitalize())

    doc_line = f"  Doctor      : Dr. {doctor_name}\n" if doctor_name else ""
    body = (
        f"Dear {patient_name},\n\n"
        f"\u2705 Your appointment has been confirmed at {hospital_name}.\n\n"
        f"\U0001f4cb Appointment Details:\n"
        f"  UHID        : {uhid}\n"
        f"  Date        : {date_str}\n"
        f"  Time        : {time_str}\n"
        f"{doc_line}"
        f"  Type        : {type_label}\n\n"
        f"Please arrive 10 minutes before your scheduled time.\n"
        f"\u2014 {hospital_name}"
    )
    normalised = _normalise_phone(to_phone)
    try:
        _twilio_send_whatsapp(to=normalised, body=body)
        logger.info("Appointment confirmation sent to %s (%s)", uhid, normalised)
    except Exception:
        logger.exception("Failed to send appointment confirmation to %s", normalised)


def send_prescription_whatsapp(
    *,
    to_phone: str,
    patient_name: str,
    uhid: str,
    hospital_name: str,
    doctor_name: str | None,
    pdf_url: str,
) -> None:
    """
    Send prescription PDF via WhatsApp to the patient after pharmacy dispense.
    Never raises — errors are logged and swallowed.
    """
    normalised = _normalise_phone(to_phone)
    doc_line = f"Consulting Doctor: Dr. {doctor_name}\n" if doctor_name else ""
    body = (
        f"Dear {patient_name},\n\n"
        f"Your prescription from {hospital_name} is ready.\n"
        f"{doc_line}"
        f"UHID: {uhid}\n\n"
        f"Please find your prescription (medicines, lab tests & doctor's notes) in the attached PDF.\n\n"
        f"Get well soon!\n— {hospital_name}"
    )
    try:
        _twilio_send_whatsapp(to=normalised, body=body, media_url=pdf_url)
        logger.info("Prescription PDF sent via WhatsApp to %s (%s)", uhid, normalised)
    except Exception:
        logger.exception("Failed to send prescription WhatsApp to %s", normalised)
