import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.master_data import (
    create_hospital_formulary,
    create_medicine_product,
    deactivate_hospital_formulary,
    import_hospital_formulary,
    search_hospital_formulary,
    update_hospital_formulary,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.department import Department
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.route import Route
from app.schemas.master_data import (
    HospitalFormularyCreate,
    HospitalFormularyImportItem,
    HospitalFormularyUpdate,
    MedicineProductCreate,
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
            tables=[
                Department.__table__,
                GenericMedicine.__table__,
                DosageForm.__table__,
                Route.__table__,
                Manufacturer.__table__,
                MedicineProduct.__table__,
                HospitalFormulary.__table__,
                AuditLog.__table__,
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        department_a = Department(id=uuid.uuid4(), name="Outpatient")
        department_b = Department(id=uuid.uuid4(), name="Emergency")
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol")
        dosage_form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        route = Route(code="ORAL", name="Oral")
        manufacturer = Manufacturer(code="CIPLA", name="Cipla")
        current.add_all([department_a, department_b, generic, dosage_form, route, manufacturer])
        await current.commit()
        yield current, department_a, department_b, generic, dosage_form, route, manufacturer
    await engine.dispose()


def product_payload(generic_id, dosage_form_id, route_id, manufacturer_id, code="PCM-500-TAB"):
    return MedicineProductCreate(
        code=code,
        generic_medicine_id=generic_id,
        brand_name="Dolo",
        strength="500",
        unit="mg",
        dosage_form_id=dosage_form_id,
        default_route_id=route_id,
        manufacturer_id=manufacturer_id,
        composition="Paracetamol 500 mg",
        gst_rate=Decimal("12.00"),
    )


@pytest.mark.asyncio
async def test_formulary_search_filters_department_and_prescribable(session):
    current, department_a, department_b, generic, form, route, manufacturer = session
    product = await create_medicine_product(product_payload(generic.id, form.id, route.id, manufacturer.id), current, ADMIN)
    approved = await create_hospital_formulary(
        HospitalFormularyCreate(
            medicine_product_id=product.id,
            department_id=department_a.id,
            is_approved=True,
            is_prescribable=True,
            effective_date=date.today() + timedelta(days=2),
        ),
        current,
        ADMIN,
    )
    await create_hospital_formulary(
        HospitalFormularyCreate(medicine_product_id=product.id, department_id=department_b.id, is_prescribable=False),
        current,
        ADMIN,
    )
    assert [item.id for item in await search_hospital_formulary("dolo", department_a.id, False, 20, current, DOCTOR)] == [approved.id]
    assert await search_hospital_formulary("dolo", department_b.id, True, 20, current, DOCTOR) == []
    assert approved.effective_date == date.today() + timedelta(days=2)


@pytest.mark.asyncio
async def test_formulary_crud_deactivate_and_audit(session):
    current, department_a, _, generic, form, route, manufacturer = session
    product = await create_medicine_product(product_payload(generic.id, form.id, route.id, manufacturer.id), current, ADMIN)
    item = await create_hospital_formulary(HospitalFormularyCreate(medicine_product_id=product.id, department_id=department_a.id), current, ADMIN)
    updated = await update_hospital_formulary(item.id, HospitalFormularyUpdate(is_approved=True, is_preferred=True), current, ADMIN)
    assert (updated.is_approved, updated.is_preferred) == (True, True)
    deactivated = await deactivate_hospital_formulary(item.id, current, ADMIN)
    assert deactivated.is_active is False
    assert await search_hospital_formulary("", department_a.id, False, 20, current, DOCTOR) == []
    actions = (await current.execute(select(AuditLog.action).where(AuditLog.resource_id == str(item.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_formulary_references_must_be_active_and_assignment_unique(session):
    current, department_a, _, generic, form, route, manufacturer = session
    product = await create_medicine_product(product_payload(generic.id, form.id, route.id, manufacturer.id), current, ADMIN)
    payload = HospitalFormularyCreate(medicine_product_id=product.id, department_id=department_a.id)
    await create_hospital_formulary(payload, current, ADMIN)
    with pytest.raises(Exception) as duplicate_error:
        await create_hospital_formulary(payload, current, ADMIN)
    assert "already assigned" in str(duplicate_error.value)
    product.is_active = False
    await current.commit()
    with pytest.raises(Exception) as inactive_error:
        await create_hospital_formulary(HospitalFormularyCreate(medicine_product_id=product.id, department_id=uuid.uuid4()), current, ADMIN)
    assert "Medicine product is missing or inactive" in str(inactive_error.value)


@pytest.mark.asyncio
async def test_formulary_import_upserts_and_reactivates(session):
    current, department_a, _, generic, form, route, manufacturer = session
    product = await create_medicine_product(product_payload(generic.id, form.id, route.id, manufacturer.id), current, ADMIN)
    payload = HospitalFormularyImportItem(medicine_product_id=product.id, department_id=department_a.id, is_approved=True)
    created = await import_hospital_formulary([payload], current, ADMIN)
    await deactivate_hospital_formulary(created[0].id, current, ADMIN)
    result = await import_hospital_formulary([payload], current, ADMIN)
    assert result[0].id == created[0].id
    assert result[0].is_active is True
    assert result[0].is_approved is True
