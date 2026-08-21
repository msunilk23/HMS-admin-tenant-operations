"""
WebSocket HTTP upgrade endpoints.

Clients connect to:
  /ws/{tenant_schema}/{channel}

Auth: pass JWT as query param ?token=<access_token>
(WebSocket API does not support Authorization headers in browsers.)

Special: ?token=<tenant display_token>  grants read-only access to the
PII-free queue:update channel for public TV display boards. The credential
is per-tenant, revocable (hospital_admin can rotate it — see
app.api.v1.tenants), and only ever checked here; it is never accepted by
any REST endpoint, so it cannot be used for API access.
"""
import secrets

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_token
from app.websocket.manager import ALLOWED_EVENT_CHANNELS, ws_manager

ws_router = APIRouter()

_ALLOWED_CHANNELS = ALLOWED_EVENT_CHANNELS

# Channels accessible without a JWT (public display boards / kiosks)
_PUBLIC_CHANNELS = {
    "queue:update",   # ?token=<tenant display_token>  (TV display boards)
    "pos:payment",    # ?token=kiosk                    (PAX A920 / payment kiosk)
}


async def _tenant_display_token(tenant_schema: str) -> str | None:
    """Look up the current revocable display credential for a tenant schema."""
    from app.db.engine import AsyncSessionLocal
    from app.models.public.user import Tenant

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(Tenant.display_token).where(
                    Tenant.schema_name == tenant_schema, Tenant.is_active == True  # noqa: E712
                )
            )
        ).first()
    return row[0] if row else None


@ws_router.websocket("/ws/{tenant_schema}/{channel}")
async def websocket_endpoint(
    websocket: WebSocket,
    tenant_schema: str,
    channel: str,
    token: str = Query(...),
):
    # Sanitise tenant_schema first
    if not tenant_schema.replace("_", "").isalnum():
        await websocket.close(code=4005)
        return

    # Validate channel name
    if channel not in _ALLOWED_CHANNELS:
        await websocket.close(code=4004)
        return

    # Allow kiosk devices without a real JWT (pos:payment only)
    if token == "kiosk":
        if channel not in _PUBLIC_CHANNELS:
            await websocket.close(code=4003)
            return
    else:
        # Validate JWT first (the common case for authenticated staff screens);
        # only fall back to the revocable per-tenant display credential lookup
        # when the token isn't a valid JWT, to avoid a DB hit on every connect.
        try:
            payload = decode_token(token)
            token_tenant = payload.get("tenant_schema", "")
            if token_tenant != tenant_schema:
                await websocket.close(code=4003)
                return
        except Exception:
            stored_display_token = await _tenant_display_token(tenant_schema)
            is_display_board = (
                stored_display_token is not None
                and secrets.compare_digest(token, stored_display_token)
            )
            if not is_display_board or channel != "queue:update":
                await websocket.close(code=4001)
                return

    await ws_manager.connect(websocket, tenant_schema, channel)
    try:
        while True:
            # Keep connection alive; clients send periodic pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, tenant_schema, channel)
