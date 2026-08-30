"""Deterministic isolated PostgreSQL fixture for the Task 7 Playwright suite."""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.base import Base
from app.models.public.tenant_feature import TenantFeature
from app.models.public.user import Tenant, User
from app.models.tenant import *  # noqa: F401,F403

SCHEMA_A = "e2e_task7"
SCHEMA_B = "e2e_task7_b"
DOCTOR_USERNAME = "e2e_doctor_task7"
DOCTOR_EMAIL = "e2e-doctor-task7@example.test"
DOCTOR_PASSWORD = "E2eDoctor@123"
RECEPTIONIST_USERNAME = "e2e_receptionist_task7"
RECEPTIONIST_EMAIL = "e2e-receptionist-task7@example.test"
RECEPTIONIST_PASSWORD = "E2eReception@123"
ADMIN_USERNAME = "e2e_admin_task7"
ADMIN_EMAIL = "e2e-admin-task7@example.test"
ADMIN_PASSWORD = "E2eAdmin@123"
PHARMACIST_USERNAME = "e2e_pharmacist_task7"
PHARMACIST_EMAIL = "e2e-pharmacist-task7@example.test"
PHARMACIST_PASSWORD = "E2ePharmacist@123"
HOSPITAL_B_DOCTOR_USERNAME = "e2e_doctor_task7_b"
HOSPITAL_B_DOCTOR_EMAIL = "e2e-doctor-task7-b@example.test"
HOSPITAL_B_DOCTOR_PASSWORD = "E2eDoctorB@123"

TENANT_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-tenant-a")
TENANT_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-tenant-b")
DOCTOR_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor")
RECEPTIONIST_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-receptionist")
ADMIN_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-admin")
PHARMACIST_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-pharmacist")
HOSPITAL_B_DOCTOR_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-b")
DOCTOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-profile")
HOSPITAL_B_DOCTOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-profile-b")
DEPARTMENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-department")
HOSPITAL_B_DEPARTMENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-department-b")
PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-patient")
PRESCRIPTION_PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-prescription-patient")
PRESCRIPTION_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-prescription-visit")
P28_PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p28-patient")
P28_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p28-visit")
HOSPITAL_B_PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-patient-b")
VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-visit")
HOSPITAL_B_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-visit-b")
ICD_URI = "https://example.test/icd10/task7"
HOSPITAL_B_ICD_URI = "https://example.test/icd10/task7/hospital-b"
MED_URI = "https://example.test/medicine/task7"
HOSPITAL_B_MED_URI = "https://example.test/medicine/task7/hospital-b"

ICD_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, ICD_URI)
ICD_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, HOSPITAL_B_ICD_URI)
MED_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, MED_URI)
MED_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, HOSPITAL_B_MED_URI)
GENERIC_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/generic/paracetamol/task7")
FORM_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/form/tablet/task7")
ROUTE_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/route/oral/task7")
MANUFACTURER_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/manufacturer/cipla/task7")
PRODUCT_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/product/dolo/task7")
PRODUCT_A_CAPSULE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/product/crocin/task7")
FORMULARY_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/formulary/dolo/task7")
FORMULARY_A_CAPSULE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/formulary/crocin/task7")
GENERIC_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/generic/cefixime/task7/hospital-b")
FORM_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/form/tablet/task7/hospital-b")
ROUTE_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/route/oral/task7/hospital-b")
MANUFACTURER_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/manufacturer/cipla/task7/hospital-b")
PRODUCT_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/product/cefixime/task7/hospital-b")
FORMULARY_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/formulary/cefixime/task7/hospital-b")
SUPPLIER_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/supplier/cipla/task7")
PO_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/purchase-order/task7")
PO_ITEM_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/purchase-order-item/task7")
PHARMACY_LOCATION_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/pharmacy-location/task7")
P28_EARLY_BATCH_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-early-batch/task7")
P28_LATER_BATCH_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-later-batch/task7")
P28_GRN_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-grn/task7")
P28_GRN_ITEM_EARLY_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-grn-item-early/task7")
P28_GRN_ITEM_LATER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-grn-item-later/task7")
P28_PRESCRIPTION_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-prescription/task7")
P28_PRESCRIPTION_ITEM_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-prescription-item/task7")
P28_QUEUE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/p28-queue/task7")
FACILITY_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-facility-a")
P30_PATIENT_SINGLE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-patient")
P30_PATIENT_MULTI_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-patient")
P30_SINGLE_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-visit")
P30_MULTI_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-visit")
P30_SINGLE_PRESCRIPTION_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-prescription")
P30_MULTI_PRESCRIPTION_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-prescription")
P30_SINGLE_ITEM_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-item")
P30_MULTI_ITEM_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-item")
P30_SINGLE_DISPENSE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-dispense")
P30_MULTI_DISPENSE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-dispense")
P30_SINGLE_BATCH_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-batch")
P30_MULTI_BATCH_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-batch-a")
P30_MULTI_BATCH_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-batch-b")
P30_SUPPLIER_BATCH_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-supplier-batch-a")
P30_SUPPLIER_BATCH_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-supplier-batch-b")
P30_LOCATION_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-location")
P30_GRN_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-grn")


def _assert_destructive_reset_allowed(database_url: str, command: str) -> None:
    allow = os.getenv("E2E_ALLOW_DESTRUCTIVE_RESET", "").lower() == "true"
    environment = os.getenv("E2E_ENVIRONMENT", "").lower()
    if environment not in {"e2e", "test"}:
        raise SystemExit(
            f"Refusing '{command}': E2E_ENVIRONMENT must be explicitly set to E2E or TEST."
        )
    if not allow:
        raise SystemExit(
            f"Refusing '{command}': set E2E_ALLOW_DESTRUCTIVE_RESET=true for explicit E2E reset operations."
        )
    lowered = database_url.lower()
    safe_hosts = ("localhost", "127.0.0.1")
    if not any(host in lowered for host in safe_hosts):
        raise SystemExit(
            f"Refusing '{command}': DATABASE_URL must target localhost/127.0.0.1 for destructive E2E reset."
        )


def _serialize_row(row):
    return {
        "id": str(row.id),
        "user_id": str(row.user_id) if row.user_id else None,
        "tenant_schema": row.tenant_schema,
        "role": row.role,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "patient_id": str(row.patient_id) if row.patient_id else None,
        "visit_id": str(row.visit_id) if row.visit_id else None,
        "request_id": row.request_id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "new_value": row.new_value,
        "old_value": row.old_value,
        "reason": row.reason,
        "request_metadata": row.request_metadata,
    }


def _tables():
    return [table for table in Base.metadata.sorted_tables if table.schema is None]


async def seed():
    from app.core.config import settings
    _assert_destructive_reset_allowed(settings.DATABASE_URL, "seed")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_A}" CASCADE'))
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_B}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA_A}"'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA_B}"'))
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_tables(), checkfirst=False))
        await conn.execute(text(f'SET search_path TO "{SCHEMA_B}", public'))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_tables(), checkfirst=False))
        await conn.execute(text('DELETE FROM public.users WHERE id IN (:doctor_id, :receptionist_id, :admin_id, :pharmacist_id, :doctor_b_id) OR username IN (:doctor_username, :receptionist_username, :admin_username, :pharmacist_username, :doctor_b_username)'), {
            "doctor_id": DOCTOR_USER_ID,
            "receptionist_id": RECEPTIONIST_USER_ID,
            "admin_id": ADMIN_USER_ID,
            "pharmacist_id": PHARMACIST_USER_ID,
            "doctor_b_id": HOSPITAL_B_DOCTOR_USER_ID,
            "doctor_username": DOCTOR_USERNAME,
            "receptionist_username": RECEPTIONIST_USERNAME,
            "admin_username": ADMIN_USERNAME,
            "pharmacist_username": PHARMACIST_USERNAME,
            "doctor_b_username": HOSPITAL_B_DOCTOR_USERNAME,
        })
        await conn.execute(text('DELETE FROM public.tenants WHERE id IN (:id_a, :id_b) OR schema_name IN (:schema_a, :schema_b)'), {
            "id_a": TENANT_A_ID,
            "id_b": TENANT_B_ID,
            "schema_a": SCHEMA_A,
            "schema_b": SCHEMA_B,
        })
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.execute(text('SET search_path TO public'))
        tenant_a = Tenant(id=TENANT_A_ID, schema_name=SCHEMA_A, hospital_name="E2E Task 7 Hospital A", contact_email="e2e-task7-a@example.test", display_token=f"e2e-a-{uuid.uuid4().hex}")
        tenant_b = Tenant(id=TENANT_B_ID, schema_name=SCHEMA_B, hospital_name="E2E Task 7 Hospital B", contact_email="e2e-task7-b@example.test", display_token=f"e2e-b-{uuid.uuid4().hex}")
        user_a = User(id=DOCTOR_USER_ID, tenant_id=TENANT_A_ID, tenant_name=SCHEMA_A, email=DOCTOR_EMAIL, username=DOCTOR_USERNAME, hashed_password=hash_password(DOCTOR_PASSWORD), full_name="E2E Doctor A", role="doctor", is_active=True, must_change_password=False)
        receptionist_a = User(id=RECEPTIONIST_USER_ID, tenant_id=TENANT_A_ID, tenant_name=SCHEMA_A, email=RECEPTIONIST_EMAIL, username=RECEPTIONIST_USERNAME, hashed_password=hash_password(RECEPTIONIST_PASSWORD), full_name="E2E Receptionist A", role="receptionist", is_active=True, must_change_password=False)
        admin_a = User(id=ADMIN_USER_ID, tenant_id=TENANT_A_ID, tenant_name=SCHEMA_A, email=ADMIN_EMAIL, username=ADMIN_USERNAME, hashed_password=hash_password(ADMIN_PASSWORD), full_name="E2E Admin A", role="hospital_admin", is_active=True, must_change_password=False)
        pharmacist_a = User(id=PHARMACIST_USER_ID, tenant_id=TENANT_A_ID, tenant_name=SCHEMA_A, email=PHARMACIST_EMAIL, username=PHARMACIST_USERNAME, hashed_password=hash_password(PHARMACIST_PASSWORD), full_name="E2E Pharmacist A", role="pharmacist", is_active=True, must_change_password=False)
        user_b = User(id=HOSPITAL_B_DOCTOR_USER_ID, tenant_id=TENANT_B_ID, tenant_name=SCHEMA_B, email=HOSPITAL_B_DOCTOR_EMAIL, username=HOSPITAL_B_DOCTOR_USERNAME, hashed_password=hash_password(HOSPITAL_B_DOCTOR_PASSWORD), full_name="E2E Doctor B", role="doctor", is_active=True, must_change_password=False)
        session.add_all([tenant_a, tenant_b, user_a, receptionist_a, admin_a, pharmacist_a, user_b])
        await session.commit()
        session.add_all([
            TenantFeature(id=uuid.uuid4(), tenant_id=TENANT_A_ID, feature="billing", enabled=True),
            TenantFeature(id=uuid.uuid4(), tenant_id=TENANT_A_ID, feature="opd_queue", enabled=True),
            TenantFeature(id=uuid.uuid4(), tenant_id=TENANT_A_ID, feature="pharmacy", enabled=True),
        ])
        await session.commit()

        await session.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        department = Department(id=DEPARTMENT_ID, name="E2E General Medicine", is_active=True)
        doctor = Doctor(id=DOCTOR_ID, user_id=DOCTOR_USER_ID, full_name="E2E Doctor", specialization="General Medicine", department_id=DEPARTMENT_ID, consultation_fee=0, is_active=True)
        patient = Patient(id=PATIENT_ID, uhid="E2E-T7-PATIENT", first_name="E2E", last_name="Patient", gender="female", phone="9000000007")
        visit = Visit(id=VISIT_ID, patient_id=PATIENT_ID, uhid=patient.uhid, doctor_id=DOCTOR_ID, department_id=DEPARTMENT_ID, status="IN_CONSULTATION", arrived_at=now, registered_at=now, pre_vital_completed_at=now, doctor_queue_at=now, doctor_called_at=now, consultation_started_at=now)
        prescription_patient = Patient(id=PRESCRIPTION_PATIENT_ID, uhid="E2E-RX-PATIENT", first_name="Prescription", last_name="Patient", gender="female", phone="9000000010")
        prescription_visit = Visit(id=PRESCRIPTION_VISIT_ID, patient_id=PRESCRIPTION_PATIENT_ID, uhid=prescription_patient.uhid, doctor_id=DOCTOR_ID, department_id=DEPARTMENT_ID, status="IN_CONSULTATION", arrived_at=now, registered_at=now, pre_vital_completed_at=now, doctor_queue_at=now, doctor_called_at=now, consultation_started_at=now)
        p28_patient = Patient(id=P28_PATIENT_ID, uhid="E2E-P28-PATIENT", first_name="P28", last_name="Patient", gender="female", phone="9000000011")
        p28_visit = Visit(id=P28_VISIT_ID, patient_id=P28_PATIENT_ID, uhid=p28_patient.uhid, doctor_id=DOCTOR_ID, department_id=DEPARTMENT_ID, status="CONSULTATION_COMPLETED", arrived_at=now, registered_at=now, pre_vital_completed_at=now, doctor_queue_at=now, doctor_called_at=now, consultation_started_at=now)
        vitals = Vitals(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-vitals"), visit_id=VISIT_ID, uhid=patient.uhid, temperature=37.0, pulse=72, respiratory_rate=18, bp_systolic=120, bp_diastolic=80, spo2=99, pain_score=1, height=170, weight=70, bmi=24.2, blood_glucose=95, chief_complaint="E2E cough", allergies="None", known_no_allergies=True, general_condition="Stable", level_of_consciousness="Alert", nurse_notes="E2E completed pre-vitals", status="completed", recorded_by_user_id=DOCTOR_USER_ID, started_at=now, completed_at=now)
        icd_active = ICD10Code(id=ICD_A_ID, code="E2E.J06.9", description="E2E Acute upper respiratory infection", is_active=True)
        icd_inactive = ICD10Code(id=uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/icd10/inactive"), code="E2E.Z99.9", description="E2E Inactive diagnosis", is_active=False)
        generic_a = GenericMedicine(id=GENERIC_A_ID, code="E2E_PARACETAMOL", name="E2E Paracetamol", therapeutic_class="Analgesic", is_active=True)
        form_a = DosageForm(id=FORM_A_ID, code="E2E_TABLET", name="Tablet", calculation_type="UNIT", is_active=True)
        route_a = Route(id=ROUTE_A_ID, code="E2E_ORAL", name="Oral", is_active=True)
        manufacturer_a = Manufacturer(id=MANUFACTURER_A_ID, code="E2E_CIPLA", name="E2E Cipla", country="India", is_active=True)
        product_a = MedicineProduct(id=PRODUCT_A_ID, code="E2E-DOLO-500", generic_medicine_id=GENERIC_A_ID, brand_name="E2E Dolo", strength="500", unit="mg", dosage_form_id=FORM_A_ID, composition="E2E Paracetamol 500 mg", is_active=True)
        product_a_capsule = MedicineProduct(id=PRODUCT_A_CAPSULE_ID, code="E2E-CROCIN-650", generic_medicine_id=GENERIC_A_ID, brand_name="E2E Crocin", strength="650", unit="mg", dosage_form_id=FORM_A_ID, composition="E2E Paracetamol 650 mg", is_active=True)
        formulary_a = HospitalFormulary(id=FORMULARY_A_ID, medicine_product_id=PRODUCT_A_ID, department_id=DEPARTMENT_ID, is_approved=True, is_preferred=True, is_prescribable=True)
        formulary_a_capsule = HospitalFormulary(id=FORMULARY_A_CAPSULE_ID, medicine_product_id=PRODUCT_A_CAPSULE_ID, department_id=DEPARTMENT_ID, is_approved=True, is_prescribable=True)
        med_table = MedicineMaster(id=MED_A_ID, generic_name="E2E Paracetamol", brand_name="E2E Crocin", strength="500 mg", dosage_form="Tablet", is_active=True)
        med_capsule = MedicineMaster(id=uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/medicine/capsule"), generic_name="E2E Paracetamol", brand_name="E2E Crocin", strength="650 mg", dosage_form="Capsule", is_active=True)
        med_inactive = MedicineMaster(id=uuid.uuid5(uuid.NAMESPACE_DNS, "https://example.test/medicine/inactive"), generic_name="E2E Inactive Drug", brand_name="E2E Old", strength="10 mg", dosage_form="Tablet", is_active=False)
        supplier_a = Supplier(id=SUPPLIER_A_ID, supplier_code="E2E-SUP-1", supplier_name="E2E Supplier", country="India", is_active=True)
        po_a = PurchaseOrder(id=PO_A_ID, po_number="E2E-PO-0001", supplier_id=SUPPLIER_A_ID, status="SENT", subtotal=Decimal("100.00"), tax_amount=Decimal("18.00"), total_amount=Decimal("118.00"))
        po_item_a = PurchaseOrderItem(id=PO_ITEM_A_ID, purchase_order_id=PO_A_ID, medicine_product_id=PRODUCT_A_ID, ordered_quantity=Decimal("10"), unit_of_measure="tablet", unit_purchase_price=Decimal("10.00"), gst_percent=Decimal("18"), taxable_amount=Decimal("100.00"), tax_amount=Decimal("18.00"), line_total=Decimal("118.00"))
        po_a.items.append(po_item_a)
        session.add_all([department, doctor, patient, visit, prescription_patient, prescription_visit, p28_patient, p28_visit, vitals, icd_active, icd_inactive, generic_a, form_a, route_a, manufacturer_a, product_a, product_a_capsule, med_table, med_capsule, med_inactive, supplier_a])
        await session.flush()
        session.add_all([po_a, formulary_a, formulary_a_capsule])
        await session.commit()

        await session.execute(text(f'SET search_path TO "{SCHEMA_B}", public'))
        department_b = Department(id=HOSPITAL_B_DEPARTMENT_ID, name="Hospital B Internal Medicine", is_active=True)
        doctor_b = Doctor(id=HOSPITAL_B_DOCTOR_ID, user_id=HOSPITAL_B_DOCTOR_USER_ID, full_name="Hospital B Doctor", specialization="Internal Medicine", department_id=HOSPITAL_B_DEPARTMENT_ID, consultation_fee=0, is_active=True)
        patient_b = Patient(id=HOSPITAL_B_PATIENT_ID, uhid="HB-T7-PATIENT", first_name="Hospital", last_name="B Patient", gender="male", phone="9000000008")
        visit_b = Visit(id=HOSPITAL_B_VISIT_ID, patient_id=HOSPITAL_B_PATIENT_ID, uhid=patient_b.uhid, doctor_id=HOSPITAL_B_DOCTOR_ID, department_id=HOSPITAL_B_DEPARTMENT_ID, status="WAITING_FOR_DOCTOR", arrived_at=now, registered_at=now, pre_vital_completed_at=now, doctor_queue_at=now)
        vitals_b = Vitals(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-vitals-b"), visit_id=HOSPITAL_B_VISIT_ID, uhid=patient_b.uhid, temperature=37.1, pulse=74, respiratory_rate=17, bp_systolic=122, bp_diastolic=82, spo2=98, pain_score=2, height=171, weight=72, bmi=24.6, blood_glucose=97, chief_complaint="B-tenant cough", allergies="None", known_no_allergies=True, general_condition="Stable", level_of_consciousness="Alert", nurse_notes="Hospital B completed pre-vitals", status="completed", recorded_by_user_id=HOSPITAL_B_DOCTOR_USER_ID, started_at=now, completed_at=now)
        icd_active_b = ICD10Code(id=ICD_B_ID, code="HB.J22.1", description="Hospital B lower respiratory infection", is_active=True)
        generic_b = GenericMedicine(id=GENERIC_B_ID, code="HB_CEFIXIME", name="Hospital B Cefixime", therapeutic_class="Antibiotic", is_active=True)
        form_b = DosageForm(id=FORM_B_ID, code="E2E_TABLET", name="Tablet", calculation_type="UNIT", is_active=True)
        route_b = Route(id=ROUTE_B_ID, code="E2E_ORAL", name="Oral", is_active=True)
        manufacturer_b = Manufacturer(id=MANUFACTURER_B_ID, code="E2E_CIPLA", name="E2E Cipla", country="India", is_active=True)
        product_b = MedicineProduct(id=PRODUCT_B_ID, code="HB-CEFI-200", generic_medicine_id=GENERIC_B_ID, brand_name="HB Cefi", strength="200", unit="mg", dosage_form_id=FORM_B_ID, composition="Hospital B Cefixime 200 mg", is_active=True)
        formulary_b = HospitalFormulary(id=FORMULARY_B_ID, medicine_product_id=PRODUCT_B_ID, department_id=HOSPITAL_B_DEPARTMENT_ID, is_approved=True, is_prescribable=True)
        med_active_b = MedicineMaster(id=MED_B_ID, generic_name="Hospital B Cefixime", brand_name="HB Cefi", strength="200 mg", dosage_form="Tablet", is_active=True)
        session.add_all([department_b, doctor_b, patient_b, visit_b, vitals_b, icd_active_b, generic_b, form_b, route_b, manufacturer_b, product_b, med_active_b])
        await session.flush()
        session.add(formulary_b)
        await session.commit()
    await engine.dispose()
    print(f"E2E seed ready: {DOCTOR_USERNAME} / {DOCTOR_PASSWORD} / visit={VISIT_ID}")


async def seed_p28():
    await seed()
    await seed_p28_scenario()


async def reset_task7_scenario():
    from app.core.config import settings

    _assert_destructive_reset_allowed(settings.DATABASE_URL, "reset_task7_scenario")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))

        await conn.execute(
            text(
                "DELETE FROM pharmacy_stock_reservations "
                "WHERE dispense_id IN ("
                "  SELECT pd.id FROM pharmacy_dispenses pd "
                "  WHERE pd.prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"
                ")"
            ),
            {"visit_id": VISIT_ID},
        )
        await conn.execute(
            text(
                "DELETE FROM pharmacy_dispense_allocations "
                "WHERE dispense_item_id IN ("
                "  SELECT pdi.id FROM pharmacy_dispense_items pdi "
                "  JOIN pharmacy_dispenses pd ON pd.id = pdi.dispense_id "
                "  WHERE pd.prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"
                ")"
            ),
            {"visit_id": VISIT_ID},
        )
        await conn.execute(
            text(
                "DELETE FROM pharmacy_dispense_items "
                "WHERE dispense_id IN ("
                "  SELECT id FROM pharmacy_dispenses "
                "  WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"
                ")"
            ),
            {"visit_id": VISIT_ID},
        )
        await conn.execute(
            text(
                "DELETE FROM pharmacy_dispenses "
                "WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"
            ),
            {"visit_id": VISIT_ID},
        )
        await conn.execute(
            text(
                "DELETE FROM pharmacy_queue "
                "WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"
            ),
            {"visit_id": VISIT_ID},
        )
        await conn.execute(
            text(
                "DELETE FROM prescription_items "
                "WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"
            ),
            {"visit_id": VISIT_ID},
        )
        await conn.execute(text("DELETE FROM prescriptions WHERE visit_id = :visit_id"), {"visit_id": VISIT_ID})
        await conn.execute(text("DELETE FROM consultations WHERE visit_id = :visit_id"), {"visit_id": VISIT_ID})
        await conn.execute(text("DELETE FROM invoices WHERE visit_id = :visit_id"), {"visit_id": VISIT_ID})
        await conn.execute(text("DELETE FROM audit_logs WHERE visit_id = :visit_id"), {"visit_id": VISIT_ID})
        await conn.execute(
            text(
                "UPDATE visits SET "
                "status = 'IN_CONSULTATION', "
                "consultation_started_at = :now_ts, "
                "consultation_completed_at = NULL, "
                "billing_started_at = NULL, "
                "billing_completed_at = NULL, "
                "doctor_queue_at = :now_ts, "
                "doctor_called_at = :now_ts "
                "WHERE id = :visit_id"
            ),
            {"visit_id": VISIT_ID, "now_ts": now},
        )

        await conn.execute(text(f'SET search_path TO "{SCHEMA_B}", public'))
        await conn.execute(text("DELETE FROM consultations WHERE visit_id = :visit_id"), {"visit_id": HOSPITAL_B_VISIT_ID})
        await conn.execute(text("DELETE FROM prescriptions WHERE visit_id = :visit_id"), {"visit_id": HOSPITAL_B_VISIT_ID})
        await conn.execute(text("DELETE FROM audit_logs WHERE visit_id = :visit_id"), {"visit_id": HOSPITAL_B_VISIT_ID})
        await conn.execute(
            text(
                "UPDATE visits SET status = 'WAITING_FOR_DOCTOR', consultation_started_at = NULL, consultation_completed_at = NULL "
                "WHERE id = :visit_id"
            ),
            {"visit_id": HOSPITAL_B_VISIT_ID},
        )

    await engine.dispose()
    print("Task7 scenario reset complete")


async def reset_prescription_scenario():
    from app.core.config import settings

    _assert_destructive_reset_allowed(settings.DATABASE_URL, "reset_prescription_scenario")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        await conn.execute(text("DELETE FROM prescription_items WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"), {"visit_id": PRESCRIPTION_VISIT_ID})
        await conn.execute(text("DELETE FROM pharmacy_queue WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id = :visit_id)"), {"visit_id": PRESCRIPTION_VISIT_ID})
        await conn.execute(text("DELETE FROM prescriptions WHERE visit_id = :visit_id"), {"visit_id": PRESCRIPTION_VISIT_ID})
    await engine.dispose()
    print("Prescription scenario reset complete")


async def reset_procurement_scenario():
    from app.core.config import settings

    _assert_destructive_reset_allowed(settings.DATABASE_URL, "reset_procurement_scenario")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        await conn.execute(text("DELETE FROM stock_transactions WHERE inventory_batch_id IN (SELECT id FROM inventory_batches WHERE batch_number LIKE 'E2E-BATCH-%' OR batch_number LIKE 'E2E-EXPIRED-%')"))
        await conn.execute(text("DELETE FROM inventory_batches WHERE batch_number LIKE 'E2E-BATCH-%' OR batch_number LIKE 'E2E-EXPIRED-%'"))
        await conn.execute(text("DELETE FROM goods_receipt_items WHERE goods_receipt_id IN (SELECT id FROM goods_receipts WHERE purchase_order_id = :po)"), {"po": PO_A_ID})
        await conn.execute(text("DELETE FROM goods_receipts WHERE purchase_order_id = :po"), {"po": PO_A_ID})
        await conn.execute(text("UPDATE purchase_order_items SET received_quantity = 0 WHERE purchase_order_id = :po"), {"po": PO_A_ID})
        await conn.execute(text("UPDATE purchase_orders SET status = 'SENT', approved_by_user_id = NULL, approved_at = NULL, sent_at = NULL, updated_by_user_id = NULL WHERE id = :po"), {"po": PO_A_ID})
    await engine.dispose()
    print("Procurement scenario reset complete")


async def reset_p28_scenario():
    from app.core.config import settings

    _assert_destructive_reset_allowed(settings.DATABASE_URL, "reset_p28_scenario")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        await conn.execute(text("DELETE FROM pharmacy_stock_reservations WHERE dispense_id IN (SELECT id FROM pharmacy_dispenses WHERE prescription_id = :rx)"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM pharmacy_dispense_allocations WHERE dispense_item_id IN (SELECT id FROM pharmacy_dispense_items WHERE dispense_id IN (SELECT id FROM pharmacy_dispenses WHERE prescription_id = :rx))"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM pharmacy_dispense_items WHERE dispense_id IN (SELECT id FROM pharmacy_dispenses WHERE prescription_id = :rx)"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM pharmacy_dispenses WHERE prescription_id = :rx"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM pharmacy_queue WHERE prescription_id = :rx"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM prescription_items WHERE prescription_id = :rx"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM prescriptions WHERE id = :rx"), {"rx": P28_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM stock_transactions WHERE reference_type = 'pharmacy_dispense' OR reference_id IN (:early, :later)"), {"early": P28_GRN_ITEM_EARLY_ID, "later": P28_GRN_ITEM_LATER_ID})
        await conn.execute(text("DELETE FROM inventory_batches WHERE id IN (:early, :later)"), {"early": P28_EARLY_BATCH_ID, "later": P28_LATER_BATCH_ID})
        await conn.execute(text("DELETE FROM pharmacy_locations WHERE id = :location"), {"location": PHARMACY_LOCATION_A_ID})
    await engine.dispose()
    print("P28 scenario reset complete")


async def seed_p28_scenario():
    await reset_p28_scenario()
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    facility_id = FACILITY_A_ID
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        visit = await session.get(Visit, P28_VISIT_ID)
        visit.status = "CONSULTATION_COMPLETED"
        location = PharmacyLocation(id=PHARMACY_LOCATION_A_ID, tenant_id=TENANT_A_ID, facility_id=facility_id, location_code="E2E-P28", location_name="E2E P28 Pharmacy", location_type="PHARMACY", active=True)
        prescription = Prescription(id=P28_PRESCRIPTION_ID, visit_id=P28_VISIT_ID, uhid="E2E-P28-PATIENT", status="finalized", version=1, medicines=[{"name": "E2E Dolo", "dose": "1 tablet", "frequency": "once daily", "duration": "10 days", "route": "oral"}])
        prescription.items.append(PrescriptionItem(id=P28_PRESCRIPTION_ITEM_ID, medicine_product_id=PRODUCT_A_ID, medicine="E2E Dolo", strength="500", quantity="10", final_quantity="10", auto_quantity="10", route="oral", frequency="once daily", duration="10 days"))
        queue = PharmacyQueue(id=P28_QUEUE_ID, prescription_id=P28_PRESCRIPTION_ID, uhid="E2E-P28-PATIENT", status="pending")
        early = InventoryBatch(id=P28_EARLY_BATCH_ID, tenant_id=TENANT_A_ID, facility_id=facility_id, pharmacy_location_id=PHARMACY_LOCATION_A_ID, medicine_id=PRODUCT_A_ID, batch_number="P28-EARLY", expiry_date=datetime(2027, 6, 30, tzinfo=timezone.utc).date(), purchase_rate=Decimal("10"), mrp=Decimal("12"), received_quantity=Decimal("6"), available_quantity=Decimal("6"), reserved_quantity=Decimal("0"), supplier_id=SUPPLIER_A_ID, goods_receipt_id=P28_GRN_ID, goods_receipt_item_id=P28_GRN_ITEM_EARLY_ID, status="ACTIVE")
        later = InventoryBatch(id=P28_LATER_BATCH_ID, tenant_id=TENANT_A_ID, facility_id=facility_id, pharmacy_location_id=PHARMACY_LOCATION_A_ID, medicine_id=PRODUCT_A_ID, batch_number="P28-LATER", expiry_date=datetime(2028, 2, 28, tzinfo=timezone.utc).date(), purchase_rate=Decimal("10"), mrp=Decimal("12"), received_quantity=Decimal("20"), available_quantity=Decimal("20"), reserved_quantity=Decimal("0"), supplier_id=SUPPLIER_A_ID, goods_receipt_id=P28_GRN_ID, goods_receipt_item_id=P28_GRN_ITEM_LATER_ID, status="ACTIVE")
        session.add(location)
        await session.flush()
        session.add(prescription)
        await session.flush()
        session.add_all([queue, early, later])
        await session.flush()
        session.add_all([
            StockTransaction(tenant_id=TENANT_A_ID, facility_id=facility_id, pharmacy_location_id=PHARMACY_LOCATION_A_ID, medicine_id=PRODUCT_A_ID, inventory_batch_id=P28_EARLY_BATCH_ID, transaction_type="PURCHASE_RECEIPT", quantity=Decimal("6"), previous_balance=Decimal("0"), new_balance=Decimal("6"), reference_type="goods_receipt_item", reference_id=P28_GRN_ITEM_EARLY_ID, reason="E2E receipt", performed_by=PHARMACIST_USER_ID),
            StockTransaction(tenant_id=TENANT_A_ID, facility_id=facility_id, pharmacy_location_id=PHARMACY_LOCATION_A_ID, medicine_id=PRODUCT_A_ID, inventory_batch_id=P28_LATER_BATCH_ID, transaction_type="PURCHASE_RECEIPT", quantity=Decimal("20"), previous_balance=Decimal("0"), new_balance=Decimal("20"), reference_type="goods_receipt_item", reference_id=P28_GRN_ITEM_LATER_ID, reason="E2E receipt", performed_by=PHARMACIST_USER_ID),
        ])
        await session.commit()
    await engine.dispose()
    print(f"P28 E2E seed ready: {PHARMACIST_USERNAME} / {PHARMACIST_PASSWORD} / facility={facility_id} / location={PHARMACY_LOCATION_A_ID}")


async def reset_p30_scenario():
    from app.core.config import settings
    _assert_destructive_reset_allowed(settings.DATABASE_URL, "reset_p30_scenario")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    dispense_ids = [P30_SINGLE_DISPENSE_ID, P30_MULTI_DISPENSE_ID]
    batch_ids = [P30_SINGLE_BATCH_ID, P30_MULTI_BATCH_A_ID, P30_MULTI_BATCH_B_ID, P30_SUPPLIER_BATCH_A_ID, P30_SUPPLIER_BATCH_B_ID]
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        await conn.execute(text("DELETE FROM patient_return_batch_allocations WHERE patient_return_item_id IN (SELECT id FROM patient_return_items WHERE return_id IN (SELECT id FROM patient_returns WHERE dispense_id = ANY(:ids)))"), {"ids": dispense_ids})
        await conn.execute(text("DELETE FROM patient_return_items WHERE return_id IN (SELECT id FROM patient_returns WHERE dispense_id = ANY(:ids))"), {"ids": dispense_ids})
        await conn.execute(text("DELETE FROM patient_returns WHERE dispense_id = ANY(:ids)"), {"ids": dispense_ids})
        await conn.execute(text("DELETE FROM supplier_return_items WHERE supplier_return_id IN (SELECT id FROM supplier_returns WHERE goods_receipt_id = :grn)"), {"grn": P30_GRN_ID})
        await conn.execute(text("DELETE FROM supplier_returns WHERE goods_receipt_id = :grn"), {"grn": P30_GRN_ID})
        await conn.execute(text("DELETE FROM stock_transactions WHERE inventory_batch_id = ANY(:ids)"), {"ids": batch_ids})
        await conn.execute(text("DELETE FROM pharmacy_dispense_allocations WHERE dispense_item_id IN (SELECT id FROM pharmacy_dispense_items WHERE dispense_id = ANY(:ids))"), {"ids": dispense_ids})
        await conn.execute(text("DELETE FROM pharmacy_dispense_items WHERE dispense_id = ANY(:ids)"), {"ids": dispense_ids})
        await conn.execute(text("DELETE FROM pharmacy_dispenses WHERE id = ANY(:ids)"), {"ids": dispense_ids})
        await conn.execute(text("DELETE FROM prescription_items WHERE prescription_id IN (:single, :multi)"), {"single": P30_SINGLE_PRESCRIPTION_ID, "multi": P30_MULTI_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM prescriptions WHERE id IN (:single, :multi)"), {"single": P30_SINGLE_PRESCRIPTION_ID, "multi": P30_MULTI_PRESCRIPTION_ID})
        await conn.execute(text("DELETE FROM inventory_batches WHERE id = ANY(:ids)"), {"ids": batch_ids})
        await conn.execute(text("DELETE FROM goods_receipts WHERE id = :id"), {"id": P30_GRN_ID})
        await conn.execute(text("DELETE FROM visits WHERE id IN (:single, :multi)"), {"single": P30_SINGLE_VISIT_ID, "multi": P30_MULTI_VISIT_ID})
        await conn.execute(text("DELETE FROM patients WHERE id IN (:single, :multi)"), {"single": P30_PATIENT_SINGLE_ID, "multi": P30_PATIENT_MULTI_ID})
        await conn.execute(text("DELETE FROM pharmacy_locations WHERE id = :id"), {"id": P30_LOCATION_ID})
    await engine.dispose()


async def seed_p30_scenario():
    await reset_p30_scenario()
    from app.core.config import settings
    now = datetime.now(timezone.utc)
    expiry = (now.replace(year=now.year + 1)).date()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        location = PharmacyLocation(id=P30_LOCATION_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, location_code="E2E-P30", location_name="E2E P30 Pharmacy", location_type="PHARMACY", active=True)
        single_patient = Patient(id=P30_PATIENT_SINGLE_ID, uhid="E2E-P30-SINGLE", first_name="P30", last_name="Single", gender="female", phone="9000000030")
        multi_patient = Patient(id=P30_PATIENT_MULTI_ID, uhid="E2E-P30-MULTI", first_name="P30", last_name="Multi", gender="male", phone="9000000031")
        single_visit = Visit(id=P30_SINGLE_VISIT_ID, patient_id=P30_PATIENT_SINGLE_ID, uhid=single_patient.uhid, doctor_id=DOCTOR_ID, department_id=DEPARTMENT_ID, status="CONSULTATION_COMPLETED", arrived_at=now, registered_at=now)
        multi_visit = Visit(id=P30_MULTI_VISIT_ID, patient_id=P30_PATIENT_MULTI_ID, uhid=multi_patient.uhid, doctor_id=DOCTOR_ID, department_id=DEPARTMENT_ID, status="CONSULTATION_COMPLETED", arrived_at=now, registered_at=now)
        session.add_all([location, single_patient, multi_patient, single_visit, multi_visit])
        await session.flush()
        single_rx = Prescription(id=P30_SINGLE_PRESCRIPTION_ID, visit_id=P30_SINGLE_VISIT_ID, uhid=single_patient.uhid, status="finalized", version=1)
        multi_rx = Prescription(id=P30_MULTI_PRESCRIPTION_ID, visit_id=P30_MULTI_VISIT_ID, uhid=multi_patient.uhid, status="finalized", version=1)
        session.add_all([single_rx, multi_rx])
        await session.flush()
        session.add_all([
            PrescriptionItem(id=P30_SINGLE_ITEM_ID, prescription_id=P30_SINGLE_PRESCRIPTION_ID, medicine_product_id=PRODUCT_A_ID, medicine="P30 Single Medicine", quantity="5", final_quantity="5"),
            PrescriptionItem(id=P30_MULTI_ITEM_ID, prescription_id=P30_MULTI_PRESCRIPTION_ID, medicine_product_id=PRODUCT_A_ID, medicine="P30 Multi Medicine", quantity="6", final_quantity="6"),
        ])
        single_dispense = PharmacyDispense(id=P30_SINGLE_DISPENSE_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, prescription_id=P30_SINGLE_PRESCRIPTION_ID, prescription_version=1, visit_id=P30_SINGLE_VISIT_ID, patient_id=P30_PATIENT_SINGLE_ID, status="CONFIRMED", completed_at=now)
        multi_dispense = PharmacyDispense(id=P30_MULTI_DISPENSE_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, prescription_id=P30_MULTI_PRESCRIPTION_ID, prescription_version=1, visit_id=P30_MULTI_VISIT_ID, patient_id=P30_PATIENT_MULTI_ID, status="CONFIRMED", completed_at=now)
        session.add_all([single_dispense, multi_dispense])
        await session.flush()
        single_item = PharmacyDispenseItem(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-dispense-item"), dispense_id=P30_SINGLE_DISPENSE_ID, prescription_item_id=P30_SINGLE_ITEM_ID, prescribed_name_snapshot="P30 Single Medicine", prescribed_quantity=Decimal("5"), internal_requested_quantity=Decimal("5"), internal_confirmed_quantity=Decimal("5"), outside_purchase_quantity=Decimal("0"), status="DISPENSED")
        multi_item = PharmacyDispenseItem(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-dispense-item"), dispense_id=P30_MULTI_DISPENSE_ID, prescription_item_id=P30_MULTI_ITEM_ID, prescribed_name_snapshot="P30 Multi Medicine", prescribed_quantity=Decimal("6"), internal_requested_quantity=Decimal("6"), internal_confirmed_quantity=Decimal("6"), outside_purchase_quantity=Decimal("0"), status="DISPENSED")
        session.add_all([single_item, multi_item])
        batches = [
            InventoryBatch(id=P30_SINGLE_BATCH_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, medicine_id=PRODUCT_A_ID, batch_number="P30-SINGLE-BATCH", expiry_date=expiry, purchase_rate=Decimal("10"), received_quantity=Decimal("5"), available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE"),
            InventoryBatch(id=P30_MULTI_BATCH_A_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, medicine_id=PRODUCT_A_ID, batch_number="P30-MULTI-A", expiry_date=expiry, purchase_rate=Decimal("10"), received_quantity=Decimal("3"), available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE"),
            InventoryBatch(id=P30_MULTI_BATCH_B_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, medicine_id=PRODUCT_A_ID, batch_number="P30-MULTI-B", expiry_date=expiry, purchase_rate=Decimal("12"), received_quantity=Decimal("3"), available_quantity=Decimal("0"), reserved_quantity=Decimal("0"), status="ACTIVE"),
        ]
        grn = GoodsReceipt(id=P30_GRN_ID, grn_number="E2E-P30-GRN", purchase_order_id=PO_A_ID, supplier_id=SUPPLIER_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, status="FULLY_RECEIVED", subtotal=Decimal("160"), total_amount=Decimal("160"))
        supplier_batches = [
            InventoryBatch(id=P30_SUPPLIER_BATCH_A_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, medicine_id=PRODUCT_A_ID, batch_number="P30-SUP-A", expiry_date=expiry, purchase_rate=Decimal("8"), received_quantity=Decimal("10"), available_quantity=Decimal("10"), reserved_quantity=Decimal("0"), supplier_id=SUPPLIER_A_ID, goods_receipt_id=P30_GRN_ID, status="ACTIVE"),
            InventoryBatch(id=P30_SUPPLIER_BATCH_B_ID, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, medicine_id=PRODUCT_A_ID, batch_number="P30-SUP-B", expiry_date=expiry, purchase_rate=Decimal("9"), received_quantity=Decimal("8"), available_quantity=Decimal("8"), reserved_quantity=Decimal("0"), supplier_id=SUPPLIER_A_ID, goods_receipt_id=P30_GRN_ID, status="ACTIVE"),
        ]
        session.add_all([grn, *batches, *supplier_batches])
        await session.flush()
        session.add_all([
            PharmacyDispenseAllocation(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-single-allocation"), dispense_item_id=single_item.id, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, inventory_batch_id=P30_SINGLE_BATCH_ID, allocated_quantity=Decimal("5"), confirmed_dispensed_quantity=Decimal("5"), status="CONSUMED"),
            PharmacyDispenseAllocation(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-allocation-a"), dispense_item_id=multi_item.id, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, inventory_batch_id=P30_MULTI_BATCH_A_ID, allocated_quantity=Decimal("3"), confirmed_dispensed_quantity=Decimal("3"), status="CONSUMED"),
            PharmacyDispenseAllocation(id=uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-p30-multi-allocation-b"), dispense_item_id=multi_item.id, tenant_id=TENANT_A_ID, facility_id=FACILITY_A_ID, pharmacy_location_id=P30_LOCATION_ID, inventory_batch_id=P30_MULTI_BATCH_B_ID, allocated_quantity=Decimal("3"), confirmed_dispensed_quantity=Decimal("3"), status="CONSUMED"),
        ])
        await session.commit()
    await engine.dispose()
    print("P30 E2E seed ready")


async def snapshot_p30():
    from app.core.config import settings
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    batch_ids = [P30_SINGLE_BATCH_ID, P30_MULTI_BATCH_A_ID, P30_MULTI_BATCH_B_ID, P30_SUPPLIER_BATCH_A_ID, P30_SUPPLIER_BATCH_B_ID]
    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        batches = (await conn.execute(text("SELECT batch_number, available_quantity FROM inventory_batches WHERE id = ANY(:ids) ORDER BY batch_number"), {"ids": batch_ids})).mappings().all()
        patient_returns = (await conn.execute(text("SELECT reference_key, status, total_return_quantity FROM patient_returns WHERE dispense_id IN (:single, :multi) ORDER BY reference_key"), {"single": P30_SINGLE_DISPENSE_ID, "multi": P30_MULTI_DISPENSE_ID})).mappings().all()
        patient_allocations = (await conn.execute(text("SELECT b.batch_number, a.returned_quantity FROM patient_return_batch_allocations a JOIN inventory_batches b ON b.id = a.inventory_batch_id ORDER BY b.batch_number"))).mappings().all()
        supplier_returns = (await conn.execute(text("SELECT reference_key, status FROM supplier_returns WHERE goods_receipt_id = :grn ORDER BY reference_key"), {"grn": P30_GRN_ID})).mappings().all()
        ledger = (await conn.execute(text("SELECT transaction_type, b.batch_number, quantity FROM stock_transactions s JOIN inventory_batches b ON b.id = s.inventory_batch_id WHERE b.id = ANY(:ids) AND transaction_type IN ('PATIENT_RETURN_RESTOCK', 'SUPPLIER_RETURN') ORDER BY transaction_type, b.batch_number"), {"ids": batch_ids})).mappings().all()
    await engine.dispose()
    print(json.dumps({"batches": [{"batch_number": row["batch_number"], "available_quantity": str(row["available_quantity"])} for row in batches], "patient_returns": [dict(row) for row in patient_returns], "patient_allocations": [{"batch_number": row["batch_number"], "returned_quantity": str(row["returned_quantity"])} for row in patient_allocations], "supplier_returns": [dict(row) for row in supplier_returns], "ledger": [{"transaction_type": row["transaction_type"], "batch_number": row["batch_number"], "quantity": str(row["quantity"])} for row in ledger]}, default=str))


async def cleanup():
    from app.core.config import settings
    _assert_destructive_reset_allowed(settings.DATABASE_URL, "cleanup")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_A}" CASCADE'))
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_B}" CASCADE'))
        await conn.execute(delete(User).where(User.id.in_([DOCTOR_USER_ID, RECEPTIONIST_USER_ID, ADMIN_USER_ID, PHARMACIST_USER_ID, HOSPITAL_B_DOCTOR_USER_ID])))
        await conn.execute(delete(TenantFeature).where(TenantFeature.tenant_id.in_([TENANT_A_ID, TENANT_B_ID])))
        await conn.execute(delete(Tenant).where(Tenant.id.in_([TENANT_A_ID, TENANT_B_ID])))
    await engine.dispose()


async def snapshot(visit_id: uuid.UUID = VISIT_ID):
    from app.core.config import settings
    from app.models.tenant.audit_log import AuditLog

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    payload: dict[str, object] = {
        "tenants": {
            "hospital_a": {
                "schema": SCHEMA_A,
                "tenant_id": str(TENANT_A_ID),
                "doctor_user_id": str(DOCTOR_USER_ID),
                "patient_id": str(PATIENT_ID),
                "visit_id": str(VISIT_ID),
                "icd10_id": str(ICD_A_ID),
                "medicine_master_id": str(MED_A_ID),
                "icd10_code": "E2E.J06.9",
                "medicine_name": "E2E Paracetamol",
            },
            "hospital_b": {
                "schema": SCHEMA_B,
                "tenant_id": str(TENANT_B_ID),
                "doctor_user_id": str(HOSPITAL_B_DOCTOR_USER_ID),
                "patient_id": str(HOSPITAL_B_PATIENT_ID),
                "visit_id": str(HOSPITAL_B_VISIT_ID),
                "icd10_id": str(ICD_B_ID),
                "medicine_master_id": str(MED_B_ID),
                "icd10_code": "HB.J22.1",
                "medicine_name": "Hospital B Cefixime",
            },
        }
    }

    async with engine.begin() as conn:
        await conn.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))

        prescription_count = (
            await conn.execute(text('SELECT COUNT(*) FROM prescriptions WHERE visit_id = :visit_id'), {"visit_id": visit_id})
        ).scalar_one()
        consultation_count = (
            await conn.execute(text('SELECT COUNT(*) FROM consultations WHERE visit_id = :visit_id'), {"visit_id": visit_id})
        ).scalar_one()
        visit_status = (
            await conn.execute(text('SELECT status FROM visits WHERE id = :visit_id'), {"visit_id": visit_id})
        ).scalar_one_or_none()

        pharmacy_queue_count = (
            await conn.execute(
                text(
                    'SELECT COUNT(*) FROM pharmacy_queue pq '
                    'JOIN prescriptions rx ON rx.id = pq.prescription_id '
                    'WHERE rx.visit_id = :visit_id'
                ),
                {"visit_id": visit_id},
            )
        ).scalar_one()
        pharmacy_dispensed_count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM pharmacy_queue pq "
                    "JOIN prescriptions rx ON rx.id = pq.prescription_id "
                    "WHERE rx.visit_id = :visit_id AND pq.status IN ('dispensing', 'dispensed', 'partially_dispensed')"
                ),
                {"visit_id": visit_id},
            )
        ).scalar_one()
        pharmacy_invoice_count = (
            await conn.execute(
                text("SELECT COUNT(*) FROM invoices WHERE visit_id = :visit_id AND source = 'pharmacy_dispense'"),
                {"visit_id": visit_id},
            )
        ).scalar_one()

        stock_movement_table = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name IN ('stock_movements', 'stock_transactions', 'inventory_movements', 'medicine_stock_movements') "
                    "LIMIT 1"
                )
            )
        ).scalar_one_or_none()
        stock_movement_count = 0
        if stock_movement_table:
            stock_movement_count = (
                await conn.execute(text(f'SELECT COUNT(*) FROM "{stock_movement_table}"'))
            ).scalar_one()

        inventory_table = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name IN ('inventory', 'medicine_inventory', 'stock', 'medicine_stock') "
                    "LIMIT 1"
                )
            )
        ).scalar_one_or_none()
        inventory_quantity = None
        if inventory_table:
            quantity_column = (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = :table_name "
                        "AND column_name IN ('quantity', 'available_quantity', 'on_hand_quantity', 'qty_on_hand', 'stock_quantity') "
                        "LIMIT 1"
                    ),
                    {"table_name": inventory_table},
                )
            ).scalar_one_or_none()
            medicine_key = (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = :table_name "
                        "AND column_name IN ('medicine_master_id', 'medicine_id') "
                        "LIMIT 1"
                    ),
                    {"table_name": inventory_table},
                )
            ).scalar_one_or_none()
            if quantity_column and medicine_key:
                inventory_quantity = (
                    await conn.execute(
                        text(
                            f'SELECT "{quantity_column}" FROM "{inventory_table}" '
                            f'WHERE "{medicine_key}" = :medicine_id LIMIT 1'
                        ),
                        {"medicine_id": MED_A_ID},
                    )
                ).scalar_one_or_none()

    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await session.execute(text(f'SET search_path TO "{SCHEMA_A}", public'))
        audit_rows = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.visit_id == visit_id)
                .order_by(AuditLog.timestamp.asc())
            )
        ).scalars().all()

        p28_dispense = await session.execute(text("SELECT id, status FROM pharmacy_dispenses WHERE prescription_id = :prescription_id"), {"prescription_id": P28_PRESCRIPTION_ID})
        p28_dispense_row = p28_dispense.first()
        p28 = None
        if p28_dispense_row:
            p28_allocations = (await session.execute(text("""
                SELECT b.batch_number, a.allocated_quantity, a.confirmed_dispensed_quantity,
                       b.available_quantity, b.reserved_quantity, a.status
                FROM pharmacy_dispense_allocations a
                JOIN inventory_batches b ON b.id = a.inventory_batch_id
                JOIN pharmacy_dispense_items di ON di.id = a.dispense_item_id
                WHERE di.dispense_id = :dispense_id
                ORDER BY b.batch_number
            """), {"dispense_id": p28_dispense_row.id})).mappings().all()
            p28_ledger = (await session.execute(text("""
                SELECT quantity FROM stock_transactions
                WHERE reference_type = 'pharmacy_dispense'
                  AND reference_id IN (
                    SELECT a.id FROM pharmacy_dispense_allocations a
                    JOIN pharmacy_dispense_items di ON di.id = a.dispense_item_id
                    WHERE di.dispense_id = :dispense_id
                  )
                ORDER BY quantity
            """), {"dispense_id": p28_dispense_row.id})).scalars().all()
            p28_item = (await session.execute(text("SELECT prescribed_quantity, internal_confirmed_quantity, outside_purchase_quantity FROM pharmacy_dispense_items WHERE dispense_id = :dispense_id"), {"dispense_id": p28_dispense_row.id})).mappings().first()
            p28 = {"status": p28_dispense_row.status, "item": dict(p28_item) if p28_item else None, "allocations": [dict(row) for row in p28_allocations], "ledger_quantities": [str(value) for value in p28_ledger]}

    await engine.dispose()

    payload["state"] = {
        "prescription_count": int(prescription_count),
        "consultation_count": int(consultation_count),
        "visit_status": visit_status,
        "pharmacy_queue_count": int(pharmacy_queue_count),
        "pharmacy_dispensed_count": int(pharmacy_dispensed_count),
        "pharmacy_invoice_count": int(pharmacy_invoice_count),
        "stock_movement_table": stock_movement_table,
        "stock_movement_count": int(stock_movement_count),
        "inventory_table": inventory_table,
        "inventory_quantity": float(inventory_quantity) if inventory_quantity is not None else None,
        "audit_records": [_serialize_row(row) for row in audit_rows],
        "p28": p28,
    }
    print(json.dumps(payload, default=str))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "seed":
        asyncio.run(seed())
    elif command == "reset_task7_scenario":
        asyncio.run(reset_task7_scenario())
    elif command == "reset_prescription_scenario":
        asyncio.run(reset_prescription_scenario())
    elif command == "reset_procurement_scenario":
        asyncio.run(reset_procurement_scenario())
    elif command == "reset_p28_scenario":
        asyncio.run(reset_p28_scenario())
    elif command == "seed_p28":
        asyncio.run(seed_p28())
    elif command == "seed_p28_scenario":
        asyncio.run(seed_p28_scenario())
    elif command == "reset_p30_scenario":
        asyncio.run(reset_p30_scenario())
    elif command == "seed_p30_scenario":
        asyncio.run(seed_p30_scenario())
    elif command == "snapshot_p30":
        asyncio.run(snapshot_p30())
    elif command == "cleanup":
        asyncio.run(cleanup())
    elif command == "snapshot":
        requested_visit = uuid.UUID(sys.argv[2]) if len(sys.argv) > 2 else VISIT_ID
        asyncio.run(snapshot(requested_visit))
    else:
        raise ValueError(f"Unsupported command: {command}")
