"""
Seed script — run once to create the first tenant and super_admin user.

Usage (from backend/ directory):
  python -m app.scripts.seed
"""

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.engine import AsyncSessionLocal, init_db
from app.models.public.user import Tenant, User


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
    "password": "ChangeMe@123",  # must be changed on first login
}

SUPER_ADMIN_USER = {
    "email": "superadmin@smarthosp.in",
    "username": "superadmin",
    "full_name": "Platform Super Admin",
    "role": "super_admin",
    "password": "SuperAdmin@123",
}


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
        print("✅ Seed complete.")
        print(f"   Tenant:      {TENANT_DATA['hospital_name']} (schema: {SHANKAR_SCHEMA})")
        print(f"   Admin:       {ADMIN_USER['email']} / {ADMIN_USER['password']}  (username: {ADMIN_USER['username']})")
        print(f"   SuperAdmin:  {SUPER_ADMIN_USER['email']} / {SUPER_ADMIN_USER['password']}  (username: {SUPER_ADMIN_USER['username']})") 
        print("   ⚠️  Change default passwords immediately after first login.")


if __name__ == "__main__":
    asyncio.run(seed())
