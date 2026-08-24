"""Shared immutable document-version architecture (invoice + prescription PDFs).

One physical table backs every document type so persistence/versioning logic
is written once (see app.services.document_service) instead of duplicated per
document kind. Tenant ownership is enforced structurally: these tables live
inside the tenant's own PostgreSQL schema (search_path), the same convention
already used by every other tenant-scoped table in this codebase.
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DOCUMENT_TYPE_INVOICE = "invoice"
DOCUMENT_TYPE_PRESCRIPTION = "prescription"
DOCUMENT_TYPES = (DOCUMENT_TYPE_INVOICE, DOCUMENT_TYPE_PRESCRIPTION)


class DocumentVersion(Base):
    """One immutable rendered document (invoice/prescription PDF) version."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_type", "parent_id", "version", name="uq_document_versions_type_parent_version"),
        UniqueConstraint("document_type", "storage_key", name="uq_document_versions_storage_key"),
        Index("ix_document_versions_type_parent", "document_type", "parent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Polymorphic reference (invoices.id or prescriptions.id) — no FK because the
    # target table depends on document_type; ownership/existence is validated
    # in the application layer before finalization.
    parent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 of the actual immutable stored file bytes — used to detect
    # tampering/corruption when the document is later read back.
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA-256 of the canonical clinical/financial snapshot JSON — used only
    # to detect "nothing changed" for idempotent re-finalization (rendered
    # PDF bytes are not byte-for-byte deterministic, e.g. embedded timestamps).
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Immutable, content-addressed relative storage key (never reused/overwritten).
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    generated_by_service: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class DocumentVersionCounter(Base):
    """Atomic per-(document_type, parent_id) version counter, row-locked on allocation."""

    __tablename__ = "document_version_counters"
    __table_args__ = (
        UniqueConstraint("document_type", "parent_id", name="uq_document_version_counters_type_parent"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    parent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
