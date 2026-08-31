import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.master_data import (
    create_medicine_product,
    deactivate_medicine_product,
    import_medicine_products,
    search_medicine_products,
    update_medicine_product,
)
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.route import Route
from app.schemas.master_data import (
    MedicineProductCreate,
    MedicineProductImportItem,
    MedicineProductUpdate,
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
                GenericMedicine.__table__,
                DosageForm.__table__,
                Route.__table__,
                Manufacturer.__table__,
                MedicineProduct.__table__,
                AuditLog.__table__,
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol", therapeutic_class="Analgesic")
        form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        route = Route(code="ORAL", name="Oral")
        manufacturer = Manufacturer(code="CIPLA", name="Cipla Limited", country="India")
        inactive_generic = GenericMedicine(code="INACTIVE", name="Inactive generic", is_active=False)
        current.add_all([generic, form, route, manufacturer, inactive_generic])
        await current.commit()
        yield current, generic, form, route, manufacturer, inactive_generic
    await engine.dispose()


def product_payload(*, generic_id, form_id, route_id, manufacturer_id, code="PCM-500-TAB"):
    return MedicineProductCreate(
        code=code,
        generic_medicine_id=generic_id,
        brand_name="Dolo",
        strength="500",
        unit="mg",
        dosage_form_id=form_id,
        default_route_id=route_id,
        manufacturer_id=manufacturer_id,
        composition="Paracetamol 500 mg",
        hsn_code="30049099",
        gst_rate=Decimal("12.00"),
        schedule_category="OTC",
        is_controlled_drug=False,
        requires_prescription=False,
    )


@pytest.mark.asyncio
async def test_product_search_matches_code_brand_strength_and_composition(session):
    current, generic, form, route, manufacturer, _ = session
    product = await create_medicine_product(product_payload(generic_id=generic.id, form_id=form.id, route_id=route.id, manufacturer_id=manufacturer.id), current, ADMIN)
    assert product.code == "PCM-500-TAB"
    assert [item.code for item in await search_medicine_products("dolo", 20, current, DOCTOR)] == [product.code]
    assert [item.code for item in await search_medicine_products("paracetamol 500", 20, current, DOCTOR)] == [product.code]
    assert await search_medicine_products("", 20, current, DOCTOR)


@pytest.mark.asyncio
async def test_product_crud_deactivate_and_audit(session):
    current, generic, form, route, manufacturer, _ = session
    product = await create_medicine_product(product_payload(generic_id=generic.id, form_id=form.id, route_id=route.id, manufacturer_id=manufacturer.id), current, ADMIN)
    updated = await update_medicine_product(product.id, MedicineProductUpdate(gst_rate=Decimal("18.00"), is_controlled_drug=True), current, ADMIN)
    assert updated.gst_rate == Decimal("18.00")
    assert updated.is_controlled_drug is True
    deactivated = await deactivate_medicine_product(product.id, current, ADMIN)
    assert deactivated.is_active is False
    assert await search_medicine_products("dolo", 20, current, DOCTOR) == []
    actions = (await current.execute(select(AuditLog.action).where(AuditLog.resource_id == str(product.id)).order_by(AuditLog.timestamp))).scalars().all()
    assert actions == ["CREATE", "UPDATE", "DEACTIVATE"]


@pytest.mark.asyncio
async def test_product_requires_active_referenced_masters(session):
    current, _, form, route, manufacturer, inactive_generic = session
    with pytest.raises(Exception) as error:
        await create_medicine_product(product_payload(generic_id=inactive_generic.id, form_id=form.id, route_id=route.id, manufacturer_id=manufacturer.id), current, ADMIN)
    assert "Generic medicine is missing or inactive" in str(error.value)


@pytest.mark.asyncio
async def test_product_import_upserts_and_reactivates_by_code(session):
    current, generic, form, route, manufacturer, _ = session
    product = await create_medicine_product(product_payload(generic_id=generic.id, form_id=form.id, route_id=route.id, manufacturer_id=manufacturer.id), current, ADMIN)
    await deactivate_medicine_product(product.id, current, ADMIN)
    result = await import_medicine_products(
        [product_payload(generic_id=generic.id, form_id=form.id, route_id=route.id, manufacturer_id=manufacturer.id)],
        current,
        ADMIN,
    )
    assert result[0].id == product.id
    assert result[0].is_active is True


@pytest.mark.asyncio
async def test_duplicate_product_code_is_rejected(session):
    current, generic, form, route, manufacturer, _ = session
    payload = product_payload(generic_id=generic.id, form_id=form.id, route_id=route.id, manufacturer_id=manufacturer.id)
    await create_medicine_product(payload, current, ADMIN)
    with pytest.raises(Exception) as error:
        await create_medicine_product(payload.model_copy(update={"brand_name": "Another brand"}), current, ADMIN)
    assert "already exists" in str(error.value)


def test_product_regulatory_field_limits_are_validated():
    ids = {"generic_medicine_id": uuid.uuid4(), "dosage_form_id": uuid.uuid4()}
    with pytest.raises(ValidationError):
        MedicineProductCreate(code="P", **ids, hsn_code="1" * 21)
    with pytest.raises(ValidationError):
        MedicineProductCreate(code="P", **ids, gst_rate=Decimal("100.01"))
