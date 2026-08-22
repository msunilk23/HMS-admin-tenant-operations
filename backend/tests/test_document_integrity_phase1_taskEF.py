"""
Task F — Concurrency-safe document finalization: PostgreSQL integration tests.

Exercises the shared document architecture (Task E: app.services.document_service
+ app.models.tenant.document + app.services.document_storage) directly against a
real PostgreSQL instance (schema-per-tenant, like every other Phase-1 concurrency
test in this suite) so unique-constraint/row-lock behaviour is genuinely verified,
not mocked. Skips cleanly if PostgreSQL is not reachable.
"""
import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital",
)

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PG_URL = os.environ["DATABASE_URL"]


def _postgres_reachable() -> bool:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(PG_URL.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="PostgreSQL not reachable at DATABASE_URL — start infra/docker-compose.yml postgres service",
)

SCHEMA_A = "test_doc_tenant_a"
SCHEMA_B = "test_doc_tenant_b"


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


async def _provision_schema(engine, schema: str):
    from app.db.base import Base
    from app.models.tenant.appointment import Appointment
    from app.models.tenant.audit_log import AuditLog
    from app.models.tenant.department import Department
    from app.models.tenant.doctor import Doctor
    from app.models.tenant.document import DocumentVersion, DocumentVersionCounter
    from app.models.tenant.invoice import Invoice
    from app.models.tenant.patient import Patient
    from app.models.tenant.prescription import Prescription, PrescriptionItem
    from app.models.tenant.visit import Visit

    tables = [
        Department.__table__, Doctor.__table__, Appointment.__table__,
        Patient.__table__, Visit.__table__, Invoice.__table__,
        Prescription.__table__, PrescriptionItem.__table__,
        DocumentVersion.__table__, DocumentVersionCounter.__table__,
        AuditLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables, checkfirst=False))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg(monkeypatch_module):
    from app.models.tenant.doctor import Doctor
    from app.models.tenant.invoice import Invoice
    from app.models.tenant.patient import Patient
    from app.models.tenant.prescription import Prescription
    from app.models.tenant.visit import Visit

    engine = create_async_engine(PG_URL, pool_pre_ping=True)
    await _provision_schema(engine, SCHEMA_A)
    await _provision_schema(engine, SCHEMA_B)

    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    def session_factory(schema: str):
        async def new_session() -> AsyncSession:
            s = maker()
            await s.execute(text(f'SET search_path TO "{schema}", public'))
            return s
        return new_session

    async def seed_invoice_and_prescription(schema: str):
        new_session = session_factory(schema)
        now = datetime.now(timezone.utc)
        patient_id = uuid.uuid4()
        doctor_id = uuid.uuid4()
        visit_id = uuid.uuid4()
        invoice_id = uuid.uuid4()
        rx_id = uuid.uuid4()
        async with (await new_session()) as s:
            s.add(Patient(
                id=patient_id, uhid=f"UHID{uuid.uuid4().hex[:8].upper()}", first_name="Doc", last_name="Test",
                gender="male", phone="9000000001", created_at=now, updated_at=now,
            ))
            s.add(Doctor(id=doctor_id, user_id=uuid.uuid4(), full_name="Dr. Test", specialization="General"))
            s.add(Visit(id=visit_id, patient_id=patient_id, uhid=f"UHID{patient_id.hex[:8]}", status="CLOSED", created_at=now, updated_at=now))
            await s.commit()
            s.add(Invoice(
                id=invoice_id, visit_id=visit_id, uhid=f"UHID{patient_id.hex[:8]}",
                line_items=[{"description": "Consultation", "amount": 500.0}],
                subtotal=500.0, discount=0.0, tax=0.0, total=500.0, paid_amount=500.0,
                payment_method="cash", status="paid", paid_at=now, created_at=now, updated_at=now,
            ))
            s.add(Prescription(
                id=rx_id, visit_id=visit_id, doctor_id=doctor_id, uhid=f"UHID{patient_id.hex[:8]}",
                status="finalized", medicines=[{"medicine": "Paracetamol", "dose": "500mg"}], instructions="After food",
            ))
            await s.commit()
        return {"visit_id": visit_id, "invoice_id": invoice_id, "prescription_id": rx_id, "patient_id": patient_id, "doctor_id": doctor_id}

    seed_a = await seed_invoice_and_prescription(SCHEMA_A)
    seed_b = await seed_invoice_and_prescription(SCHEMA_B)

    yield {
        "engine": engine,
        "session_factory": session_factory,
        "seed_a": seed_a,
        "seed_b": seed_b,
    }

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_A}" CASCADE'))
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_B}" CASCADE'))
    await engine.dispose()


def _invoice_snapshot(invoice_id, visit_id, patient_id, extra_tax: float = 0.0) -> dict:
    from app.core.invoice_pdf_service import canonical_invoice_snapshot

    return canonical_invoice_snapshot({
        "id": invoice_id, "visit_id": visit_id, "uhid": "UHID1234",
        "line_items": [{"description": "Consultation", "amount": 500.0}],
        "subtotal": 500.0, "discount": 0.0, "tax": extra_tax, "total": 500.0 + extra_tax,
        "paid_amount": 500.0, "status": "paid", "payment_method": "cash",
        "receipt_number": None, "source": None, "pharmacy_queue_id": None,
        "created_at": datetime.now(timezone.utc), "paid_at": datetime.now(timezone.utc),
        "patient_id": patient_id, "patient_name": "Doc Test", "patient_phone": "9000000001",
        "doctor_id": None, "department_id": None,
    })


def _prescription_snapshot(rx_id, visit_id, patient_id, doctor_id) -> dict:
    from app.core.prescription_pdf_service import canonical_prescription_snapshot

    return canonical_prescription_snapshot({
        "id": rx_id, "visit_id": visit_id, "uhid": "UHID1234", "status": "finalized",
        "instructions": "After food", "medicines": [{"medicine": "Paracetamol", "dose": "500mg"}],
        "created_at": datetime.now(timezone.utc),
        "patient_id": patient_id, "patient_name": "Doc Test",
        "doctor_id": doctor_id, "doctor_name": "Dr. Test",
    })


@pytest.mark.asyncio(loop_scope="module")
async def test_two_concurrent_invoice_finalizations_get_unique_sequential_versions(pg, tmp_path_factory):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)

    # Two DIFFERENT snapshots (different tax) so both genuinely produce new versions
    # rather than being deduplicated by the idempotency checksum check.
    async def _finalize(tax_value: float):
        session = await new_session()
        try:
            snapshot = _invoice_snapshot(seed["invoice_id"], seed["visit_id"], seed["patient_id"], extra_tax=tax_value)
            doc = await finalize_document(
                session,
                document_type=DOCUMENT_TYPE_INVOICE,
                parent_id=seed["invoice_id"],
                snapshot=snapshot,
                render_pdf=build_invoice_pdf,
                storage=storage,
            )
            await session.commit()
            return doc.version, doc.storage_key
        finally:
            await session.close()

    results = await asyncio.gather(_finalize(1.0), _finalize(2.0))
    versions = sorted(v for v, _ in results)
    keys = [k for _, k in results]
    assert versions == [1, 2], f"Expected unique sequential versions, got {versions}"
    assert len(set(keys)) == 2, "Each version must use a unique immutable storage key"


@pytest.mark.asyncio(loop_scope="module")
async def test_two_concurrent_prescription_finalizations_get_unique_sequential_versions(pg):
    from app.core.prescription_pdf_service import build_prescription_pdf
    from app.services.document_service import finalize_document
    from app.models.tenant.document import DOCUMENT_TYPE_PRESCRIPTION
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)

    async def _finalize(instructions: str):
        session = await new_session()
        try:
            snapshot = _prescription_snapshot(seed["prescription_id"], seed["visit_id"], seed["patient_id"], seed["doctor_id"])
            snapshot["prescription"]["instructions"] = instructions
            doc = await finalize_document(
                session,
                document_type=DOCUMENT_TYPE_PRESCRIPTION,
                parent_id=seed["prescription_id"],
                snapshot=snapshot,
                render_pdf=build_prescription_pdf,
                storage=storage,
            )
            await session.commit()
            return doc.version, doc.storage_key
        finally:
            await session.close()

    results = await asyncio.gather(_finalize("After food"), _finalize("Before food"))
    versions = sorted(v for v, _ in results)
    keys = [k for _, k in results]
    assert versions == [1, 2]
    assert len(set(keys)) == 2


@pytest.mark.asyncio(loop_scope="module")
async def test_no_file_is_ever_overwritten(pg):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()

    session = await new_session()
    doc1 = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=10.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    v1_bytes = storage.read(doc1.storage_key)
    await session.close()

    session = await new_session()
    doc2 = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=20.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    # v1's file must remain byte-identical after v2 is created — never overwritten.
    assert storage.read(doc1.storage_key) == v1_bytes
    assert doc1.storage_key != doc2.storage_key


@pytest.mark.asyncio(loop_scope="module")
async def test_database_failure_after_storage_write_does_not_corrupt_versioning(pg, monkeypatch_module):
    """Simulate a DB commit failure AFTER the file was written but before the
    caller commits. The counter allocation rolls back with it, so a retry
    reallocates the same version number, and the orphaned (harmless,
    content-addressed) file on disk does not block that retry."""
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE, DocumentVersion
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()
    snapshot = _invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=99.0)

    session = await new_session()
    doc = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=snapshot, render_pdf=build_invoice_pdf, storage=storage,
    )
    assert doc.version == 1
    # Simulate the caller's surrounding transaction failing to commit (DB outage).
    await session.rollback()
    await session.close()

    # No committed metadata should exist for this invoice.
    verify_session = await new_session()
    rows = (await verify_session.execute(
        select(DocumentVersion).where(DocumentVersion.parent_id == invoice_id)
    )).scalars().all()
    assert rows == []
    await verify_session.close()

    # Retry with the same snapshot must succeed and reuse version 1 cleanly
    # (the orphaned identical-content file from the aborted attempt is a no-op write).
    session = await new_session()
    retry_doc = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=snapshot, render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()
    assert retry_doc.version == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_storage_failure_before_commit_leaves_no_metadata(pg, monkeypatch_module):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document, DocumentFinalizationError
    from app.services.document_storage import DocumentStorageError
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE, DocumentVersion

    class _FailingStorage:
        def write(self, key, data):
            raise DocumentStorageError("simulated disk failure")

        def read(self, key):  # pragma: no cover - unused
            raise FileNotFoundError(key)

        def exists(self, key):  # pragma: no cover - unused
            return False

    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()

    session = await new_session()
    with pytest.raises(DocumentStorageError):
        await finalize_document(
            session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
            snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=42.0),
            render_pdf=build_invoice_pdf, storage=_FailingStorage(),
        )
    await session.rollback()
    await session.close()

    verify_session = await new_session()
    rows = (await verify_session.execute(
        select(DocumentVersion).where(DocumentVersion.parent_id == invoice_id)
    )).scalars().all()
    assert rows == [], "Storage failure must not commit unusable metadata"
    await verify_session.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_stored_document_checksum_matches_actual_file_bytes(pg):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()
    session = await new_session()
    doc = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=3.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    actual_bytes = storage.read(doc.storage_key)
    assert hashlib.sha256(actual_bytes).hexdigest() == doc.checksum_sha256


@pytest.mark.asyncio(loop_scope="module")
async def test_historical_version_retrieval_returns_original_snapshot(pg):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document, get_version
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()

    session = await new_session()
    v1 = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=5.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    session = await new_session()
    v2 = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=6.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    session = await new_session()
    fetched_v1 = await get_version(session, DOCUMENT_TYPE_INVOICE, invoice_id, 1)
    await session.close()

    assert fetched_v1.id == v1.id
    assert fetched_v1.snapshot_json["invoice"]["tax"] == 5.0
    assert v2.snapshot_json["invoice"]["tax"] == 6.0


@pytest.mark.asyncio(loop_scope="module")
async def test_cross_tenant_document_download_is_structurally_rejected(pg):
    """Tenant B's session (schema search_path) must never see Tenant A's document row,
    even when given Tenant A's exact parent_id — tenant scope is the schema itself."""
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document, get_version
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed_a = pg["seed_a"]
    new_session_a = pg["session_factory"](SCHEMA_A)
    new_session_b = pg["session_factory"](SCHEMA_B)
    invoice_id = uuid.uuid4()

    session = await new_session_a()
    doc_a = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed_a["visit_id"], seed_a["patient_id"], extra_tax=7.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    session_b = await new_session_b()
    cross_tenant_lookup = await get_version(session_b, DOCUMENT_TYPE_INVOICE, invoice_id, doc_a.version)
    await session_b.close()

    assert cross_tenant_lookup is None, "Hospital B must never access Hospital A's documents"


@pytest.mark.asyncio(loop_scope="module")
async def test_tampered_file_checksum_mismatch_is_detected(pg):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document, read_document_bytes, DocumentIntegrityError
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()
    session = await new_session()
    doc = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=_invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=8.0),
        render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    # Tamper with the stored file directly on disk (bypassing the write-once API).
    path = storage._path(doc.storage_key)
    path.write_bytes(b"%PDF-tampered-content")

    with pytest.raises(DocumentIntegrityError):
        read_document_bytes(storage, doc)


@pytest.mark.asyncio(loop_scope="module")
async def test_unauthorized_role_is_rejected_for_document_download(pg):
    from app.core.dependencies import require_role
    from fastapi import HTTPException

    dependency = require_role("receptionist", "billing_officer", "nurse", "doctor", "hospital_admin")
    unauthorized_user = {"sub": str(uuid.uuid4()), "tenant_schema": SCHEMA_A, "role": "pharmacist"}

    with pytest.raises(HTTPException) as exc_info:
        await dependency(unauthorized_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio(loop_scope="module")
async def test_repeated_finalization_request_is_idempotent(pg):
    from app.core.invoice_pdf_service import build_invoice_pdf
    from app.services.document_service import finalize_document
    from app.models.tenant.document import DOCUMENT_TYPE_INVOICE, DocumentVersion
    from app.services.document_storage import LocalFileDocumentStorage

    storage = LocalFileDocumentStorage(subroot=f"test-docs-{uuid.uuid4().hex}")
    seed = pg["seed_a"]
    new_session = pg["session_factory"](SCHEMA_A)
    invoice_id = uuid.uuid4()
    snapshot = _invoice_snapshot(invoice_id, seed["visit_id"], seed["patient_id"], extra_tax=11.0)

    session = await new_session()
    first = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=snapshot, render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    session = await new_session()
    second = await finalize_document(
        session, document_type=DOCUMENT_TYPE_INVOICE, parent_id=invoice_id,
        snapshot=snapshot, render_pdf=build_invoice_pdf, storage=storage,
    )
    await session.commit()
    await session.close()

    assert first.id == second.id
    assert first.version == second.version

    verify_session = await new_session()
    rows = (await verify_session.execute(
        select(DocumentVersion).where(DocumentVersion.parent_id == invoice_id)
    )).scalars().all()
    await verify_session.close()
    assert len(rows) == 1, "Repeated identical finalization requests must not create duplicate versions"
