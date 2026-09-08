from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_store import SecretStore, get_secret_store
from app.integrations.providers import PROVIDER_CONFIGS, get_provider_adapter, validate_provider_configuration
from app.models.public.tenant_integration import (
    TenantProviderAuditEvent,
    TenantProviderConnection,
    TenantProviderCredentialVersion,
    TenantProviderWebhookRoute,
)


async def _audit_event(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, capability: str, environment: str, event_type: str, result: str, metadata: dict[str, Any] | None = None) -> None:
    event = TenantProviderAuditEvent(
        tenant_id=tenant_id,
        provider=provider.lower(),
        capability=capability,
        environment=environment.upper(),
        event_type=event_type,
        event_metadata={k: v for k, v in (metadata or {}).items() if v is not None},
        result=result,
        actor_user_id=None,
    )
    session.add(event)


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
        "connection_name": item.connection_name,
        "public_configuration": item.public_configuration,
        "status": item.status,
        "credential_version": item.credential_version,
        "endpoint_id": item.endpoint_id,
        "last_error": item.last_error,
        "connection_tested_at": item.connection_tested_at.isoformat() if item.connection_tested_at else None,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
    } for item in connections]


async def create_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, capability: str | None = None, connection_name: str | None = None, public_configuration: dict[str, str] | None = None, secrets: dict[str, str] | None = None, secret_store: SecretStore | None = None) -> dict[str, Any]:
    provider_key = provider.lower()
    public_configuration = public_configuration or {}
    secrets = secrets or {}
    config = validate_provider_configuration(provider_code=provider_key, capability=capability or "", environment=environment, public_configuration=public_configuration, secrets=secrets)
    capability_name = config.capability
    record = await session.scalar(
        select(TenantProviderConnection).where(
            TenantProviderConnection.tenant_id == tenant_id,
            TenantProviderConnection.provider == provider_key,
            TenantProviderConnection.environment == environment.upper(),
        )
    )
    if record is not None:
        return {"id": str(record.id), "provider": record.provider, "environment": record.environment, "status": record.status}
    record = TenantProviderConnection(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=capability_name,
        environment=environment.upper(),
        status="DISABLED",
        connection_name=connection_name.strip() if connection_name else None,
        public_configuration=public_configuration,
        endpoint_id=f"{provider_key}-{uuid.uuid4().hex[:12]}",
        created_by="system",
        updated_by="system",
    )
    session.add(record)
    session.add(TenantProviderWebhookRoute(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=capability_name,
        environment=environment.upper(),
        connection_id=record.id,
    ))
    if secrets:
        ciphertext, nonce, algorithm, key_version = await (secret_store or get_secret_store()).store_secret(
            tenant_id=tenant_id, provider=provider_key, capability=capability_name,
            environment=environment.upper(), credential_version=record.credential_version,
            secret=json.dumps(secrets, sort_keys=True),
        )
        session.add(TenantProviderCredentialVersion(
            tenant_id=tenant_id, provider=provider_key, capability=capability_name,
            environment=environment.upper(), credential_version=record.credential_version,
            secret_ciphertext=ciphertext, secret_nonce=nonce, algorithm=algorithm,
            key_version=key_version, versioned_by="system",
        ))
    await _audit_event(session=session, tenant_id=tenant_id, provider=provider_key, capability=capability_name, environment=environment.upper(), event_type="connection_created", result="SUCCESS", metadata={"endpoint_id": record.endpoint_id})
    await session.commit()
    await session.refresh(record)
    return {
        "id": str(record.id),
        "provider": record.provider,
        "capability": record.capability,
        "environment": record.environment,
        "connection_name": record.connection_name,
        "public_configuration": record.public_configuration,
        "status": record.status,
        "endpoint_id": record.endpoint_id,
    }


async def update_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str | None = None, status: str | None = None, connection_name: str | None = None) -> dict[str, Any]:
    stmt = select(TenantProviderConnection).where(
        TenantProviderConnection.tenant_id == tenant_id,
        TenantProviderConnection.provider == provider.lower(),
    )
    if environment:
        stmt = stmt.where(TenantProviderConnection.environment == environment.upper())
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise ValueError(f"No integration connection found for provider {provider}")
    previous_status = record.status
    if status:
        record.status = status.upper()
        record.updated_by = "system"
    if connection_name is not None:
        record.connection_name = connection_name.strip() or None
    await _audit_event(session=session, tenant_id=tenant_id, provider=record.provider, capability=record.capability, environment=record.environment, event_type="connection_updated", result="SUCCESS", metadata={"previous_status": previous_status, "new_status": record.status})
    await session.commit()
    return {"id": str(record.id), "provider": record.provider, "environment": record.environment, "connection_name": record.connection_name, "status": record.status}


async def submit_secret(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, credential_type: str, secret: str | None, credential_version: int | None, secret_store: SecretStore | None = None) -> dict[str, Any]:
    provider_key = provider.lower()
    config = PROVIDER_CONFIGS.get(provider_key)
    if config is None:
        raise ValueError(f"Unsupported provider: {provider}")
    if secret is None:
        raise ValueError("Secret payload is required")
    version = credential_version or 1
    store = secret_store or get_secret_store()
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
    await _audit_event(session=session, tenant_id=tenant_id, provider=provider_key, capability=credential_type or config.capability, environment=environment.upper(), event_type="secret_updated", result="SUCCESS", metadata={"credential_version": version, "algorithm": algorithm})
    await session.commit()
    return {
        "provider": provider_key,
        "environment": environment.upper(),
        "credential_version": version,
        "algorithm": algorithm,
        "key_version": key_version,
    }


async def rotate_secret(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, credential_type: str, secret: str, secret_store: SecretStore | None = None) -> dict[str, Any]:
    provider_key = provider.lower()
    existing = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider_key, TenantProviderConnection.environment == environment.upper()))
    if existing is None:
        raise ValueError(f"No connection found for provider {provider}")
    next_version = (existing.credential_version or 0) + 1
    store = secret_store or get_secret_store()
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
    store.invalidate_cache(tenant_id=tenant_id, provider=provider_key, environment=environment.upper())
    await _audit_event(session=session, tenant_id=tenant_id, provider=provider_key, capability=credential_type or existing.capability, environment=environment.upper(), event_type="secret_rotated", result="SUCCESS", metadata={"previous_version": next_version - 1, "new_version": next_version})
    await session.commit()
    return {"provider": provider_key, "credential_version": next_version, "status": existing.status}


async def get_persisted_secret(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, capability: str, environment: str, credential_version: int, secret_store: SecretStore | None = None) -> str:
    provider_key = provider.lower()
    environment_key = environment.upper()
    version = await session.scalar(
        select(TenantProviderCredentialVersion).where(
            TenantProviderCredentialVersion.tenant_id == tenant_id,
            TenantProviderCredentialVersion.provider == provider_key,
            TenantProviderCredentialVersion.capability == capability,
            TenantProviderCredentialVersion.environment == environment_key,
            TenantProviderCredentialVersion.credential_version == credential_version,
        )
    )
    if version is None:
        raise KeyError("Credential version does not exist for this tenant integration")
    return await (secret_store or get_secret_store()).decrypt_secret(
        tenant_id=tenant_id,
        provider=provider_key,
        capability=capability,
        environment=environment_key,
        credential_version=credential_version,
        ciphertext=version.secret_ciphertext,
        nonce=version.secret_nonce,
    )


async def get_razorpay_credentials(*, session: AsyncSession, tenant_id: uuid.UUID, environment: str = "LIVE") -> tuple[str, dict[str, str], TenantProviderConnection]:
    connection = await session.scalar(
        select(TenantProviderConnection).where(
            TenantProviderConnection.tenant_id == tenant_id,
            TenantProviderConnection.provider == "razorpay",
            TenantProviderConnection.capability == "payment",
            TenantProviderConnection.environment == environment.upper(),
            TenantProviderConnection.status == "LIVE",
        )
    )
    if connection is None:
        raise ValueError("Active Razorpay integration is not configured")
    key_id = str(connection.public_configuration.get("key_id", ""))
    if not key_id:
        raise ValueError("Razorpay key ID is not configured")
    decrypted = await get_persisted_secret(
        session=session, tenant_id=tenant_id, provider="razorpay", capability="payment",
        environment=connection.environment, credential_version=connection.credential_version,
    )
    try:
        secrets = json.loads(decrypted)
    except json.JSONDecodeError as exc:
        raise ValueError("Razorpay credential record is invalid") from exc
    if not isinstance(secrets, dict):
        raise ValueError("Razorpay credential record is invalid")
    return key_id, {str(key): str(value) for key, value in secrets.items()}, connection


async def test_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str, environment: str, credential_type: str, secret: str | None) -> dict[str, Any]:
    provider_key = provider.lower()
    if provider_key not in PROVIDER_CONFIGS:
        raise ValueError(f"Unsupported provider: {provider}")
    get_provider_adapter(provider_key)
    if secret:
        await submit_secret(session=session, tenant_id=tenant_id, provider=provider_key, environment=environment, credential_type=credential_type, secret=secret, credential_version=None)
    record = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider_key, TenantProviderConnection.environment == environment.upper()))
    if record is None:
        record = await create_connection(session=session, tenant_id=tenant_id, provider=provider_key, environment=environment, capability=credential_type)
    record.last_error = "Provider connection testing is not implemented"
    await _audit_event(session=session, tenant_id=tenant_id, provider=provider_key, capability=credential_type, environment=environment.upper(), event_type="connection_test", result="NOT_IMPLEMENTED", metadata={"provider": provider_key})
    await session.commit()
    return {"provider": provider_key, "environment": environment.upper(), "status": record.status, "success": False, "state": "NOT_IMPLEMENTED"}


async def enable_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str) -> dict[str, Any]:
    record = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider.lower()))
    if record is None:
        raise ValueError(f"No connection found for provider {provider}")
    if record.environment != "LIVE":
        raise ValueError("Only LIVE-environment connections can be enabled")
    if record.connection_tested_at is None or record.last_success_at is None or record.status != "TEST":
        raise ValueError("LIVE activation requires a successful provider connection test")
    credential = await session.scalar(
        select(TenantProviderCredentialVersion).where(
            TenantProviderCredentialVersion.tenant_id == tenant_id,
            TenantProviderCredentialVersion.provider == record.provider,
            TenantProviderCredentialVersion.capability == record.capability,
            TenantProviderCredentialVersion.environment == record.environment,
            TenantProviderCredentialVersion.credential_version == record.credential_version,
        )
    )
    if credential is None:
        raise ValueError("LIVE activation requires the current credential version")
    previous_status = record.status
    record.status = "LIVE"
    await _audit_event(session=session, tenant_id=tenant_id, provider=record.provider, capability=record.capability, environment=record.environment, event_type="connection_enabled", result="SUCCESS", metadata={"previous_status": previous_status, "new_status": record.status})
    await session.commit()
    return {"provider": provider.lower(), "status": "LIVE"}


async def disable_connection(*, session: AsyncSession, tenant_id: uuid.UUID, provider: str) -> dict[str, Any]:
    record = await session.scalar(select(TenantProviderConnection).where(TenantProviderConnection.tenant_id == tenant_id, TenantProviderConnection.provider == provider.lower()))
    if record is None:
        raise ValueError(f"No connection found for provider {provider}")
    previous_status = record.status
    record.status = "DISABLED"
    get_secret_store().invalidate_cache(tenant_id=tenant_id, provider=record.provider, environment=record.environment)
    await _audit_event(session=session, tenant_id=tenant_id, provider=record.provider, capability=record.capability, environment=record.environment, event_type="connection_disabled", result="SUCCESS", metadata={"previous_status": previous_status, "new_status": record.status})
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

