import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.master_data import (
    create_generic_medicine,
    deactivate_generic_medicine,
    import_generic_medicines,
    search_generic_medicines,
    update_generic_medicine,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.generic_medicine import GenericMedicine
from app.schemas.master_data import (
    GenericMedicineCreate,
    GenericMedicineImportItem,
    GenericMedicineUpdate,
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
        await conn.run_sync(Base.metadata.create_all, tables=[GenericMedicine.__table__, AuditLog.__table__])
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        current.add_all([
            GenericMedicine(code="PARACETAMOL", name="Paracetamol", therapeutic_class="Analgesic"),
            GenericMedicine(code="INACTIVE", name="Inactive medicine", is_active=False),
        ])
        await current.commit()
        yield current
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_matches_code_name_and_therapeutic_class_and_excludes_inactive(session):
    assert [item.code for item in await search_generic_medicines("para", 20, session, DOCTOR)] == ["PARACETAMOL"]
    assert [item.code for item in await search_generic_medicines("analgesic", 20, session, DOCTOR)] == ["PARACETAMOL"]
    assert all(item.code != "INACTIVE" for item in await search_generic_medicines("", 100, session, DOCTOR))


@pytest.mark.asyncio
async def test_create_update_and_deactivate_are_audited(session):
    created = await create_generic_medicine(
        GenericMedicineCreate(code=" amoxicillin ", name=" Amoxicillin ", therapeutic_class="Antibiotic"),
        session,
        ADMIN,
    )
    assert created.code == "AMOXICILLIN"
    assert created.name == "Amoxicillin"

    updated = await update_generic_medicine(
        created.id,
        GenericMedicineUpdate(description="Broad-spectrum antibiotic"),
        session,
        ADMIN,
    )
    assert updated.description == "Broad-spectrum antibiotic"

    deactivated = await deactivate_generic_medicine(created.id, session, ADMIN)
    assert deactivated.is_active is False
    assert await session.scalar(select(GenericMedicine).where(GenericMedicine.id == created.id, GenericMedicine.is_active.is_(True))) is None

    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(created.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_import_upserts_and_reactivates_by_code(session):
    result = await import_generic_medicines(
        [
            GenericMedicineImportItem(code="inactive", name="Recovered medicine", therapeutic_class="Other"),
            GenericMedicineImportItem(code="ibuprofen", name="Ibuprofen", therapeutic_class="NSAID"),
        ],
        session,
        ADMIN,
    )
    assert [(item.code, item.is_active) for item in result] == [("INACTIVE", True), ("IBUPROFEN", True)]
    assert (await session.scalar(select(GenericMedicine).where(GenericMedicine.code == "INACTIVE"))).name == "Recovered medicine"


@pytest.mark.asyncio
async def test_duplicate_code_is_rejected(session):
    with pytest.raises(Exception) as error:
        await create_generic_medicine(
            GenericMedicineCreate(code="paracetamol", name="Another Paracetamol"),
            session,
            ADMIN,
        )
    assert "already exists" in str(error.value)
