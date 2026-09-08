from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.core.razorpay_service import verify_webhook_signature
from app.db.engine import AsyncSessionLocal, get_session, tenant_schema_var
from app.integrations.providers import public_provider_catalogue
from app.models.public.tenant_integration import TenantProviderAuditEvent, TenantProviderConnection, TenantProviderCredentialVersion, TenantProviderWebhookRoute
from app.models.public.user import Tenant
from app.models.tenant.invoice import Invoice
from app.services.tenant_integration_service import (
    create_connection,
    disable_connection,
    enable_connection,
    get_audit_history,
    get_razorpay_credentials,
    list_connections,
    rotate_secret,
    submit_secret,
    test_connection,
    update_connection,
)

router = APIRouter()
webhook_router = APIRouter()
logger = logging.getLogger(__name__)


class IntegrationCreateRequest(BaseModel):
    provider_code: str
    environment: str = Field(default="TEST")
    capability: str
    connection_name: str | None = Field(default=None, max_length=128)
    public_configuration: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class IntegrationUpdateRequest(BaseModel):
    environment: str | None = None
    status: str | None = None
    connection_name: str | None = None


class SecretSubmitRequest(BaseModel):
    environment: str = Field(default="TEST")
    credential_type: str
    secret: str | None = Field(default=None, exclude=True)
    credential_version: int | None = None


@router.get("/providers")
async def list_supported_providers(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    return {"providers": public_provider_catalogue()}


@router.get("/connections")
async def list_integration_connections(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    return await list_connections(session=session, tenant_id=tenant_id)


@router.post("/connections")
async def create_integration_connection(
    payload: IntegrationCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    try:
        return await create_connection(session=session, tenant_id=tenant_id, provider=payload.provider_code, environment=payload.environment, capability=payload.capability, connection_name=payload.connection_name, public_configuration=payload.public_configuration, secrets=payload.secrets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/connections/{provider}")
async def update_integration_connection(
    provider: str,
    payload: IntegrationUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    return await update_connection(session=session, tenant_id=tenant_id, provider=provider, environment=payload.environment, status=payload.status, connection_name=payload.connection_name)


@router.post("/connections/{provider}/secret")
async def submit_integration_secret(
    provider: str,
    payload: SecretSubmitRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    if payload.secret is None and payload.credential_version is None:
        raise HTTPException(status_code=400, detail="Secret or credential_version required")
    return await submit_secret(session=session, tenant_id=tenant_id, provider=provider, environment=payload.environment, credential_type=payload.credential_type, secret=payload.secret, credential_version=payload.credential_version)


@router.post("/connections/{provider}/rotate")
async def rotate_integration_secret(
    provider: str,
    payload: SecretSubmitRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    if payload.secret is None:
        raise HTTPException(status_code=400, detail="Secret is required for rotation")
    return await rotate_secret(session=session, tenant_id=tenant_id, provider=provider, environment=payload.environment, credential_type=payload.credential_type, secret=payload.secret)


@router.post("/connections/{provider}/test")
async def test_integration_connection(
    provider: str,
    payload: SecretSubmitRequest | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    return await test_connection(session=session, tenant_id=tenant_id, provider=provider, environment=(payload.environment if payload else "TEST"), credential_type=(payload.credential_type if payload else "default"), secret=(payload.secret if payload else None))


@router.post("/connections/{provider}/enable")
async def enable_integration_connection(
    provider: str,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    return await enable_connection(session=session, tenant_id=tenant_id, provider=provider)


@router.post("/connections/{provider}/disable")
async def disable_integration_connection(
    provider: str,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    return await disable_connection(session=session, tenant_id=tenant_id, provider=provider)


@router.get("/audit")
async def get_integration_audit_history(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    tenant_id = uuid.UUID(str(current_user["tenant_id"]))
    return await get_audit_history(session=session, tenant_id=tenant_id)


@webhook_router.post("/webhooks/razorpay/{integration_endpoint_id}")
async def razorpay_webhook(integration_endpoint_id: str, request: Request):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    async with AsyncSessionLocal() as public_session:
        route = await public_session.scalar(
            select(TenantProviderWebhookRoute).join(
                TenantProviderConnection, TenantProviderWebhookRoute.connection_id == TenantProviderConnection.id
            ).where(
                TenantProviderConnection.endpoint_id == integration_endpoint_id,
                TenantProviderWebhookRoute.provider == "razorpay",
                TenantProviderWebhookRoute.is_active.is_(True),
                TenantProviderConnection.status == "LIVE",
            )
        )
        if route is None:
            raise HTTPException(status_code=404, detail="Integration endpoint not found")
        connection = await public_session.get(TenantProviderConnection, route.connection_id)
        try:
            _, secrets, _ = await get_razorpay_credentials(
                session=public_session, tenant_id=route.tenant_id, environment=route.environment
            )
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Webhook integration is not configured") from None
        if not verify_webhook_signature(body, signature, secrets.get("webhook_secret")):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
        try:
            event_data = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON") from None
        payment = event_data.get("payload", {}).get("payment", {}).get("entity", {})
        order = event_data.get("payload", {}).get("order", {}).get("entity", {})
        order_id = payment.get("order_id") or order.get("id")
        payment_id = payment.get("id")
        if event_data.get("event") not in {"payment.captured", "payment.authorized"}:
            return {"status": "ignored"}
        if not order_id or not payment_id:
            raise HTTPException(status_code=400, detail="Webhook payment identity is missing")
        tenant = await public_session.get(Tenant, route.tenant_id)
        if tenant is None or not tenant.is_active:
            raise HTTPException(status_code=400, detail="Webhook tenant is inactive")
        await public_session.commit()

    token = tenant_schema_var.set(tenant.schema_name)
    try:
        async with AsyncSessionLocal() as tenant_session:
            await tenant_session.execute(__import__("sqlalchemy").text(f'SET search_path TO "{tenant.schema_name}", public'))
            invoice = await tenant_session.scalar(select(Invoice).where(Invoice.razorpay_order_id == order_id).with_for_update())
            if invoice is None:
                raise HTTPException(status_code=400, detail="Webhook order is not linked to an invoice")
            if invoice.razorpay_payment_id == payment_id or invoice.status == "paid":
                return {"status": "idempotent"}
            if invoice.status in {"cancelled", "refunded"}:
                raise HTTPException(status_code=409, detail="Invoice cannot accept webhook payment")
            invoice.razorpay_payment_id = payment_id
            invoice.payment_method = str(payment.get("method") or "razorpay")
            invoice.status = "paid"
            from datetime import datetime, timezone
            invoice.paid_at = datetime.now(timezone.utc)
            tenant_session.add(TenantProviderAuditEvent(tenant_id=route.tenant_id, provider="razorpay", capability=connection.capability, environment=connection.environment, event_type="webhook_payment_processed", result="SUCCESS", event_metadata={"order_id": str(order_id), "payment_id": str(payment_id), "event": str(event_data.get("event"))}))
            await tenant_session.commit()
            logger.info("Processed Razorpay webhook endpoint=%s event=%s", integration_endpoint_id, event_data.get("event"))
            return {"status": "processed"}
    finally:
        tenant_schema_var.reset(token)


@router.get("/webhooks/twilio/{integration_endpoint_id}")
async def twilio_webhook_placeholder(integration_endpoint_id: str):
    raise HTTPException(status_code=404, detail="Twilio webhook integration not implemented in this scaffold")
