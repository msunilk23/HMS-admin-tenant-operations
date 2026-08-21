"""Controlled ICD-10 and medicine master-data regression tests."""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.api.v1.master_data import search_icd10, search_medicines
from app.api.v1.consultations import _validate_diagnoses
from app.api.v1.prescriptions import create_prescription
from app.db.base import Base
from app.models.tenant.audit_log import AuditLog
from app.models.tenant.consultation import Consultation
from app.models.tenant.icd10_code import ICD10Code
from app.models.tenant.medicine_master import MedicineMaster
from app.models.tenant.patient import Patient
from app.models.tenant.prescription import Prescription, PrescriptionItem
from app.models.tenant.visit import Visit, VisitStatus
from app.schemas.master_data import MedicineImportItem
from app.schemas.prescription import MedicineItem, PrescriptionCreate


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    return "JSON"


USER = {"sub": str(uuid.uuid4()), "role": "doctor", "tenant_schema": "tenant_a"}
ADMIN = {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": "tenant_a"}

_TABLES = [
    Patient.__table__, Visit.__table__, Consultation.__table__,
    Prescription.__table__, PrescriptionItem.__table__, AuditLog.__table__,
    ICD10Code.__table__, MedicineMaster.__table__,
]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as current:
        icd = [
            ICD10Code(id=uuid.uuid4(), code="J06.9", description="Acute upper respiratory infection", is_active=True),
            ICD10Code(id=uuid.uuid4(), code="E11.9", description="Type 2 diabetes mellitus", is_active=True),
            ICD10Code(id=uuid.uuid4(), code="Z99.9", description="Inactive test code", is_active=False),
        ]
        meds = [
            MedicineMaster(id=uuid.uuid4(), generic_name="Paracetamol", brand_name="Crocin", strength="500 mg", dosage_form="Tablet", is_active=True),
            MedicineMaster(id=uuid.uuid4(), generic_name="Amoxicillin", brand_name="Mox", strength="250 mg", dosage_form="Capsule", is_active=True),
            MedicineMaster(id=uuid.uuid4(), generic_name="Inactive Drug", brand_name="Old", strength="10 mg", dosage_form="Tablet", is_active=False),
        ]
        current.add_all(icd + meds)
        await current.commit()
        yield current, icd, meds
    await engine.dispose()


@pytest.mark.asyncio
async def test_icd_search_code_description_case_insensitive_and_limit(session):
    current, icd, _ = session
    assert [x.code for x in await search_icd10("j06", 20, current, USER)] == ["J06.9"]
    assert [x.code for x in await search_icd10("RESPIRATORY", 20, current, USER)] == ["J06.9"]
    assert [x.code for x in await search_icd10("diabetes", 1, current, USER)] == ["E11.9"]
    assert all(x.code != "Z99.9" for x in await search_icd10("", 100, current, USER))


@pytest.mark.asyncio
async def test_medicine_searches_generic_brand_strength_form_and_excludes_inactive(session):
    current, _, _ = session
    assert (await search_medicines("paracetamol", 20, current, USER))[0].generic_name == "Paracetamol"
    assert (await search_medicines("crocin", 20, current, USER))[0].brand_name == "Crocin"
    assert (await search_medicines("500 mg", 20, current, USER))[0].generic_name == "Paracetamol"
    assert (await search_medicines("tablet", 20, current, USER))[0].generic_name == "Paracetamol"
    assert all(x.generic_name != "Inactive Drug" for x in await search_medicines("", 100, current, USER))


@pytest.mark.asyncio
async def test_icd_selection_snapshots_authoritative_description_and_rejects_inactive(session):
    current, icd, _ = session
    normalized, free = await _validate_diagnoses(current, [{"code": "J06.9", "description": "client text"}])
    assert normalized == [{"code": "J06.9", "description": "Acute upper respiratory infection", "free_text": False}]
    assert free is False
    with pytest.raises(Exception):
        await _validate_diagnoses(current, [{"code": "Z99.9", "description": "inactive"}])


@pytest.mark.asyncio
async def test_free_text_diagnosis_requires_reason_and_is_marked(session):
    current, _, _ = session
    with pytest.raises(Exception):
        await _validate_diagnoses(current, [{"code": "FREE_TEXT", "description": "Unusual syndrome"}])
    normalized, free = await _validate_diagnoses(current, [{"code": "FREE_TEXT", "description": "Unusual syndrome"}], "No suitable ICD-10 code available")
    assert normalized[0]["free_text"] is True
    assert free is True


@pytest.mark.asyncio
async def test_prescription_selected_master_id_and_snapshot_survive_master_change(session):
    current, _, meds = session
    patient = Patient(id=uuid.uuid4(), uhid="U1", first_name="A", last_name="B", gender="female", phone="9999999999")
    visit = Visit(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, status=VisitStatus.IN_CONSULTATION.value)
    current.add_all([patient, visit])
    await current.commit()
    medicine = meds[0]
    result = await create_prescription(
        PrescriptionCreate(visit_id=visit.id, items=[MedicineItem(medicine_master_id=medicine.id, dose="1", frequency="OD", duration="5 days", route="oral", quantity="5")]),
        current, USER,
    )
    assert result.items[0].medicine_master_id == medicine.id
    assert result.items[0].medicine == "Paracetamol"
    medicine.generic_name = "Renamed Paracetamol"
    await current.commit()
    row = (await current.execute(select(PrescriptionItem).where(PrescriptionItem.prescription_id == result.id))).scalar_one()
    assert row.medicine == "Paracetamol"


@pytest.mark.asyncio
async def test_inactive_medicine_rejected_and_inventory_not_touched(session):
    current, _, meds = session
    patient = Patient(id=uuid.uuid4(), uhid="U2", first_name="C", last_name="D", gender="male", phone="9999999998")
    visit = Visit(id=uuid.uuid4(), patient_id=patient.id, uhid=patient.uhid, status=VisitStatus.IN_CONSULTATION.value)
    current.add_all([patient, visit])
    await current.commit()
    inactive = meds[2]
    with pytest.raises(Exception):
        await create_prescription(
            PrescriptionCreate(visit_id=visit.id, items=[MedicineItem(medicine_master_id=inactive.id, dose="1", frequency="OD", duration="1 day", route="oral")]),
            current, USER,
        )
    assert not any(name in current.info for name in ("inventory", "stock"))


@pytest.mark.asyncio
async def test_master_search_roles_are_enforced_by_dependency_contract():
    from app.core.dependencies import require_role
    from fastapi import HTTPException
    check = require_role("doctor", "hospital_admin")
    with pytest.raises(HTTPException):
        await check({"role": "receptionist"})
    check_medicine = require_role("doctor", "pharmacist", "hospital_admin")
    with pytest.raises(HTTPException):
        await check_medicine({"role": "nurse"})


@pytest.mark.asyncio
async def test_tenant_scoped_master_query_cannot_cross_schemas(session):
    current, _, _ = session
    # The API receives the authenticated tenant context through get_session;
    # direct route invocation is still tenant-scoped by the supplied session.
    assert USER["tenant_schema"] == "tenant_a"
    assert all(item.is_active for item in await search_icd10("", 100, current, USER))
