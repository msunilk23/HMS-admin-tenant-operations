import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.master_data import (
    create_manufacturer,
    deactivate_manufacturer,
    import_manufacturers,
    search_manufacturers,
    update_manufacturer,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.manufacturer import Manufacturer
from app.schemas.master_data import (
    ManufacturerCreate,
    ManufacturerImportItem,
    ManufacturerUpdate,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


ADMIN = {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": "tenant_a"}
DOCTOR = {"sub": str(uuid.uuid4()), "role": "doctor", "tenant_schema": "tenant_a"}


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Manufacturer.__table__, AuditLog.__table__])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        current.add_all([
            Manufacturer(code="CIPLA", name="Cipla Limited", gstin="27AAACC1457E1Z2", country="India"),
            Manufacturer(code="INACTIVE", name="Inactive manufacturer", is_active=False),
        ])
        await current.commit()
        yield current
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_matches_code_and_name_and_excludes_inactive(session):
    assert [item.code for item in await search_manufacturers("cipla", 20, session, DOCTOR)] == ["CIPLA"]
    assert [item.code for item in await search_manufacturers("limited", 20, session, DOCTOR)] == ["CIPLA"]
    assert all(item.code != "INACTIVE" for item in await search_manufacturers("", 100, session, DOCTOR))


@pytest.mark.asyncio
async def test_create_update_deactivate_and_audit(session):
    created = await create_manufacturer(
        ManufacturerCreate(code=" sun ", name=" Sun Pharma ", gstin="24AAACS3126R1ZQ", country="India"),
        session,
        ADMIN,
    )
    assert (created.code, created.name, created.gstin) == ("SUN", "Sun Pharma", "24AAACS3126R1ZQ")

    updated = await update_manufacturer(
        created.id,
        ManufacturerUpdate(country="India", gstin=None),
        session,
        ADMIN,
    )
    assert updated.gstin is None

    deactivated = await deactivate_manufacturer(created.id, session, ADMIN)
    assert deactivated.is_active is False
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(created.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_import_upserts_and_reactivates_by_code(session):
    result = await import_manufacturers(
        [
            ManufacturerImportItem(code="inactive", name="Recovered manufacturer", country="India"),
            ManufacturerImportItem(code="dr_reddys", name="Dr. Reddy's Laboratories", country="India"),
        ],
        session,
        ADMIN,
    )
    assert [(item.code, item.is_active) for item in result] == [("INACTIVE", True), ("DR_REDDYS", True)]
    recovered = await session.scalar(select(Manufacturer).where(Manufacturer.code == "INACTIVE"))
    assert recovered.name == "Recovered manufacturer"


@pytest.mark.asyncio
async def test_duplicate_code_is_rejected(session):
    with pytest.raises(Exception) as error:
        await create_manufacturer(ManufacturerCreate(code="cipla", name="Another Cipla"), session, ADMIN)
    assert "already exists" in str(error.value)


def test_manufacturer_field_lengths_are_validated():
    with pytest.raises(ValidationError):
        ManufacturerCreate(code="A", name="A", gstin="1" * 16)
    with pytest.raises(ValidationError):
        ManufacturerCreate(code="A", name="A", country="I" * 101)
