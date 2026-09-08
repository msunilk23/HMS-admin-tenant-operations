from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.integrations.providers import public_provider_catalogue
from app.models.public.tenant_integration import TenantProviderConnection, TenantProviderCredentialVersion, TenantProviderAuditEvent
from app.services.tenant_integration_service import (
    create_connection,
    disable_connection,
    enable_connection,
    get_audit_history,
    list_connections,
    rotate_secret,
    submit_secret,
    test_connection,
    update_connection,
)

router = APIRouter()


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


@router.get("/webhooks/razorpay/{integration_endpoint_id}")
async def razorpay_webhook_placeholder(integration_endpoint_id: str):
    raise HTTPException(status_code=404, detail="Razorpay webhook integration not implemented in this scaffold")


@router.get("/webhooks/twilio/{integration_endpoint_id}")
async def twilio_webhook_placeholder(integration_endpoint_id: str):
    raise HTTPException(status_code=404, detail="Twilio webhook integration not implemented in this scaffold")
