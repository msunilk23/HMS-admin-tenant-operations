import hashlib
import hmac
import os

import pytest

os.environ.setdefault("SECRET_KEY", "phase14-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "webhook-secret"

from app.core.razorpay_service import verify_webhook_signature
from app.models.tenant.invoice import invoice_status_for_payment


@pytest.mark.parametrize(
    ("total", "paid", "expected"),
    [
        (1000, 0, "pending"),
        (1000, 250, "partially_paid"),
        (1000, 1000, "paid"),
    ],
)
def test_invoice_payment_statuses(total, paid, expected):
    assert invoice_status_for_payment(total, paid) == expected


def test_webhook_signature_requires_matching_secret():
    body = b'{"event":"payment.captured"}'
    signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, signature)
    assert not verify_webhook_signature(body, "invalid")