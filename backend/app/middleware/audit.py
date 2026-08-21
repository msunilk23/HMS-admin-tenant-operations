"""
Audit log middleware — writes an entry to public.audit_log for every
mutating request (POST / PUT / PATCH / DELETE) once a response is returned.
Read operations (GET, HEAD, OPTIONS) are not logged.

The write is fire-and-forget via asyncio.create_task so it never delays
the response. Failures are silently swallowed to keep the middleware
non-blocking.
"""

import asyncio
import logging
import uuid
from jose import JWTError

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


async def _write_audit_entry(
    tenant_schema: str,
    user_id: str | None,
    method: str,
    path: str,
    status_code: int,
    ip_address: str | None,
    role: str | None,
    request_id: str,
    request_metadata: dict,
) -> None:
    """Background task: open a fresh DB connection and persist the log row."""
    try:
        from sqlalchemy import text
        from app.db.engine import AsyncSessionLocal
        from app.models.public.audit_log import AuditLog
        from app.services.audit_service import sanitize_audit_value

        uid = uuid.UUID(user_id) if user_id else None

        async with AsyncSessionLocal() as session:
            # Use public schema for the audit log regardless of tenant
            await session.execute(text('SET search_path TO public'))
            session.add(AuditLog(
                tenant_schema=tenant_schema,
                user_id=uid,
                role=role,
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                ip_address=ip_address,
                request_metadata=sanitize_audit_value(request_metadata),
            ))
            await session.commit()
    except Exception:
        logger.debug("audit_log write failed (non-critical)", exc_info=True)


class AuditLogMiddleware(BaseHTTPMiddleware):
    _MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
        from app.services.audit_service import set_audit_request_context, reset_audit_request_context
        context_tokens = set_audit_request_context(request_id, ip_address)
        try:
            response = await call_next(request)
        finally:
            reset_audit_request_context(context_tokens)

        if request.method not in self._MUTATING_METHODS or response.status_code >= 500:
            return response

        # Extract user_id from JWT (best-effort — no error if absent)
        user_id: str | None = None
        role: str | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.core.security import decode_token
                payload = decode_token(auth_header[7:])
                user_id = payload.get("sub")
                role = payload.get("role")
            except JWTError:
                pass

        # Tenant schema is set by TenantMiddleware via ContextVar
        from app.db.engine import tenant_schema_var
        tenant_schema = tenant_schema_var.get()

        # Client IP — respect X-Forwarded-For set by nginx
        request_metadata = {
            "query": request.url.query,
            "user_agent": request.headers.get("User-Agent"),
        }

        asyncio.create_task(
            _write_audit_entry(
                tenant_schema=tenant_schema,
                user_id=user_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                ip_address=ip_address,
                role=role,
                request_id=request_id,
                request_metadata=request_metadata,
            )
        )

        return response
