"""Tenant-scoped provider integration persistence.

These tables are stored in the public schema because inbound webhooks arrive
without an authenticated tenant context; only a non-secret opaque routing record
lives in the public scope. The tenant binding itself remains authoritative via the
current tenant context in the authenticated backend.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TenantProviderConnection(Base, TimestampMixin):
    __tablename__ = "tenant_provider_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "environment", name="uq_provider_connections_tenant_provider_env"),
        UniqueConstraint("endpoint_id", name="uq_provider_connections_endpoint_id"),
        Index("ix_provider_connections_tenant_provider", "tenant_id", "provider"),
        Index("ix_provider_connections_status", "status"),
        CheckConstraint("provider IN ('twilio', 'razorpay', 'cloudinary')", name="ck_provider_connections_provider"),
        CheckConstraint("capability IN ('communication', 'payment', 'document_storage')", name="ck_provider_connections_capability"),
        CheckConstraint("environment IN ('TEST', 'LIVE')", name="ck_provider_connections_environment"),
        CheckConstraint("status IN ('DISABLED', 'TEST', 'LIVE')", name="ck_provider_connections_status"),
        CheckConstraint("credential_version > 0", name="ck_provider_connections_credential_version"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DISABLED")
    connection_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    endpoint_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class TenantProviderCredentialVersion(Base, TimestampMixin):
    __tablename__ = "tenant_provider_credential_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "environment",
            "credential_version",
            name="uq_provider_credentials_tenant_provider_env_version",
        ),
        Index("ix_provider_credentials_tenant_provider", "tenant_id", "provider"),
        CheckConstraint("provider IN ('twilio', 'razorpay', 'cloudinary')", name="ck_provider_credentials_provider"),
        CheckConstraint("capability IN ('communication', 'payment', 'document_storage')", name="ck_provider_credentials_capability"),
        CheckConstraint("environment IN ('TEST', 'LIVE')", name="ck_provider_credentials_environment"),
        CheckConstraint("credential_version > 0", name="ck_provider_credentials_version"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    versioned_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class TenantProviderWebhookRoute(Base):
    __tablename__ = "tenant_provider_webhook_routes"
    __table_args__ = (
        Index("ix_provider_webhook_routes_tenant_provider", "tenant_id", "provider"),
        CheckConstraint("provider IN ('twilio', 'razorpay', 'cloudinary')", name="ck_provider_webhook_routes_provider"),
        CheckConstraint("capability IN ('communication', 'payment', 'document_storage')", name="ck_provider_webhook_routes_capability"),
        CheckConstraint("environment IN ('TEST', 'LIVE')", name="ck_provider_webhook_routes_environment"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.tenant_provider_connections.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TenantProviderAuditEvent(Base):
    __tablename__ = "tenant_provider_audit_events"
    __table_args__ = (
        Index("ix_provider_audit_events_tenant_time", "tenant_id", "created_at"),
        CheckConstraint("provider IN ('twilio', 'razorpay', 'cloudinary')", name="ck_provider_audit_events_provider"),
        CheckConstraint("capability IN ('communication', 'payment', 'document_storage')", name="ck_provider_audit_events_capability"),
        CheckConstraint("environment IN ('TEST', 'LIVE')", name="ck_provider_audit_events_environment"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
