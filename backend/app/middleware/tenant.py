"""
TenantMiddleware
================
Resolves the hospital tenant from every incoming request and stores
it in a Python ContextVar so that the DB session can set the correct
PostgreSQL search_path for the duration of that request.

Resolution order:
1. JWT 'tenant_schema' claim  (authenticated API routes)
2. X-Tenant-Schema header     (internal / service-to-service calls)
3. Falls back to 'public'     (unauthenticated routes like /health, /api/v1/auth/login)
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.db.engine import tenant_schema_var
from app.core.security import decode_token


_PUBLIC_PATHS = {
    "/health",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/api/v1/billing/razorpay/webhook",  # Razorpay webhook — no JWT, tenant in payload
}


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        schema = "public"

        # Skip tenant resolution for public paths
        if request.url.path not in _PUBLIC_PATHS and not request.url.path.startswith("/ws"):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                try:
                    payload = decode_token(token)
                    schema = payload.get("tenant_schema", "public")
                except Exception:
                    pass  # Invalid token — let the route handler return 401

            # Allow explicit header override (useful for WebSocket upgrade requests)
            header_schema = request.headers.get("X-Tenant-Schema")
            if header_schema:
                schema = header_schema

        # Sanitise: only allow alphanumeric + underscore to prevent injection
        if not schema.replace("_", "").isalnum():
            schema = "public"

        token_ctx = tenant_schema_var.set(schema)
        try:
            response = await call_next(request)
        finally:
            tenant_schema_var.reset(token_ctx)

        return response
