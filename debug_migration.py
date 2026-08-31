#!/usr/bin/env python
"""Debug script to understand migration issue with document_versions table."""
import os
import asyncio
import uuid
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine

os.environ["DATABASE_URL"] = "postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital"
os.environ["SECRET_KEY"] = "test-secret-key"

TEST_TENANT_SCHEMA = f"debug_mig_{uuid.uuid4().hex[:8]}"

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    
    print(f"\n=== Testing Migration for Schema: {TEST_TENANT_SCHEMA} ===\n")
    
    # Step 1: Create new tenant schema
    async with engine.begin() as conn:
        print("1. Creating schema...")
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_TENANT_SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{TEST_TENANT_SCHEMA}"'))
        print(f"   Schema created: {TEST_TENANT_SCHEMA}")
        
        # Step 2: Insert into public.tenants
        print("\n2. Registering tenant...")
        tenant_id = uuid.uuid4()
        await conn.execute(
            text(
                """
                INSERT INTO public.tenants (id, schema_name, hospital_name, contact_email, is_active, timezone, display_token)
                VALUES (:id, :schema, 'Debug Test Hospital', :email, true, 'Asia/Kolkata', :dt)
                """
            ),
            {"id": tenant_id, "schema": TEST_TENANT_SCHEMA, "email": f"{TEST_TENANT_SCHEMA}@example.test", "dt": uuid.uuid4().hex},
        )
        print(f"   Tenant registered: {tenant_id}")
    
    # Step 3: Check current state
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{TEST_TENANT_SCHEMA}", public'))
        
        print("\n3. Checking schema state BEFORE migration:")
        # Check if alembic_version exists
        result = await conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'alembic_version')"
            )
        )
        has_alembic = result.scalar()
        print(f"   alembic_version table exists: {has_alembic}")
        
        # Check if document_versions exists
        result = await conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'document_versions')"
            )
        )
        has_doc_versions = result.scalar()
        print(f"   document_versions table exists: {has_doc_versions}")
        
        # List all tables in schema
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() ORDER BY table_name"
            )
        )
        tables = result.scalars().all()
        print(f"   Total tables in schema: {len(tables)}")
        if tables:
            print(f"   Tables: {', '.join(tables[:10])}")
    
    # Step 4: Run alembic upgrade
    print("\n4. Running alembic upgrade head...")
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd="d:\\Personal\\HMS\\HMS-tenant\\backend",
        env={**os.environ},
        capture_output=True,
        text=True,
    )
    print(f"   Return code: {result.returncode}")
    if result.stderr:
        print(f"   Stderr: {result.stderr[:500]}")
    
    # Step 5: Check state AFTER migration
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{TEST_TENANT_SCHEMA}", public'))
        
        print("\n5. Checking schema state AFTER migration:")
        # Check if alembic_version exists
        result = await conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'alembic_version')"
            )
        )
        has_alembic = result.scalar()
        print(f"   alembic_version table exists: {has_alembic}")
        
        # Check alembic version
        if has_alembic:
            result = await conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"))
            version = result.scalar()
            print(f"   Current migration version: {version}")
        
        # Check if document_versions exists
        result = await conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'document_versions')"
            )
        )
        has_doc_versions = result.scalar()
        print(f"   document_versions table exists: {has_doc_versions}")
        
        # List all tables in schema
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() ORDER BY table_name"
            )
        )
        tables = result.scalars().all()
        print(f"   Total tables in schema: {len(tables)}")
        if tables:
            print(f"   Tables: {', '.join(tables[:15])}")
    
    # Cleanup
    async with engine.begin() as conn:
        print(f"\n6. Cleaning up...")
        await conn.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_TENANT_SCHEMA}" CASCADE'))
        print("   Cleanup complete")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
