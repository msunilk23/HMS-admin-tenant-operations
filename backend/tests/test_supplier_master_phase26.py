import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.pharmacy import (
    create_supplier,
    deactivate_supplier,
    import_suppliers,
    list_suppliers,
    update_supplier,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.supplier import Supplier
from app.schemas.pharmacy import SupplierCreate, SupplierImportItem, SupplierUpdate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


ADMIN = {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": "tenant_a"}
STORE_MANAGER = {"sub": str(uuid.uuid4()), "role": "store_manager", "tenant_schema": "tenant_a"}
PHARMACIST = {"sub": str(uuid.uuid4()), "role": "pharmacist", "tenant_schema": "tenant_a"}


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Supplier.__table__, AuditLog.__table__])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        current.add_all([
            Supplier(supplier_code="CIPLA", supplier_name="Cipla Limited", gstin="27AAACC1457E1Z2", country="India", credit_days=30),
            Supplier(supplier_code="INACTIVE", supplier_name="Inactive Supplier", is_active=False),
        ])
        await current.commit()
        yield current
    await engine.dispose()


@pytest.mark.asyncio
async def test_supplier_search_excludes_inactive_and_matches_code_or_name(session):
    rows = await list_suppliers("cipla", False, 20, session, PHARMACIST)
    assert [row.supplier_code for row in rows] == ["CIPLA"]
    rows = await list_suppliers("limited", False, 20, session, PHARMACIST)
    assert [row.supplier_code for row in rows] == ["CIPLA"]
    assert await list_suppliers("inactive", False, 20, session, PHARMACIST) == []
    assert [row.supplier_code for row in await list_suppliers("inactive", True, 20, session, PHARMACIST)] == ["INACTIVE"]


@pytest.mark.asyncio
async def test_supplier_crud_soft_delete_and_audit(session):
    created = await create_supplier(
        SupplierCreate(
            supplier_code=" sun ", supplier_name=" Sun Pharma ", gstin="24AAACS3126R1ZQ",
            drug_license_no="DL-100", city="Mumbai", country="India", credit_days=45,
        ),
        session,
        ADMIN,
    )
    assert (created.supplier_code, created.supplier_name, created.credit_days) == ("SUN", "Sun Pharma", 45)
    updated = await update_supplier(created.id, SupplierUpdate(supplier_name="Sun Pharma Limited", payment_terms="Net 45"), session, STORE_MANAGER)
    assert updated.supplier_name == "Sun Pharma Limited"
    deactivated = await deactivate_supplier(created.id, session, STORE_MANAGER)
    assert deactivated.is_active is False
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(created.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_supplier_import_upserts_and_reactivates(session):
    result = await import_suppliers(
        [
            SupplierImportItem(supplier_code="inactive", supplier_name="Recovered Supplier", country="India"),
            SupplierImportItem(supplier_code="glenmark", supplier_name="Glenmark Pharmaceuticals", country="India"),
        ],
        session,
        ADMIN,
    )
    assert [(item.supplier_code, item.is_active) for item in result] == [("INACTIVE", True), ("GLENMARK", True)]
    recovered = await session.scalar(select(Supplier).where(Supplier.supplier_code == "INACTIVE"))
    assert recovered.supplier_name == "Recovered Supplier"


@pytest.mark.asyncio
async def test_duplicate_supplier_code_and_invalid_credit_days_are_rejected(session):
    with pytest.raises(Exception) as duplicate:
        await create_supplier(SupplierCreate(supplier_code="cipla", supplier_name="Another"), session, ADMIN)
    assert "already exists" in str(duplicate.value)
    with pytest.raises(Exception) as invalid:
        await create_supplier(SupplierCreate(supplier_code="bad", supplier_name="Bad", credit_days=-1), session, ADMIN)
    assert "credit_days" in str(invalid.value)


@pytest.mark.asyncio
async def test_supplier_role_boundary_is_explicit():
    from app.core.dependencies import require_role

    read_check = require_role("pharmacist", "store_manager", "hospital_admin")
    write_check = require_role("store_manager", "hospital_admin")
    assert await read_check(PHARMACIST) == PHARMACIST
    with pytest.raises(Exception):
        await write_check(PHARMACIST)


def test_supplier_table_contract():
    columns = Supplier.__table__.c
    assert {"supplier_code", "supplier_name", "gstin", "drug_license_no", "credit_days", "is_active", "created_at", "updated_at"} <= set(columns.keys())
    assert any(constraint.name == "uq_suppliers_supplier_code" for constraint in Supplier.__table__.constraints)
