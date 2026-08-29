import hashlib
import hmac
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("SECRET_KEY", "phase14-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "webhook-secret"

from app.core.razorpay_service import verify_webhook_signature
from app.models.tenant.invoice import invoice_status_for_payment
from app.api.v1.billing import _authorize_linked_pharmacy_dispense


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


@pytest.mark.asyncio
async def test_pharmacy_handoff_is_noop_for_non_pharmacy_invoice():
    class Session:
        async def get(self, *_args):
            raise AssertionError("non-pharmacy invoices must not load a dispense")

    invoice = SimpleNamespace(status="paid", pharmacy_dispense_id=None)
    await _authorize_linked_pharmacy_dispense(invoice, Session())


@pytest.mark.asyncio
async def test_pharmacy_handoff_calls_confirmation_for_paid_linked_invoice(monkeypatch):
    dispense_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    confirmed_by = uuid.uuid4()
    dispense = SimpleNamespace(id=dispense_id, tenant_id=tenant_id, facility_id=facility_id, patient_id=uuid.uuid4(), visit_id=uuid.uuid4(), status="READY_FOR_BILLING", billing_status="PENDING")

    class Session:
        async def get(self, model, requested_id):
            assert requested_id == dispense_id
            return dispense

        def add(self, _entry):
            return None

    captured = {}

    async def confirm(_session, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.api.v1.billing.confirm_dispense_stock_consumption", confirm)
    invoice = SimpleNamespace(id=uuid.uuid4(), status="paid", pharmacy_dispense_id=dispense_id)
    await _authorize_linked_pharmacy_dispense(invoice, Session(), confirmed_by=confirmed_by)

    assert captured == {
        "dispense_id": dispense_id,
        "tenant_id": tenant_id,
        "facility_id": facility_id,
        "confirmed_by": confirmed_by,
        "billing_authorized": True,
    }