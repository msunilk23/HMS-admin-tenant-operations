import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.services.audit_service import record_audit, sanitize_audit_value


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[AuditLog.__table__])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current_session:
        yield current_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_audit_captures_domain_metadata_and_redacts_secrets(session):
    user_id = uuid.uuid4()
    visit_id = uuid.uuid4()
    record_audit(
        session,
        current_user={"sub": str(user_id), "role": "billing_officer", "tenant_schema": "tenant_a"},
        action="REFUND",
        resource_type="invoice",
        resource_id=uuid.uuid4(),
        visit_id=visit_id,
        old_value={"status": "paid"},
        new_value={"status": "refunded", "password": "must-not-persist"},
        reason="Patient request",
        request_metadata={"request_id": "req-1", "authorization": "secret-token"},
    )
    await session.commit()

    row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.tenant_schema == "tenant_a"
    assert row.role == "billing_officer"
    assert row.visit_id == visit_id
    assert row.reason == "Patient request"
    assert row.new_value["password"] == "[REDACTED]"
    assert row.request_metadata["authorization"] == "[REDACTED]"


def test_sanitize_audit_value_handles_nested_values():
    assert sanitize_audit_value({"nested": {"refresh_token": "secret"}})["nested"]["refresh_token"] == "[REDACTED]"
