"""
Canonical feature key registry for the SaaS entitlements system.

Every feature available in the platform is listed here.
This list is used by:
  - Alembic migration (seed data)
  - require_feature() dependency
  - Super admin API (GET /super/features)
  - Frontend authStore (hasFeature)

To add a new feature:
  1. Add the key to ALL_FEATURES below
  2. Add a new Alembic migration that seeds the feature for existing tenants
  3. Add require_feature("your_key") to the relevant router
"""

ALL_FEATURES: list[str] = [
    "opd_queue",           # OPD Queue Dashboard + Token Board
    "appointments",        # Appointment Booking & Calendar
    "vitals",              # Nurse Vitals Capture
    "nurse_roster",        # Nurse Duty Roster & Room Assignment
    "lab",                 # Lab Orders, Result Entry, PDF Upload
    "pharmacy",            # Pharmacy Dispensing Queue
    "billing",             # Invoice Generation, Payments
    "razorpay",            # Online Payment via POS Kiosk
    "whatsapp_sms",        # Twilio SMS/WhatsApp Notifications
    "cloudinary_reports",  # Lab PDF Upload to Cloudinary
]

PLAN_FEATURES: dict[str, list[str]] = {
    "starter": [
        "opd_queue",
        "vitals",
        "appointments",
    ],
    "standard": [
        "opd_queue",
        "vitals",
        "appointments",
        "lab",
        "pharmacy",
        "billing",
    ],
    "enterprise": ALL_FEATURES,
}
