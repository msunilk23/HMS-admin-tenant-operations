"""Focused P29.10 RBAC and audit contract tests."""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.services.audit_service import record_audit
from app.core.dependencies import require_permission


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


class FakePermissionSession:
    def __init__(self, allowed: str | None):
        self.allowed = allowed

    async def scalar(self, _statement):
        return self.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", [
    "PHARMACY_BILLING_CREATE",
    "PHARMACY_BILLING_PAYMENT",
    "PHARMACY_BILLING_VERIFY",
    "PHARMACY_BILLING_CANCEL",
])
async def test_pharmacy_billing_permission_denies_missing_permission(permission):
    check = require_permission(permission)
    with pytest.raises(HTTPException) as error:
        await check({"role": "pharmacist"}, FakePermissionSession(None))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_pharmacy_billing_permission_allows_granted_permission():
    user = {"sub": str(uuid.uuid4()), "role": "pharmacist", "tenant_schema": "tenant_a"}
    check = require_permission("PHARMACY_BILLING_CREATE")
    assert await check(user, FakePermissionSession("PHARMACY_BILLING_CREATE")) == user


@pytest_asyncio.fixture
async def audit_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=[AuditLog.__table__])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_pharmacy_billing_audit_events_persist_actor_and_references(audit_session):
    actor = uuid.uuid4()
    invoice_id = uuid.uuid4()
    dispense_id = uuid.uuid4()
    user = {"sub": str(actor), "role": "pharmacist", "tenant_schema": "tenant_a"}
    for event in (
        "PHARMACY_INVOICE_CREATED",
        "PHARMACY_INVOICE_REUSED",
        "PHARMACY_PAYMENT_COMPLETED",
        "PHARMACY_BILLING_CANCELLED",
        "PHARMACY_RESERVATION_RELEASED_FOR_BILLING_CANCELLATION",
        "PHARMACY_DISPENSE_AUTHORIZED",
        "PHARMACY_DISPENSE_CONFIRMED",
    ):
        record_audit(
            audit_session,
            current_user=user,
            action=event,
            resource_type="invoice" if "INVOICE" in event or "PAYMENT" in event or "BILLING" in event else "pharmacy_dispense",
            resource_id=invoice_id if "DISPENSE" not in event and "RESERVATION" not in event else dispense_id,
            new_value={"invoice_id": str(invoice_id), "dispense_id": str(dispense_id)},
        )
    await audit_session.commit()
    rows = (await audit_session.execute(select(AuditLog).order_by(AuditLog.timestamp))).scalars().all()
    assert [row.action for row in rows] == [
        "PHARMACY_INVOICE_CREATED",
        "PHARMACY_INVOICE_REUSED",
        "PHARMACY_PAYMENT_COMPLETED",
        "PHARMACY_BILLING_CANCELLED",
        "PHARMACY_RESERVATION_RELEASED_FOR_BILLING_CANCELLATION",
        "PHARMACY_DISPENSE_AUTHORIZED",
        "PHARMACY_DISPENSE_CONFIRMED",
    ]
    assert all(row.user_id == actor and row.tenant_schema == "tenant_a" for row in rows)
    assert all(row.new_value["invoice_id"] == str(invoice_id) for row in rows)
