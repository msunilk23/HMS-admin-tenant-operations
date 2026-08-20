from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.core.dependencies import require_role
from app.core.security import hash_password
from app.models.public.user import Tenant, User
from app.schemas.tenant import TenantCreate, TenantPublic

import uuid

router = APIRouter()

# All per-tenant schema tables to create (DDL run via Alembic at provision time)
_PROVISION_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS "{schema}";
"""


@router.post("", response_model=TenantPublic, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("super_admin")),
):
    # Sanitise schema name
    schema = payload.schema_name.lower().replace("-", "_")
    if not schema.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid schema name. Use lowercase letters, numbers, underscores only.")

    # Create tenant record
    tenant = Tenant(
        id=uuid.uuid4(),
        schema_name=schema,
        hospital_name=payload.hospital_name,
        contact_email=payload.contact_email,
    )
    session.add(tenant)
    await session.flush()  # get tenant.id before creating user

    # Create schema in PostgreSQL
    await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    # Create admin user for this tenant
    admin_user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tenant_name=schema,
        email=payload.admin_email,
        hashed_password=hash_password(payload.admin_password),
        full_name=payload.admin_full_name,
        role="hospital_admin",
        must_change_password=True,
        password_changed_at=None,
    )
    session.add(admin_user)
    await session.commit()
    await session.refresh(tenant)

    return TenantPublic(
        id=str(tenant.id),
        hospital_name=tenant.hospital_name,
        schema_name=tenant.schema_name,
        contact_email=tenant.contact_email,
        is_active=tenant.is_active,
    )
