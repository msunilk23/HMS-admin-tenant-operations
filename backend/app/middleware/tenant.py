"""
TenantMiddleware
================
Resolves the hospital tenant from every incoming authenticated request and
stores it in a Python ContextVar so that the DB session can set the correct
PostgreSQL search_path for the duration of that request.

Security model (authoritative — do not weaken):
  - The signed JWT is the ONLY source of tenant identity for normal requests.
  - There is no client-supplied header/query/cookie override. A browser or
    any other caller can never switch tenant context by sending
    'X-Tenant-Schema' or similar; that mechanism has been removed entirely.
  - For every tenant-role JWT, the (tenant_id, tenant_schema) claim pair is
    revalidated against PostgreSQL (via a short-lived Redis cache) on every
    request. A mismatched, unknown, or deactivated tenant is rejected with a
    hard 403 — the request never reaches the route handler and never falls
    back to the 'public' schema.
  - super_admin JWTs never carry a tenant_schema/tenant_id and are always
    confined to the 'public' schema at this layer; tenant-route access for
    super_admin is additionally denied by `require_tenant_user`.
  - Public routes (health, login, refresh, docs, approved webhooks) are
    explicitly allow-listed and never touch tenant context.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db.engine import tenant_schema_var
from app.core.security import decode_token
from app.core.redis_client import get_cached_tenant_status, set_cached_tenant_status


_PUBLIC_PATHS = {
    "/health",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/api/v1/billing/razorpay/webhook",  # Razorpay webhook — no JWT, tenant in payload
}


def _is_valid_schema_name(schema: str) -> bool:
    return bool(schema) and schema.replace("_", "").isalnum()


async def _load_tenant_status(tenant_id: str) -> dict | None:
    """Return {"schema_name", "is_active"} for tenant_id, using Redis then PostgreSQL."""
    cached = await get_cached_tenant_status(tenant_id)
    if cached is not None:
        return cached

    # Import locally to avoid a hard dependency cycle at module import time.
    import uuid as _uuid
    from sqlalchemy import select
    from app.db.engine import AsyncSessionLocal
    from app.models.public.user import Tenant

    try:
        tenant_uuid = _uuid.UUID(str(tenant_id))
    except (TypeError, ValueError):
        return None

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(Tenant.schema_name, Tenant.is_active).where(Tenant.id == tenant_uuid)
            )
        ).first()

    if row is None:
        return None

    status_dict = {"schema_name": row[0], "is_active": bool(row[1])}
    await set_cached_tenant_status(tenant_id, row[0], bool(row[1]))
    return status_dict


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Public / unauthenticated routes always resolve to 'public' and skip
        # JWT-based tenant resolution entirely.
        if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/ws"):
            token_ctx = tenant_schema_var.set("public")
            try:
                return await call_next(request)
            finally:
                tenant_schema_var.reset(token_ctx)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # No credentials — let the route's own auth dependency return 401.
            # Tenant context stays 'public'; no tenant data can be reached
            # because every non-public route requires an authenticated user.
            token_ctx = tenant_schema_var.set("public")
            try:
                return await call_next(request)
            finally:
                tenant_schema_var.reset(token_ctx)

        try:
            payload = decode_token(auth_header[7:])
        except Exception:
            # Invalid/expired token — let the route's auth dependency return 401.
            token_ctx = tenant_schema_var.set("public")
            try:
                return await call_next(request)
            finally:
                tenant_schema_var.reset(token_ctx)

        role = payload.get("role")

        if role == "super_admin":
            # Platform operator — never bound to a tenant schema.
            schema = "public"
        else:
            tenant_id = payload.get("tenant_id")
            claimed_schema = payload.get("tenant_schema", "")

            if not tenant_id or not _is_valid_schema_name(claimed_schema):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid tenant context."},
                )

            tenant_status = await _load_tenant_status(str(tenant_id))
            if (
                tenant_status is None
                or not tenant_status["is_active"]
                or tenant_status["schema_name"] != claimed_schema
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid or inactive tenant context."},
                )

            schema = claimed_schema

        token_ctx = tenant_schema_var.set(schema)
        try:
            response = await call_next(request)
        finally:
            tenant_schema_var.reset(token_ctx)

        return response

