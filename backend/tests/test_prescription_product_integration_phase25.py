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
from app.models.tenant.consultation import Consultation
from app.models.tenant.department import Department
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_master import MedicineMaster
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.route import Route
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.prescription import MedicineItem, PrescriptionCreate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


DOCTOR_USER = {"sub": str(uuid.uuid4()), "role": "doctor", "tenant_schema": "tenant_a"}


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
                Patient.__table__,
                Visit.__table__,
                Consultation.__table__,
                Prescription.__table__,
                PrescriptionItem.__table__,
                AuditLog.__table__,
                MedicineMaster.__table__,
                GenericMedicine.__table__,
                DosageForm.__table__,
                Route.__table__,
                Manufacturer.__table__,
                MedicineProduct.__table__,
            ],
        )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        generic = GenericMedicine(code="PARACETAMOL", name="Paracetamol")
        form = DosageForm(code="TABLET", name="Tablet", calculation_type="UNIT")
        route = Route(code="ORAL", name="Oral")
        manufacturer = Manufacturer(code="CIPLA", name="Cipla")
        current.add_all([generic, form, route, manufacturer])
        await current.flush()
        product = MedicineProduct(
            code="DOLO-500",
            generic_medicine_id=generic.id,
            brand_name="Dolo",
            strength="500",
            unit="mg",
            dosage_form_id=form.id,
            default_route_id=route.id,
            manufacturer_id=manufacturer.id,
            composition="Paracetamol 500 mg",
        )
        legacy = MedicineMaster(generic_name="Legacy Paracetamol", brand_name="Legacy Brand", strength="500 mg", dosage_form="Tablet")
        current.add_all([product, legacy])
        await current.commit()
        yield current, product, generic, form, route, legacy
    await engine.dispose()


async def add_visit(session: AsyncSession, suffix: str) -> Visit:
    patient = Patient(id=uuid.uuid4(), uhid=f"P-{suffix}", first_name="Test", last_name=suffix, gender="female", phone="9999999999")
    visit = Visit(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, status=VisitStatus.CONSULTATION_COMPLETED.value)
    session.add_all([patient, visit])
    await session.commit()
    return visit


@pytest.mark.asyncio
async def test_product_selection_populates_id_and_authoritative_snapshots(session):
    current, product, generic, form, route, _ = session
    visit = await add_visit(current, "product")
    result = await create_prescription(
        PrescriptionCreate(
            visit_id=visit.id,
            items=[MedicineItem(medicine_product_id=product.id, dose="1", frequency="BD", duration="5 days", quantity="10", route="oral")],
        ),
        current,
        DOCTOR_USER,
    )
    item = result.items[0]
    assert item.medicine_product_id == product.id
    assert item.medicine == "Dolo"
    assert item.generic_name_snapshot == "Paracetamol"
    assert item.brand_name_snapshot == "Dolo"
    assert item.strength_snapshot == "500"
    assert item.dosage_form_snapshot == "Tablet"
    assert item.route_snapshot == "Oral"
    assert item.quantity == "10"
    assert item.frequency == "BD"

    generic.name = "Changed Generic"
    product.brand_name = "Changed Brand"
    form.name = "Changed Form"
    route.name = "Changed Route"
    await current.commit()
    stored = (await current.execute(select(PrescriptionItem).where(PrescriptionItem.id == item.id))).scalar_one()
    assert (stored.generic_name_snapshot, stored.brand_name_snapshot, stored.dosage_form_snapshot, stored.route_snapshot) == ("Paracetamol", "Dolo", "Tablet", "Oral")


@pytest.mark.asyncio
async def test_unselected_medicine_requires_explicit_free_text_reason(session):
    current, _, _, _, _, _ = session
    visit = await add_visit(current, "free")
    with pytest.raises(Exception) as error:
        await create_prescription(
            PrescriptionCreate(visit_id=visit.id, items=[MedicineItem(medicine="Unlisted medicine", dose="1", frequency="OD", duration="1 day", quantity="1")]),
            current,
            DOCTOR_USER,
        )
    assert "free-text" in str(error.value)

    result = await create_prescription(
        PrescriptionCreate(
            visit_id=visit.id,
            items=[MedicineItem(medicine="Unlisted medicine", is_free_text=True, free_text_reason="Urgent external prescription", dose="1", frequency="OD", duration="1 day", quantity="1")],
        ),
        current,
        DOCTOR_USER,
    )
    assert result.items[0].medicine == "Unlisted medicine"
    assert result.medicines[0]["is_free_text"] is True
    assert result.medicines[0]["free_text_reason"] == "Urgent external prescription"


@pytest.mark.asyncio
async def test_legacy_medicine_master_selection_remains_compatible(session):
    current, _, _, _, _, legacy = session
    visit = await add_visit(current, "legacy")
    result = await create_prescription(
        PrescriptionCreate(
            visit_id=visit.id,
            items=[MedicineItem(medicine_master_id=legacy.id, dose="1", frequency="OD", duration="1 day", quantity="1", route="oral")],
        ),
        current,
        DOCTOR_USER,
    )
    assert result.items[0].medicine_master_id == legacy.id
    assert result.items[0].medicine_product_id is None
    assert result.items[0].medicine == "Legacy Paracetamol"
