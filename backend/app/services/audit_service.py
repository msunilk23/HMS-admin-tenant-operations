"""Shared domain audit recording with secret-safe snapshots."""

import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.audit_log import AuditLog

_REQUEST_ID: ContextVar[str | None] = ContextVar("audit_request_id", default=None)
_SOURCE_IP: ContextVar[str | None] = ContextVar("audit_source_ip", default=None)


def set_audit_request_context(request_id: str, source_ip: str | None):
    return (
        _REQUEST_ID.set(request_id),
        _SOURCE_IP.set(source_ip),
    )


def reset_audit_request_context(tokens) -> None:
    _REQUEST_ID.reset(tokens[0])
    _SOURCE_IP.reset(tokens[1])


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(term in normalized for term in (
        "password", "secret", "token", "jwt", "authorization", "api_key",
        "signature", "aadhaar", "aadhar", "cvv", "card_number", "pan_number",
    ))


def sanitize_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else sanitize_audit_value(item)
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
    patient_id: Any = None,
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
        patient_id=_user_uuid(patient_id),
        visit_id=_user_uuid(visit_id),
        request_id=_REQUEST_ID.get(),
        source_ip=_SOURCE_IP.get(),
        old_value=sanitize_audit_value(old_value),
        new_value=sanitize_audit_value(new_value),
        reason=reason,
        request_metadata=sanitize_audit_value(request_metadata),
    )
    session.add(entry)
    return entry
