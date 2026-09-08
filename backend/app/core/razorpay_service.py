"""
Razorpay integration helpers.

create_razorpay_order  — creates an order via Razorpay REST API
verify_webhook_signature — validates the X-Razorpay-Signature header
"""

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def create_razorpay_order(
    *,
    amount_rupees: float,
    receipt: str,
    key_id: str | None = None,
    key_secret: str | None = None,
    notes: dict | None = None,
) -> dict | None:
    """
    Create a Razorpay order.

    Returns the full order dict on success (notably order["id"] and order["amount"]).
    Returns None if Razorpay is not configured or on any error.
    All errors are logged and swallowed — callers must handle None gracefully.
    """
    if not (key_id and key_secret):
        logger.warning("Razorpay not configured — skipping order creation.")
        return None
    try:
        import razorpay  # lazy — package optional

        client = razorpay.Client(auth=(key_id, key_secret))
        amount_paise = int(round(amount_rupees * 100))  # Razorpay amounts are in paise
        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt[:40],    # Razorpay caps receipt at 40 chars
            "payment_capture": True,    # auto-capture on successful payment
            "notes": notes or {},
        })
        logger.info("Razorpay order created: %s for ₹%.2f", order["id"], amount_rupees)
        return order
    except Exception:
        logger.exception("Failed to create Razorpay order")
        return None


def fetch_order_payments(*, order_id: str, key_id: str | None = None, key_secret: str | None = None) -> dict | None:
    """
    Fetch the captured/authorized payments for a Razorpay order via the Razorpay API.

    Returns the first successful payment entity dict, or None if not found / not configured.
    Used as a fallback when the webhook was missed (ngrok down, URL stale, etc.).
    """
    if not (key_id and key_secret):
        return None

    try:
        import razorpay

        client = razorpay.Client(auth=(key_id, key_secret))
        response = client.order.payments(order_id)
        for item in response.get("items", []):
            if item.get("status") in ("captured", "authorized"):
                return item
        return None
    except Exception:
        logger.exception("Failed to fetch Razorpay order payments for %s", order_id)
        return None


def verify_webhook_signature(body: bytes, signature: str | None, webhook_secret: str | None) -> bool:
    """
    Verify the X-Razorpay-Signature HMAC-SHA256 header.

    Returns True if the signature is valid.
    The tenant-resolved webhook secret and signature are mandatory.
    """
    if not webhook_secret or not signature:
        return False

    expected = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
