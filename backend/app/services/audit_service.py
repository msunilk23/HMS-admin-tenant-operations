"""Shared domain audit recording with secret-safe snapshots."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.audit_log import AuditLog

_SECRET_KEYS = {
    "password", "password_hash", "secret", "token", "access_token", "refresh_token",
    "api_key", "api_secret", "razorpay_key_secret", "razorpay_webhook_secret",
    "authorization", "x-api-key", "x-razorpay-signature",
}


def sanitize_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SECRET_KEYS else sanitize_audit_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _user_uuid(user_id: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id)) if user_id is not None else None
    except (TypeError, ValueError):
        return None


def record_audit(
    session: AsyncSession,
    *,
    current_user: dict | None,
    action: str,
    resource_type: str,
    resource_id: Any = None,
    old_value: Any = None,
    new_value: Any = None,
    visit_id: Any = None,
    reason: str | None = None,
    request_metadata: dict | None = None,
) -> AuditLog:
    user = current_user or {}
    entry = AuditLog(
        user_id=_user_uuid(user.get("sub")),
        tenant_schema=user.get("tenant_schema"),
        role=user.get("role"),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        visit_id=_user_uuid(visit_id),
        old_value=sanitize_audit_value(old_value),
        new_value=sanitize_audit_value(new_value),
        reason=reason,
        request_metadata=sanitize_audit_value(request_metadata),
    )
    session.add(entry)
    return entry
