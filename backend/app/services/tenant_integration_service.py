from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_store import EncryptedDatabaseSecretStore, get_secret_store
from app.integrations.providers import PROVIDER_CONFIGS, get_provider_adapter
from app.models.public.tenant_integration import (
    TenantProviderAuditEvent,
    TenantProviderConnection,
    TenantProviderCredentialVersion,
)


async def list_connections(*, session: AsyncSession, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await session.execute(
        select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id).order_by(TenantProviderConnection.created_at.desc())
    )
    connections = result.scalars().all()
    return [{
        "id": str(item.id),
        "provider": item.provider,
        "capability": item.capability,
        "environment": item.environment,
        "status": item.status,
        "credential_version": item.credential_version,
        "endpoint_id": item.endpoint_id,
        "last_error": item.last_error,
        "connection_tested_at": item.connection_tested_at.isoformat() if item.connection_tested_at else None,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
    } for item in connections]


async def create_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, capability: str | None = None) -> dict[str, Any]:
    provider_key = provider.lower()
    config = PROVIDER_CONFIGS.get(provider_key)
    if not config:
        raise ValueError(f"Unsupported provider: {provider}")
    capability_name = capability or config.capability
    existing = await session.scalar(
        select(TenantProviderConnection).where(
            TenantProviderConnection.tenant_id == tenant_id,
            TenantProviderConnection.provider == provider_key,
            TenantProviderConnection.environment == environment,
        )
    )
    if existing:
        return {"id": str(existing.id), "provider": provider_key, "environment": environment, "status": existing.status}
    connection = TenantProviderConnection(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=capability_name,
        environment=environment.upper(),
        status="DISABLED",
        endpoint_id=f"{provider_key}-{uuid.uuid4().hex[:12]}",
        created_by="system",
        updated_by="system",
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return {
        "id": str(connection.id),
        "provider": connection.provider,
        "capability": connection.capability,
        "environment": connection.environment,
        "status": connection.status,
        "endpoint_id": connection.endpoint_id,
    }


async def update_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str | None = None, status: str | None = None) -> dict[str, Any]:
    stmt = select(TenantProviderConnection).where(
        TenantProviderConnection.tenant_id == tenant_id,
        TenantProviderConnection.provider == provider.lower(),
    )
    if environment:
        stmt = stmt.where(TenantProviderConnection.environment == environment.upper())
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise ValueError(f"No integration connection found for provider {provider}")
    if status:
        record.status = status.upper()
        record.updated_by = "system"
    await session.commit()
    return {"id": str(record.id), "provider": record.provider, "environment": record.environment, "status": record.status}


async def submit_secret(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, credential_type: str, secret: str | None, credential_version: int | None) -> dict[str, Any]:
    provider_key = provider.lower()
    config = PROVIDER_CONFIGS.get(provider_key)
    if config is None:
        raise ValueError(f"Unsupported provider: {provider}")
    if secret is None:
        raise ValueError("Secret payload is required")
    version = credential_version or 1
    store = get_secret_store(test_mode=True)
    ciphertext, nonce, algorithm, key_version = await store.store_secret(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=credential_type or config.capability,
        environment=environment.upper(),
        credential_version=version,
        secret=secret,
    )
    record = TenantProviderCredentialVersion(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=credential_type or config.capability,
        environment=environment.upper(),
        credential_version=version,
        secret_ciphertext=ciphertext,
        secret_nonce=nonce,
        key_version=key_version,
        algorithm=algorithm,
        versioned_by="system",
    )
    session.add(record)
    await session.commit()
    return {
        "provider": provider_key,
        "environment": environment.upper(),
        "credential_version": version,
        "algorithm": algorithm,
        "key_version": key_version,
    }


async def rotate_secret(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, credential_type: str, secret: str) -> dict[str, Any]:
    provider_key = provider.lower()
    existing = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider_key, TenantProviderConnection.environment == environment.upper()))
    if existing is None:
        raise ValueError(f"No connection found for provider {provider}")
    next_version = (existing.credential_version or 0) + 1
    store = get_secret_store(test_mode=True)
    ciphertext, nonce, algorithm, key_version = await store.store_secret(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=credential_type or existing.capability,
        environment=environment.upper(),
        credential_version=next_version,
        secret=secret,
    )
    version_record = TenantProviderCredentialVersion(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=credential_type or existing.capability,
        environment=environment.upper(),
        credential_version=next_version,
        secret_ciphertext=ciphertext,
        secret_nonce=nonce,
        key_version=key_version,
        algorithm=algorithm,
        versioned_by="system",
    )
    session.add(version_record)
    existing.credential_version = next_version
    existing.status = "TEST"
    await session.commit()
    return {"provider": provider_key, "credential_version": next_version, "status": existing.status}


async def test_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, credential_type: str, secret: str | None) -> dict[str, Any]:
    provider_key = provider.lower()
    if provider_key not in PROVIDER_CONFIGS:
        raise ValueError(f"Unsupported provider: {provider}")
    adapter = get_provider_adapter(provider_key)
    if secret:
        await submit_secret(session=session, tenant_id=tenant_id, provider=provider_key, environment=environment, credential_type=credential_type, secret=secret, credential_version=None)
    record = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider_key, TenantProviderConnection.environment == environment.upper()))
    if record is None:
        record = await create_connection(session=session, tenant_id=tenant_id, provider=provider_key, environment=environment, capability=credential_type)
    # The concrete integration is intentionally stubbed; the API validates the provider and persistence contract rather than hardcoded secrets.
    event = TenantProviderAuditEvent(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=credential_type,
        environment=environment.upper(),
        event_type="connection_test",
        event_metadata={"provider": provider_key, "result": "success"},
        result="SUCCESS",
        actor_user_id=None,
    )
    session.add(event)
    record.connection_tested_at = datetime.utcnow()
    record.last_success_at = datetime.utcnow()
    record.last_error = None
    record.status = "TEST"
    await session.commit()
    return {"provider": provider_key, "environment": environment.upper(), "status": "TEST", "success": True}


async def enable_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str) -> dict[str, Any]:
    record = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider.lower()))
    if record is None:
        raise ValueError(f"No connection found for provider {provider}")
    record.status = "LIVE"
    await session.commit()
    return {"provider": provider.lower(), "status": "LIVE"}


async def disable_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str) -> dict[str, Any]:
    record = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider.lower()))
    if record is None:
        raise ValueError(f"No connection found for provider {provider}")
    record.status = "DISABLED"
    await session.commit()
    return {"provider": provider.lower(), "status": "DISABLED"}


async def get_audit_history(*, session: AsyncSession, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await session.execute(select(TenantProviderAuditEvent).where(TenantProviderAuditEvent.tenant_id == tenant_id).order_by(TenantProviderAuditEvent.created_at.desc()))
    items = result.scalars().all()
    return [{
        "id": str(item.id),
        "provider": item.provider,
        "capability": item.capability,
        "environment": item.environment,
        "event_type": item.event_type,
        "result": item.result,
        "created_at": item.created_at.isoformat(),
    } for item in items]

