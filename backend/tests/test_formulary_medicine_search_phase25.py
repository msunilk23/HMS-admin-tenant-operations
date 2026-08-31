import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.pharmacy import search_formulary_medicines
from app.db.base import Base
from app.models.tenant.department import Department
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.route import Route
from app.schemas.master_data import MedicineProductCreate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


DOCTOR = {"sub": str(uuid.uuid4()), "role": "doctor", "tenant_schema": "tenant_a"}


def _business_date():
    return datetime.now(timezone.utc).date()


@pytest_asyncio.fixture
async def search_context():
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
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        department_a = Department(id=uuid.uuid4(), name="Outpatient")
        department_b = Department(id=uuid.uuid4(), name="Emergency")
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol")
        dosage_form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        route = Route(code="ORAL", name="Oral")
        manufacturer = Manufacturer(code="CIPLA", name="Cipla")
        session.add_all([department_a, department_b, generic, dosage_form, route, manufacturer])
        await session.flush()

        product = MedicineProduct(
            id=uuid.uuid4(),
            code="PCM-500-TAB",
            generic_medicine_id=generic.id,
            brand_name="Dolo",
            strength="500",
            unit="mg",
            dosage_form_id=dosage_form.id,
            default_route_id=route.id,
            manufacturer_id=manufacturer.id,
            composition="Paracetamol 500 mg",
            gst_rate=Decimal("12.00"),
        )
        inactive_product = MedicineProduct(
            id=uuid.uuid4(),
            code="PCM-INACTIVE",
            generic_medicine_id=generic.id,
            brand_name="Inactive Dolo",
            dosage_form_id=dosage_form.id,
            is_active=False,
        )
        session.add_all([product, inactive_product])
        await session.flush()
        session.add_all([
            HospitalFormulary(
                id=uuid.uuid4(),
                medicine_product_id=product.id,
                department_id=department_a.id,
                is_approved=True,
                is_preferred=True,
                is_prescribable=True,
            ),
            HospitalFormulary(
                id=uuid.uuid4(),
                medicine_product_id=product.id,
                department_id=department_b.id,
                is_approved=True,
                is_prescribable=False,
            ),
            HospitalFormulary(
                id=uuid.uuid4(),
                medicine_product_id=inactive_product.id,
                department_id=department_a.id,
                is_approved=True,
                is_prescribable=True,
            ),
        ])
        await session.commit()
        yield session, department_a, department_b, product
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_returns_current_approved_prescribable_product_metadata(search_context):
    session, department_a, _, product = search_context
    result = await search_formulary_medicines(
        q="paracetamol", department_id=department_a.id, prescribable_only=True, limit=20, session=session, _=DOCTOR
    )
    assert len(result) == 1
    item = result[0]
    assert item.medicine_product_id == product.id
    assert item.code == "PCM-500-TAB"
    assert item.generic_name == "Paracetamol"
    assert item.brand_name == "Dolo"
    assert item.dosage_form_name == "Tablet"
    assert item.default_route_name == "Oral"
    assert item.is_approved is True
    assert item.is_prescribable is True
    assert not hasattr(item, "stock_quantity")
    assert not hasattr(item, "inventory_quantity")


@pytest.mark.asyncio
async def test_search_matches_brand_and_composition_and_filters_department(search_context):
    session, department_a, department_b, product = search_context
    by_brand = await search_formulary_medicines("dolo", department_a.id, True, 20, session, DOCTOR)
    by_composition = await search_formulary_medicines("500 mg", department_a.id, True, 20, session, DOCTOR)
    assert [item.medicine_product_id for item in by_brand] == [product.id]
    assert [item.medicine_product_id for item in by_composition] == [product.id]
    assert await search_formulary_medicines("dolo", department_b.id, True, 20, session, DOCTOR) == []
    assert len(await search_formulary_medicines("dolo", department_b.id, False, 20, session, DOCTOR)) == 1


@pytest.mark.asyncio
async def test_search_excludes_future_expired_unapproved_and_inactive_records(search_context):
    session, department_a, _, product = search_context
    current_entry = await session.scalar(
        select(HospitalFormulary).where(
            HospitalFormulary.medicine_product_id == product.id,
            HospitalFormulary.department_id == department_a.id,
            HospitalFormulary.is_approved.is_(True),
        )
    )
    current_entry.effective_date = _business_date() + timedelta(days=1)
    await session.commit()
    assert await search_formulary_medicines("", department_a.id, True, 20, session, DOCTOR) == []
    current_entry.effective_date = None
    current_entry.expiry_date = _business_date() - timedelta(days=1)
    await session.commit()
    assert await search_formulary_medicines("", department_a.id, True, 20, session, DOCTOR) == []


@pytest.mark.asyncio
async def test_search_applies_limit(search_context):
    session, department_a, _, product = search_context
    second_product = MedicineProduct(
        id=uuid.uuid4(),
        code="PCM-650-TAB",
        generic_medicine_id=product.generic_medicine_id,
        brand_name="Crocin",
        dosage_form_id=product.dosage_form_id,
        is_active=True,
    )
    session.add(second_product)
    await session.flush()
    session.add(HospitalFormulary(medicine_product_id=second_product.id, department_id=department_a.id, is_approved=True, is_prescribable=True))
    await session.commit()
    result = await search_formulary_medicines("", department_a.id, True, 1, session, DOCTOR)
    assert len(result) == 1
