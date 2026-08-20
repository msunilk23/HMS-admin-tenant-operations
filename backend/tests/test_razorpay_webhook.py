import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

from app.api.v1.billing import _extract_razorpay_context


def test_extracts_tenant_from_order_notes():
    event = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_123",
                    "order_id": "order_test_456",
                    "method": "card",
                }
            },
            "order": {
                "entity": {
                    "id": "order_test_456",
                    "notes": {
                        "tenant_schema": "shankar",
                        "source": "pharmacy",
                    },
                }
            },
        },
    }

    result = _extract_razorpay_context(event)

    assert result["order_id"] == "order_test_456"
    assert result["payment_id"] == "pay_test_123"
    assert result["payment_method"] == "card"
    assert result["tenant_schema"] == "shankar"
    assert result["order_notes"] == {"tenant_schema": "shankar", "source": "pharmacy"}
    assert result["payment_notes"] == {}
    assert result["tenant_conflict"] is False


def test_extracts_tenant_from_payment_notes_fallback():
    event = {
        "event": "payment.authorized",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_999",
                    "order_id": "order_test_111",
                    "method": "upi",
                    "notes": {"tenant_schema": "apollo"},
                }
            }
        },
    }

    result = _extract_razorpay_context(event)

    assert result["tenant_schema"] == "apollo"
    assert result["order_id"] == "order_test_111"
    assert result["payment_method"] == "upi"


def test_missing_tenant_in_both_notes_is_rejected_safely():
    event = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_missing",
                    "order_id": "order_test_missing",
                    "method": "card",
                }
            }
        },
    }

    result = _extract_razorpay_context(event)

    assert result["tenant_schema"] == ""
    assert result["tenant_conflict"] is False


def test_order_tenant_wins_over_payment_tenant_conflict():
    event = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_777",
                    "order_id": "order_test_777",
                    "method": "card",
                    "notes": {"tenant_schema": "apollo"},
                }
            },
            "order": {
                "entity": {
                    "id": "order_test_777",
                    "notes": {"tenant_schema": "shankar"},
                }
            },
        },
    }

    result = _extract_razorpay_context(event)

    assert result["tenant_schema"] == "shankar"
    assert result["tenant_conflict"] is True
