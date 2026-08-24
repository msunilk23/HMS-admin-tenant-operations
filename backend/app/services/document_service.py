"""Shared immutable document-generation/versioning service.

Used by both invoice and prescription PDF finalization so the concurrency,
persistence, and integrity logic is written exactly once. Rendering (what the
PDF looks like) stays in per-document-type modules
(`app.core.invoice_pdf_service`, `app.core.prescription_pdf_service`); this
module only owns: checksum computation, concurrency-safe version allocation,
write-once storage sequencing, and historical/integrity retrieval.

Concurrency-safe version allocation (Task F):
  Version numbers come from `DocumentVersionCounter` via a single
  `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` statement (same proven
  pattern as `app.services.token_allocation`). PostgreSQL takes a row lock on
  the counter row for the duration of the allocating transaction, so two
  concurrent finalizations for the same (document_type, parent_id) are
  serialized by the database itself — no read-latest-then-+1 race is
  possible. The `DocumentVersion` table also carries a DB-level unique
  constraint on (document_type, parent_id, version) as defense-in-depth; a
  violation is treated as a recognized conflict and retried a bounded number
  of times, never silently swallowed.

Ordering guarantees:
  1. Idempotency check (same checksum already finalized) — return existing,
     no new version consumed.
  2. Allocate version (row-locked, still inside the caller's transaction).
  3. Render PDF bytes.
  4. Write to storage FIRST, using an immutable content-addressed key. If
     this raises, we propagate the error and never insert a metadata row —
     storage failure cannot commit unusable metadata.
  5. Insert the `DocumentVersion` row (same transaction). If the caller's
     surrounding commit later fails (DB failure), the counter increment and
     any flushed metadata roll back together; the already-written file
     becomes an unreferenced-but-harmless orphan (content-addressed, so a
     retry with the same inputs reuses/no-ops the same key — see
     `LocalFileDocumentStorage.write`). Phase 1 accepts this as a documented
     risk; production object storage should add a periodic orphan sweep.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.document import DocumentVersion, DocumentVersionCounter
from app.services.document_storage import (
    DocumentStorage,
    DocumentStorageConflict,
    DocumentStorageError,
    sha256_hex,
)

# Real concurrency is resolved by the DB row lock above; a small retry budget
# only guards recognized conflicts (unique-violation races, storage key
# collisions), never unexpected exceptions.
_MAX_FINALIZE_ATTEMPTS = 5


class DocumentFinalizationError(Exception):
    """Raised when a document version could not be finalized after retrying recognized conflicts."""


class DocumentIntegrityError(Exception):
    """Raised when a stored document's bytes no longer match its recorded checksum."""


def canonical_checksum(snapshot: dict) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_hex(payload)


async def _allocate_version(session: AsyncSession, document_type: str, parent_id: uuid.UUID) -> int:
    bind = session.bind
    insert_fn = _sqlite_insert if bind is not None and bind.dialect.name == "sqlite" else _pg_insert
    stmt = (
        insert_fn(DocumentVersionCounter)
        .values(id=uuid.uuid4(), document_type=document_type, parent_id=parent_id, last_value=1)
        .on_conflict_do_update(
            index_elements=["document_type", "parent_id"],
            set_={"last_value": DocumentVersionCounter.last_value + 1},
        )
        .returning(DocumentVersionCounter.last_value)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_current_version(session: AsyncSession, document_type: str, parent_id: uuid.UUID) -> DocumentVersion | None:
    return (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_type == document_type, DocumentVersion.parent_id == parent_id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_version(
    session: AsyncSession, document_type: str, parent_id: uuid.UUID, version: int
) -> DocumentVersion | None:
    return (
        await session.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_type == document_type,
                DocumentVersion.parent_id == parent_id,
                DocumentVersion.version == version,
            )
        )
    ).scalar_one_or_none()


async def list_versions(session: AsyncSession, document_type: str, parent_id: uuid.UUID) -> list[DocumentVersion]:
    rows = (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_type == document_type, DocumentVersion.parent_id == parent_id)
            .order_by(DocumentVersion.version.asc())
        )
    ).scalars().all()
    return list(rows)


async def finalize_document(
    session: AsyncSession,
    *,
    document_type: str,
    parent_id: uuid.UUID,
    snapshot: dict,
    render_pdf: Callable[[dict], bytes],
    storage: DocumentStorage,
    generated_by_user_id: uuid.UUID | None = None,
    generated_by_service: str | None = None,
) -> DocumentVersion:
    """Idempotently create (or return) the immutable document version for `snapshot`.

    Never overwrites an earlier version. Safe to call concurrently for the
    same parent_id — see module docstring for the ordering guarantees.
    """
    snapshot_checksum = canonical_checksum(snapshot)

    existing = (
        await session.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_type == document_type,
                DocumentVersion.parent_id == parent_id,
                DocumentVersion.snapshot_checksum == snapshot_checksum,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    last_error: Exception | None = None
    for _ in range(_MAX_FINALIZE_ATTEMPTS):
        version = await _allocate_version(session, document_type, parent_id)
        pdf_bytes = render_pdf(snapshot)
        file_checksum = sha256_hex(pdf_bytes)
        storage_key = f"{document_type}/{parent_id}/v{version}-{file_checksum[:16]}.pdf"

        try:
            file_size = storage.write(storage_key, pdf_bytes)
        except DocumentStorageConflict as exc:
            # Recognized conflict (key collision with different content) — retry with next version.
            last_error = exc
            continue
        except DocumentStorageError:
            # Storage failure must not commit unusable metadata — propagate untouched.
            raise

        document = DocumentVersion(
            id=uuid.uuid4(),
            document_type=document_type,
            parent_id=parent_id,
            version=version,
            checksum_sha256=file_checksum,
            snapshot_checksum=snapshot_checksum,
            storage_key=storage_key,
            file_size_bytes=file_size,
            snapshot_json=snapshot,
            generated_by_user_id=generated_by_user_id,
            generated_by_service=generated_by_service,
            is_current=True,
        )
        nested = await session.begin_nested()
        try:
            await session.execute(
                update(DocumentVersion)
                .where(
                    DocumentVersion.document_type == document_type,
                    DocumentVersion.parent_id == parent_id,
                    DocumentVersion.is_current.is_(True),
                )
                .values(is_current=False)
            )
            session.add(document)
            await session.flush()
        except IntegrityError as exc:
            await nested.rollback()
            try:
                session.expunge(document)
            except Exception:
                pass
            last_error = exc
            continue
        return document

    raise DocumentFinalizationError(
        f"Could not finalize {document_type} document for {parent_id} after multiple attempts"
    ) from last_error


def read_document_bytes(storage: DocumentStorage, document: DocumentVersion) -> bytes:
    """Read stored bytes and verify they still match the recorded checksum."""
    try:
        data = storage.read(document.storage_key)
    except FileNotFoundError as exc:
        raise DocumentIntegrityError(f"Stored document file is missing: {document.storage_key}") from exc
    if sha256_hex(data) != document.checksum_sha256:
        raise DocumentIntegrityError(f"Checksum mismatch for document {document.id} — file may be tampered")
    return data
