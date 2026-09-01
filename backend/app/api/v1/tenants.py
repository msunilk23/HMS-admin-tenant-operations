from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.core.dependencies import require_role, require_tenant_user
from app.core.security import hash_password
from app.models.public.user import Tenant, User
from app.schemas.tenant import DisplayTokenRead, TenantBrandingRead, TenantBrandingUpdate, TenantCreate, TenantPublic
from app.services.audit_service import record_audit
from app.services.logo_service import save_tenant_logo

import secrets
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


def _display_token_response(tenant: Tenant) -> DisplayTokenRead:
    return DisplayTokenRead(
        display_token=tenant.display_token,
        display_url_path=f"/display/{tenant.schema_name}/{tenant.display_token}",
    )


@router.get("/branding", response_model=TenantBrandingRead)
async def get_tenant_branding(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_tenant_user),
):
    """Live logo/colors for the current tenant — polled so branding updates
    without waiting for the user's JWT to be reissued on next login/refresh."""
    tenant = await session.get(Tenant, uuid.UUID(current_user["tenant_id"]))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantBrandingRead(
        hospital_name=tenant.hospital_name,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
    )


@router.patch("/branding", response_model=TenantBrandingRead)
async def update_tenant_branding(
    payload: TenantBrandingUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Self-service brand color update — the tenant's own hospital_admin,
    no Super Admin involvement required."""
    tenant = await session.get(Tenant, uuid.UUID(current_user["tenant_id"]))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    old_value = {"primary_color": tenant.primary_color, "secondary_color": tenant.secondary_color}
    if payload.primary_color is not None:
        tenant.primary_color = payload.primary_color
    if payload.secondary_color is not None:
        tenant.secondary_color = payload.secondary_color

    record_audit(
        session,
        current_user=current_user,
        action="UPDATE",
        resource_type="tenant_branding",
        resource_id=tenant.id,
        old_value=old_value,
        new_value={"primary_color": tenant.primary_color, "secondary_color": tenant.secondary_color},
    )
    await session.commit()
    await session.refresh(tenant)
    return TenantBrandingRead(
        hospital_name=tenant.hospital_name,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
    )


@router.post("/branding/logo", response_model=TenantBrandingRead)
async def upload_own_tenant_logo(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Self-service logo upload — auto-derives brand colors from the image,
    same extraction used by the Super Admin console."""
    tenant = await session.get(Tenant, uuid.UUID(current_user["tenant_id"]))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    old_value = {"logo_url": tenant.logo_url, "primary_color": tenant.primary_color, "secondary_color": tenant.secondary_color}
    logo_url, primary_color, secondary_color = await save_tenant_logo(tenant.id, file)
    tenant.logo_url = logo_url
    tenant.primary_color = primary_color
    tenant.secondary_color = secondary_color

    record_audit(
        session,
        current_user=current_user,
        action="UPLOAD_LOGO",
        resource_type="tenant_branding",
        resource_id=tenant.id,
        old_value=old_value,
        new_value={"logo_url": logo_url, "primary_color": primary_color, "secondary_color": secondary_color},
    )
    await session.commit()
    return TenantBrandingRead(
        hospital_name=tenant.hospital_name,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
    )


@router.get("/display-token", response_model=DisplayTokenRead)
async def get_display_token(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """Return this hospital's current public-display-board credential and URL."""
    tenant = await session.get(Tenant, uuid.UUID(current_user["tenant_id"]))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _display_token_response(tenant)


@router.post("/display-token/rotate", response_model=DisplayTokenRead)
async def rotate_display_token(
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role("hospital_admin")),
):
    """
    Generate a new display-board credential, immediately revoking the old one.
    Any TV board still using the previous URL will be disconnected and must be
    reconfigured with the new URL — this is the intended revocation behaviour.
    """
    tenant = await session.get(Tenant, uuid.UUID(current_user["tenant_id"]))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.display_token = secrets.token_urlsafe(24)
    await session.commit()
    await session.refresh(tenant)
    return _display_token_response(tenant)

