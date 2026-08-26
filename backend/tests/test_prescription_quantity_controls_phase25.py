import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.prescriptions import create_prescription
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.route import Route
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.prescription import MedicineItem, PrescriptionCreate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


DOCTOR = {"sub": str(uuid.uuid4()), "role": "doctor", "tenant_schema": "tenant_a"}


@pytest_asyncio.fixture
async def quantity_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Patient.__table__,
                Visit.__table__,
                Prescription.__table__,
                PrescriptionItem.__table__,
                AuditLog.__table__,
                GenericMedicine.__table__,
                DosageForm.__table__,
                Route.__table__,
                MedicineProduct.__table__,
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol")
        form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        route = Route(code="ORAL", name="Oral")
        session.add_all([generic, form, route])
        await session.flush()
        product = MedicineProduct(
            code="PCM-500",
            generic_medicine_id=generic.id,
            brand_name="Dolo",
            strength="500",
            unit="mg",
            dosage_form_id=form.id,
            default_route_id=route.id,
        )
        session.add(product)
        await session.commit()
        yield session, product
    await engine.dispose()


async def add_visit(session: AsyncSession, suffix: str) -> Visit:
    patient = Patient(id=uuid.uuid4(), uhid=f"Q-{suffix}", first_name="Quantity", last_name=suffix, gender="female", phone="9999999999")
    visit = Visit(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, status=VisitStatus.CONSULTATION_COMPLETED.value)
    session.add_all([patient, visit])
    await session.commit()
    return visit


async def make_prescription(session, product, suffix: str, **item_values):
    visit = await add_visit(session, suffix)
    values = {
        "medicine_product_id": product.id,
        "dose": "1",
        "frequency": "BD",
        "duration": "5 days",
        "route": "oral",
    }
    values.update(item_values)
    item = MedicineItem(**values)
    return await create_prescription(PrescriptionCreate(visit_id=visit.id, items=[item]), session, DOCTOR)


@pytest.mark.asyncio
async def test_unit_quantity_is_calculated_and_used_when_not_supplied(quantity_context):
    session, product = quantity_context
    result = await make_prescription(session, product, "auto", quantity=None)
    item = result.items[0]
    assert item.auto_quantity == "10"
    assert item.final_quantity == "10"
    assert item.quantity == "10"
    assert item.quantity_override_flag is False


@pytest.mark.asyncio
async def test_decimal_maen_dose_is_calculated(quantity_context):
    session, product = quantity_context
    result = await make_prescription(session, product, "decimal", dose="½", frequency="1-0-1-0", quantity=None)
    assert result.items[0].auto_quantity == "5"
    assert result.items[0].final_quantity == "5"


@pytest.mark.asyncio
async def test_ongoing_duration_does_not_auto_calculate(quantity_context):
    session, product = quantity_context
    result = await make_prescription(session, product, "ongoing", duration="Ongoing", quantity="30")
    item = result.items[0]
    assert item.auto_quantity is None
    assert item.final_quantity == "30"
    assert item.quantity_override_flag is False


@pytest.mark.asyncio
async def test_quantity_override_requires_reason_and_is_audited(quantity_context):
    session, product = quantity_context
    visit = await add_visit(session, "override-rejected")
    with pytest.raises(Exception) as error:
        await create_prescription(
            PrescriptionCreate(
                visit_id=visit.id,
                items=[MedicineItem(medicine_product_id=product.id, dose="1", frequency="BD", duration="5 days", quantity="11", route="oral")],
            ),
            session,
            DOCTOR,
        )
    assert "Reason required" in str(error.value)

    result = await make_prescription(session, product, "override-accepted", quantity="11", quantity_override_reason="Patient supplied a different pack size")
    item = result.items[0]
    assert item.auto_quantity == "10"
    assert item.final_quantity == "11"
    assert item.quantity == "11"
    assert item.quantity_override_flag is True
    assert item.quantity_override_reason == "Patient supplied a different pack size"
    audit = (await session.execute(select(AuditLog).where(AuditLog.resource_id == str(result.id)))).scalar_one()
    assert audit.new_value["medicines"][0]["quantity_override_flag"] is True
    assert audit.new_value["medicines"][0]["quantity_override_reason"] == "Patient supplied a different pack size"


@pytest.mark.asyncio
async def test_preset_frequency_mapping_is_calculated(quantity_context):
    session, product = quantity_context
    result = await make_prescription(session, product, "tid", frequency="TID", quantity=None)
    assert result.items[0].auto_quantity == "15"
