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
    create_dosage_form,
    create_route,
    deactivate_dosage_form,
    deactivate_route,
    import_dosage_forms,
    import_routes,
    search_dosage_forms,
    search_routes,
    update_dosage_form,
    update_route,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.route import Route
from app.schemas.master_data import (
    DosageFormCreate,
    DosageFormImportItem,
    DosageFormUpdate,
    RouteCreate,
    RouteImportItem,
    RouteUpdate,
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
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[DosageForm.__table__, Route.__table__, AuditLog.__table__],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        current.add_all([
            DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT"),
            DosageForm(code="OLD_FORM", name="Old form", calculation_type="MANUAL", is_active=False),
            Route(code="ORAL", name="Oral"),
            Route(code="OLD_ROUTE", name="Old route", is_active=False),
        ])
        await current.commit()
        yield current
    await engine.dispose()


@pytest.mark.asyncio
async def test_dosage_form_search_and_inactive_filter(session):
    assert [item.code for item in await search_dosage_forms("tablet", 20, session, DOCTOR)] == ["TABLET"]
    assert [item.code for item in await search_dosage_forms("unit", 20, session, DOCTOR)] == ["TABLET"]
    assert all(item.code != "OLD_FORM" for item in await search_dosage_forms("", 100, session, DOCTOR))


@pytest.mark.asyncio
async def test_route_search_and_inactive_filter(session):
    assert [item.code for item in await search_routes("oral", 20, session, DOCTOR)] == ["ORAL"]
    assert all(item.code != "OLD_ROUTE" for item in await search_routes("", 100, session, DOCTOR))


@pytest.mark.asyncio
async def test_dosage_form_crud_deactivate_and_audit(session):
    created = await create_dosage_form(
        DosageFormCreate(code=" syrup ", name=" Syrup ", calculation_type="LIQUID"),
        session,
        ADMIN,
    )
    assert (created.code, created.name, created.calculation_type) == ("SYRUP", "Syrup", "LIQUID")
    updated = await update_dosage_form(created.id, DosageFormUpdate(description="Measured in mL"), session, ADMIN)
    assert updated.description == "Measured in mL"
    deactivated = await deactivate_dosage_form(created.id, session, ADMIN)
    assert deactivated.is_active is False
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(created.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_route_crud_deactivate_and_audit(session):
    created = await create_route(RouteCreate(code=" i.v. ", name=" Intravenous "), session, ADMIN)
    assert (created.code, created.name) == ("I.V.", "Intravenous")
    updated = await update_route(created.id, RouteUpdate(description="Injection route"), session, ADMIN)
    assert updated.description == "Injection route"
    deactivated = await deactivate_route(created.id, session, ADMIN)
    assert deactivated.is_active is False
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.resource_id == str(created.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_import_upserts_and_reactivates_both_masters(session):
    dosage_forms = await import_dosage_forms(
        [DosageFormImportItem(code="old_form", name="Recovered form", calculation_type="PRN")],
        session,
        ADMIN,
    )
    routes = await import_routes(
        [RouteImportItem(code="old_route", name="Recovered route")],
        session,
        ADMIN,
    )
    assert (dosage_forms[0].code, dosage_forms[0].calculation_type, dosage_forms[0].is_active) == ("OLD_FORM", "PRN", True)
    assert (routes[0].code, routes[0].name, routes[0].is_active) == ("OLD_ROUTE", "Recovered route", True)


@pytest.mark.asyncio
async def test_duplicate_codes_are_rejected(session):
    with pytest.raises(Exception) as dosage_error:
        await create_dosage_form(DosageFormCreate(code="tablet", name="Another", calculation_type="UNIT"), session, ADMIN)
    with pytest.raises(Exception) as route_error:
        await create_route(RouteCreate(code="oral", name="Another"), session, ADMIN)
    assert "already exists" in str(dosage_error.value)
    assert "already exists" in str(route_error.value)


def test_dosage_form_calculation_type_is_controlled():
    with pytest.raises(ValidationError):
        DosageFormCreate(code="INJECTION", name="Injection", calculation_type="AUTOMATIC")
    assert DosageFormCreate(code="INJECTION", name="Injection", calculation_type="MANUAL").calculation_type == "MANUAL"
