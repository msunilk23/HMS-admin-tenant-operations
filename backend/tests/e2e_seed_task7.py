"""Deterministic isolated PostgreSQL fixture for the Task 7 Playwright suite."""
import asyncio
import json
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
HOSPITAL_B_DOCTOR_USERNAME = "e2e_doctor_task7_b"
HOSPITAL_B_DOCTOR_EMAIL = "e2e-doctor-task7-b@example.test"
HOSPITAL_B_DOCTOR_PASSWORD = "E2eDoctorB@123"

TENANT_A_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-tenant-a")
TENANT_B_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-tenant-b")
DOCTOR_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor")
RECEPTIONIST_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-receptionist")
ADMIN_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-admin")
HOSPITAL_B_DOCTOR_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-b")
DOCTOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-profile")
HOSPITAL_B_DOCTOR_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-doctor-profile-b")
DEPARTMENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-department")
HOSPITAL_B_DEPARTMENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-department-b")
PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hms-e2e-task7-patient")
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
        await conn.execute(text('DELETE FROM public.users WHERE id IN (:doctor_id, :receptionist_id, :admin_id, :doctor_b_id) OR username IN (:doctor_username, :receptionist_username, :admin_username, :doctor_b_username)'), {
            "doctor_id": DOCTOR_USER_ID,
            "receptionist_id": RECEPTIONIST_USER_ID,
            "admin_id": ADMIN_USER_ID,
            "doctor_b_id": HOSPITAL_B_DOCTOR_USER_ID,
            "doctor_username": DOCTOR_USERNAME,
            "receptionist_username": RECEPTIONIST_USERNAME,
            "admin_username": ADMIN_USERNAME,
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
        user_b = User(id=HOSPITAL_B_DOCTOR_USER_ID, tenant_id=TENANT_B_ID, tenant_name=SCHEMA_B, email=HOSPITAL_B_DOCTOR_EMAIL, username=HOSPITAL_B_DOCTOR_USERNAME, hashed_password=hash_password(HOSPITAL_B_DOCTOR_PASSWORD), full_name="E2E Doctor B", role="doctor", is_active=True, must_change_password=False)
        session.add_all([tenant_a, tenant_b, user_a, receptionist_a, admin_a, user_b])
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
        session.add_all([department, doctor, patient, visit, vitals, icd_active, icd_inactive, generic_a, form_a, route_a, manufacturer_a, product_a, product_a_capsule, med_table, med_capsule, med_inactive, supplier_a])
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


async def cleanup():
    from app.core.config import settings
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_A}" CASCADE'))
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_B}" CASCADE'))
        await conn.execute(delete(User).where(User.id.in_([DOCTOR_USER_ID, RECEPTIONIST_USER_ID, ADMIN_USER_ID, HOSPITAL_B_DOCTOR_USER_ID])))
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
    }
    print(json.dumps(payload, default=str))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "seed":
        asyncio.run(seed())
    elif command == "cleanup":
        asyncio.run(cleanup())
    elif command == "snapshot":
        requested_visit = uuid.UUID(sys.argv[2]) if len(sys.argv) > 2 else VISIT_ID
        asyncio.run(snapshot(requested_visit))
    else:
        raise ValueError(f"Unsupported command: {command}")
