"""
Seed script — run once to create the first tenant and super_admin user.

Usage (from backend/ directory):
  python -m app.scripts.seed
"""

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, generate_temp_password
from app.db.engine import AsyncSessionLocal, init_db
from app.models.public.user import Tenant, User
from app.models.tenant.department import Department
from app.models.tenant.dosage_form import DosageForm
from app.models.tenant.generic_medicine import GenericMedicine
from app.models.tenant.hospital_formulary import HospitalFormulary
from app.models.tenant.manufacturer import Manufacturer
from app.models.tenant.medicine_product import MedicineProduct
from app.models.tenant.route import Route


SHANKAR_SCHEMA = "shankar"

TENANT_DATA = {
    "hospital_name": "Shankar Super Speciality Hospital",
    "schema_name": SHANKAR_SCHEMA,
    "contact_email": "admin@shankar-hospital.in",
}

ADMIN_USER = {
    "email": "admin@shankar-hospital.in",
    "username": "hospitaladmin",
    "full_name": "Hospital Admin",
    "role": "hospital_admin",
    "password": generate_temp_password(),  # unique per run; must change on first login
}

SUPER_ADMIN_USER = {
    "email": "superadmin@smarthosp.in",
    "username": "superadmin",
    "full_name": "Platform Super Admin",
    "role": "super_admin",
    "password": generate_temp_password(),  # unique per run; must change on first login
}


async def _get_or_create(session: AsyncSession, model, lookup: dict, values: dict | None = None):
    item = await session.scalar(select(model).filter_by(**lookup))
    if item:
        return item
    item = model(**lookup, **(values or {}))
    session.add(item)
    await session.flush()
    return item


async def seed_pharmacy_data(session: AsyncSession) -> None:
    """Seed the stable demo pharmacy catalog in the active tenant schema."""
    await session.execute(text(f'SET search_path TO "{SHANKAR_SCHEMA}", public'))

    outpatient = await _get_or_create(session, Department, {"name": "Outpatient"}, {"description": "General outpatient department"})
    emergency = await _get_or_create(session, Department, {"name": "Emergency"}, {"description": "Emergency care department"})

    forms = {}
    for code, name, calculation_type, is_active in (
        ("TABLET", "Tablet", "UNIT", True),
        ("CAPSULE", "Capsule", "UNIT", True),
        ("SYRUP", "Syrup", "LIQUID", True),
        ("INJECTION", "Injection", "MANUAL", True),
        ("LEGACY_FORM", "Legacy form", "MANUAL", False),
    ):
        forms[code] = await _get_or_create(
            session,
            DosageForm,
            {"code": code},
            {"name": name, "calculation_type": calculation_type, "is_active": is_active},
        )

    routes = {}
    for code, name, is_active in (
        ("ORAL", "Oral", True),
        ("IV", "Intravenous", True),
        ("IM", "Intramuscular", True),
        ("LEGACY_ROUTE", "Legacy route", False),
    ):
        routes[code] = await _get_or_create(session, Route, {"code": code}, {"name": name, "is_active": is_active})

    manufacturers = {}
    for code, name, gstin, country, is_active in (
        ("CIPLA", "Cipla Limited", "27AAACC1457E1Z2", "India", True),
        ("GSK", "GlaxoSmithKline", None, "United Kingdom", True),
        ("SUN", "Sun Pharmaceutical", "24AAKCS0950L1Z4", "India", True),
        ("LEGACY_MFR", "Legacy manufacturer", None, "India", False),
    ):
        manufacturers[code] = await _get_or_create(
            session,
            Manufacturer,
            {"code": code},
            {"name": name, "gstin": gstin, "country": country, "is_active": is_active},
        )

    generics = {}
    for code, name, therapeutic_class, is_active in (
        ("PARACETAMOL", "Paracetamol", "Analgesic", True),
        ("AMOXICILLIN", "Amoxicillin", "Antibiotic", True),
        ("AZITHROMYCIN", "Azithromycin", "Antibiotic", True),
        ("OMEPRAZOLE", "Omeprazole", "PPI", True),
        ("CETIRIZINE", "Cetirizine", "Antihistamine", True),
        ("IBUPROFEN", "Ibuprofen", "NSAID", True),
        ("CIPROFLOXACIN", "Ciprofloxacin", "Antibiotic", True),
        ("DICLOFENAC", "Diclofenac", "NSAID", True),
        ("LEGACY_GENERIC", "Legacy generic", "Other", False),
    ):
        generics[code] = await _get_or_create(
            session,
            GenericMedicine,
            {"code": code},
            {"name": name, "therapeutic_class": therapeutic_class, "is_active": is_active},
        )

    products = {}
    product_rows = (
        ("DOLO-500-TAB", "PARACETAMOL", "Dolo", "500", "mg", "TABLET", "ORAL", "CIPLA", True),
        ("CROCIN-650-TAB", "PARACETAMOL", "Crocin", "650", "mg", "TABLET", "ORAL", "GSK", True),
        ("MOX-500-CAP", "AMOXICILLIN", "Mox", "500", "mg", "CAPSULE", "ORAL", "SUN", True),
        ("AZI-500-TAB", "AZITHROMYCIN", "Azithro", "500", "mg", "TABLET", "ORAL", "CIPLA", True),
        ("OMZ-20-CAP", "OMEPRAZOLE", "Omz", "20", "mg", "CAPSULE", "ORAL", "SUN", True),
        ("CET-10-TAB", "CETIRIZINE", "Cetiriz", "10", "mg", "TABLET", "ORAL", "CIPLA", True),
        ("IBU-400-TAB", "IBUPROFEN", "Ibu", "400", "mg", "TABLET", "ORAL", "SUN", True),
        ("CIP-500-TAB", "CIPROFLOXACIN", "Ciprobid", "500", "mg", "TABLET", "ORAL", "CIPLA", True),
        ("DIC-50-TAB", "DICLOFENAC", "Diclo", "50", "mg", "TABLET", "ORAL", "SUN", True),
        ("DOLO-SYRUP", "PARACETAMOL", "Dolo Syrup", "250", "mg/5ml", "SYRUP", "ORAL", "CIPLA", True),
        ("AMOX-INJ", "AMOXICILLIN", "Amox Injection", "500", "mg", "INJECTION", "IM", "SUN", True),
        ("LEGACY-PRODUCT", "LEGACY_GENERIC", "Legacy Product", "1", "unit", "LEGACY_FORM", "ORAL", "LEGACY_MFR", False),
    )
    for code, generic_code, brand, strength, unit, form_code, route_code, manufacturer_code, is_active in product_rows:
        products[code] = await _get_or_create(
            session,
            MedicineProduct,
            {"code": code},
            {
                "generic_medicine_id": generics[generic_code].id,
                "brand_name": brand,
                "strength": strength,
                "unit": unit,
                "dosage_form_id": forms[form_code].id,
                "default_route_id": routes[route_code].id,
                "manufacturer_id": manufacturers[manufacturer_code].id,
                "composition": f"{generics[generic_code].name} {strength}{unit}",
                "gst_rate": 12,
                "schedule_category": "OTC" if generic_code in {"PARACETAMOL", "CETIRIZINE", "IBUPROFEN"} else "SCHEDULE_H",
                "requires_prescription": generic_code not in {"PARACETAMOL", "CETIRIZINE", "IBUPROFEN"},
                "is_active": is_active,
            },
        )

    formulary_rows = (
        ("DOLO-500-TAB", outpatient, True, True),
        ("CROCIN-650-TAB", outpatient, True, True),
        ("MOX-500-CAP", outpatient, True, True),
        ("AZI-500-TAB", outpatient, True, True),
        ("OMZ-20-CAP", outpatient, True, True),
        ("CET-10-TAB", outpatient, True, True),
        ("IBU-400-TAB", outpatient, True, True),
        ("DIC-50-TAB", outpatient, True, True),
        ("DOLO-SYRUP", outpatient, True, True),
        ("AMOX-INJ", emergency, True, True),
        ("DOLO-500-TAB", emergency, True, True),
        ("CROCIN-650-TAB", emergency, True, False),
        ("MOX-500-CAP", emergency, False, False),
        ("LEGACY-PRODUCT", outpatient, True, True),
    )
    for product_code, department, is_approved, is_prescribable in formulary_rows:
        await _get_or_create(
            session,
            HospitalFormulary,
            {"medicine_product_id": products[product_code].id, "department_id": department.id},
            {"is_approved": is_approved, "is_prescribable": is_prescribable},
        )


async def seed():
    await init_db()

    async with AsyncSessionLocal() as session:
        # Set search_path to public for seed
        await session.execute(text("SET search_path TO public"))

        # Create tenant
        tenant = Tenant(
            id=uuid.uuid4(),
            **TENANT_DATA,
        )
        session.add(tenant)
        await session.flush()

        # Create PostgreSQL schema for Shankar
        await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SHANKAR_SCHEMA}"'))

        # Create hospital admin user
        admin = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            tenant_name=SHANKAR_SCHEMA,
            email=ADMIN_USER["email"],
            username=ADMIN_USER["username"],
            hashed_password=hash_password(ADMIN_USER["password"]),
            full_name=ADMIN_USER["full_name"],
            role=ADMIN_USER["role"],
        )
        session.add(admin)

        # Create super admin user (no specific tenant — uses same tenant for storage)
        super_admin = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            tenant_name=SHANKAR_SCHEMA,
            email=SUPER_ADMIN_USER["email"],
            username=SUPER_ADMIN_USER["username"],
            hashed_password=hash_password(SUPER_ADMIN_USER["password"]),
            full_name=SUPER_ADMIN_USER["full_name"],
            role=SUPER_ADMIN_USER["role"],
        )
        session.add(super_admin)

        await session.commit()
        await seed_pharmacy_data(session)
        await session.commit()
        print("✅ Seed complete.")
        print(f"   Tenant:      {TENANT_DATA['hospital_name']} (schema: {SHANKAR_SCHEMA})")
        print(f"   Admin:       {ADMIN_USER['email']} / {ADMIN_USER['password']}  (username: {ADMIN_USER['username']})")
        print(f"   SuperAdmin:  {SUPER_ADMIN_USER['email']} / {SUPER_ADMIN_USER['password']}  (username: {SUPER_ADMIN_USER['username']})") 
        print("   ⚠️  Change default passwords immediately after first login.")


if __name__ == "__main__":
    asyncio.run(seed())
