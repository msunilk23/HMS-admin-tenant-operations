import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "task8-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


from app.api.v1.billing import download_invoice_document, finalize_invoice_document, list_invoice_documents
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.appointment import Appointment
from app.models.tenant.department import Department
from app.models.tenant.doctor import Doctor
from app.models.tenant.invoice import Invoice
from app.models.tenant.document import DOCUMENT_TYPE_INVOICE, DocumentVersion, DocumentVersionCounter
from app.models.tenant.patient import Patient
from app.models.tenant.visit import Visit


CURRENT_USER = {
    "sub": str(uuid.uuid4()),
    "tenant_schema": "test_tenant",
    "role": "billing_officer",
}

_TABLES = [
    Department.__table__,
    Doctor.__table__,
    Patient.__table__,
    Appointment.__table__,
    Visit.__table__,
    Invoice.__table__,
    DocumentVersion.__table__,
    DocumentVersionCounter.__table__,
    AuditLog.__table__,
]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed_paid_invoice(session: AsyncSession) -> Invoice:
    now = datetime.now(timezone.utc)
    patient = Patient(
        id=uuid.uuid4(),
        uhid=f"UHID{uuid.uuid4().hex[:8].upper()}",
        first_name="Task8",
        last_name="Patient",
        gender="female",
        phone="9999999999",
        created_at=now,
        updated_at=now,
    )
    visit = Visit(
        id=uuid.uuid4(),
        patient_id=patient.id,
        uhid=patient.uhid,
        status="CLOSED",
        created_at=now,
        updated_at=now,
    )
    invoice = Invoice(
        id=uuid.uuid4(),
        visit_id=visit.id,
        uhid=patient.uhid,
        line_items=[{"description": "Consultation", "amount": 500.0}],
        subtotal=500.0,
        discount=0.0,
        tax=0.0,
        total=500.0,
        paid_amount=500.0,
        payment_method="cash",
        status="paid",
        paid_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add_all([patient, visit, invoice])
    await session.commit()
    return invoice


@pytest.mark.asyncio
async def test_finalize_invoice_document_is_idempotent_for_unchanged_invoice(session: AsyncSession):
    invoice = await _seed_paid_invoice(session)

    first = await finalize_invoice_document(invoice.id, session=session, current_user=CURRENT_USER)
    second = await finalize_invoice_document(invoice.id, session=session, current_user=CURRENT_USER)

    assert first.id == second.id
    assert first.version == 1

    rows = (await session.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_type == DOCUMENT_TYPE_INVOICE, DocumentVersion.parent_id == invoice.id
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_finalize_invoice_document_creates_new_version_when_invoice_changes(session: AsyncSession):
    invoice = await _seed_paid_invoice(session)

    v1 = await finalize_invoice_document(invoice.id, session=session, current_user=CURRENT_USER)
    db_invoice = await session.get(Invoice, invoice.id)
    db_invoice.tax = 25.0
    db_invoice.total = 525.0
    await session.commit()

    v2 = await finalize_invoice_document(invoice.id, session=session, current_user=CURRENT_USER)

    assert v2.version == 2
    assert v1.checksum_sha256 != v2.checksum_sha256

    docs = await list_invoice_documents(invoice.id, session=session, _=CURRENT_USER)
    assert [d.version for d in docs] == [1, 2]


@pytest.mark.asyncio
async def test_download_invoice_document_returns_pdf_response(session: AsyncSession):
    invoice = await _seed_paid_invoice(session)
    doc = await finalize_invoice_document(invoice.id, session=session, current_user=CURRENT_USER)

    response = await download_invoice_document(invoice.id, doc.version, session=session, _=CURRENT_USER)
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].endswith('.pdf"')
    assert bytes(response.body).startswith(b"%PDF")
