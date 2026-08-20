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
    notes: dict | None = None,
) -> dict | None:
    """
    Create a Razorpay order.

    Returns the full order dict on success (notably order["id"] and order["amount"]).
    Returns None if Razorpay is not configured or on any error.
    All errors are logged and swallowed — callers must handle None gracefully.
    """
    from app.core.config import settings  # lazy to avoid circular imports at startup

    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
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


def fetch_order_payments(order_id: str) -> dict | None:
    """
    Fetch the captured/authorized payments for a Razorpay order via the Razorpay API.

    Returns the first successful payment entity dict, or None if not found / not configured.
    Used as a fallback when the webhook was missed (ngrok down, URL stale, etc.).
    """
    from app.core.config import settings

    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
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


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify the X-Razorpay-Signature HMAC-SHA256 header.

    Returns True if the signature is valid.
    A configured webhook secret is mandatory. Unsigned webhooks are rejected.
    """
    from app.core.config import settings

    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET not set — rejecting webhook")
        return False

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
