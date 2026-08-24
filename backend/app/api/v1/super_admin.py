"""
Super Admin — Tenant Management API.

All endpoints require role=super_admin.
Allows viewing, configuring, suspending, and managing feature entitlements
for every tenant hospital in the system.
"""
import asyncio
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.core.features import ALL_FEATURES, PLAN_FEATURES
from app.core.redis_client import invalidate_feature_cache, invalidate_tenant_status_cache
from app.core.security import hash_password, generate_temp_password
from app.db.engine import get_session
from app.models.public.tenant_feature import TenantFeature
from app.models.public.user import Tenant, User

router = APIRouter(dependencies=[Depends(require_role("super_admin"))])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TenantListItem(BaseModel):
    id: uuid.UUID
    hospital_name: str
    schema_name: str
    contact_email: str
    contact_phone: str | None
    logo_url: str | None
    primary_color: str | None
    secondary_color: str | None
    plan: str
    is_active: bool
    enabled_features: list[str]
    feature_count: int

    model_config = {"from_attributes": True}


class TenantDetail(BaseModel):
    id: uuid.UUID
    hospital_name: str
    schema_name: str
    contact_email: str
    contact_phone: str | None
    logo_url: str | None
    primary_color: str | None
    secondary_color: str | None
    plan: str
    is_active: bool
    features: dict[str, bool]   # {feature_key: enabled}

    model_config = {"from_attributes": True}


class TenantUpdate(BaseModel):
    hospital_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    plan: str | None = None
    is_active: bool | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None


class FeatureBulkSet(BaseModel):
    enabled_features: list[str]     # keys that should be enabled; rest are disabled


class FeatureToggle(BaseModel):
    enabled: bool


class CreateTenantRequest(BaseModel):
    hospital_name: str
    schema_name: str        # lowercase, alphanumeric + underscore
    contact_email: str
    contact_phone: str | None = None
    plan: str = "starter"
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None


class CreateTenantResponse(BaseModel):
    id: uuid.UUID
    hospital_name: str
    schema_name: str
    contact_email: str
    contact_phone: str | None
    logo_url: str | None
    primary_color: str | None
    secondary_color: str | None
    plan: str
    username: str
    default_password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_tenant_or_404(tenant_id: uuid.UUID, session: AsyncSession) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _validate_schema_name(schema_name: str) -> None:
    if not re.match(r'^[a-z][a-z0-9_]{1,62}$', schema_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="schema_name must start with a lowercase letter, contain only lowercase letters, digits, and underscores, and be 2–63 characters.",
        )
    if schema_name in {"public", "information_schema", "pg_catalog", "pg_toast"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Schema name '{schema_name}' is reserved.",
        )


def _validate_color(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    color = value.strip()
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        raise HTTPException(status_code=422, detail=f"{field} must be a 6-digit hex color such as #2563eb.")
    return color.lower()
async def _generate_admin_username(session: AsyncSession) -> str:
    """Return 'hospitalAdmin', 'hospitalAdmin2', … — first globally available."""
    base = "hospitalAdmin"
    candidate = base
    for i in range(2, 1000):
        exists = (await session.execute(
            select(User.id).where(User.username == candidate)
        )).scalar_one_or_none()
        if not exists:
            return candidate
        candidate = f"{base}{i}"
    raise RuntimeError("Could not generate unique admin username")


def _run_alembic_upgrade() -> None:
    """Blocking — run in thread pool. Runs 'alembic upgrade head' for all tenants (idempotent)."""
    import subprocess
    proc = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


async def _get_feature_map(tenant_id: uuid.UUID, session: AsyncSession) -> dict[str, bool]:
    """Return {feature_key: enabled} for all known features for this tenant."""
    rows = await session.execute(
        select(TenantFeature.feature, TenantFeature.enabled).where(
            TenantFeature.tenant_id == tenant_id
        )
    )
    db_map = {row[0]: row[1] for row in rows.fetchall()}
    # Fill in any features not yet in DB as disabled
    return {f: db_map.get(f, False) for f in ALL_FEATURES}


async def _upsert_features(
    tenant_id: uuid.UUID,
    feature_map: dict[str, bool],
    session: AsyncSession,
) -> None:
    """Upsert TenantFeature rows according to the provided feature_map."""
    existing_rows = (await session.execute(
        select(TenantFeature).where(TenantFeature.tenant_id == tenant_id)
    )).scalars().all()
    existing = {row.feature: row for row in existing_rows}

    for feature, enabled in feature_map.items():
        if feature in existing:
            existing[feature].enabled = enabled
        else:
            session.add(TenantFeature(tenant_id=tenant_id, feature=feature, enabled=enabled))
    await session.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/features", response_model=list[str])
async def list_features() -> list[str]:
    """Return the canonical list of all known feature keys."""
    return ALL_FEATURES


@router.get("/hospitals", response_model=list[TenantListItem])
async def list_tenants(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all tenant hospitals with plan, status, and enabled feature summary."""
    tenants = (await session.execute(
        select(Tenant).order_by(Tenant.hospital_name)
    )).scalars().all()

    result = []
    for tenant in tenants:
        feature_map = await _get_feature_map(tenant.id, session)
        enabled = [k for k, v in feature_map.items() if v]
        result.append(TenantListItem(
            id=tenant.id,
            hospital_name=tenant.hospital_name,
            schema_name=tenant.schema_name,
            contact_email=tenant.contact_email,
            contact_phone=tenant.contact_phone,
            logo_url=tenant.logo_url,
            primary_color=tenant.primary_color,
            secondary_color=tenant.secondary_color,
            plan=tenant.plan,
            is_active=tenant.is_active,
            enabled_features=enabled,
            feature_count=len(enabled),
        ))
    return result


@router.get("/hospitals/{tenant_id}", response_model=TenantDetail)
async def get_tenant(
    tenant_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> TenantDetail:
    """Get a single tenant with all feature toggle states."""
    tenant = await _get_tenant_or_404(tenant_id, session)
    feature_map = await _get_feature_map(tenant.id, session)
    return TenantDetail(
        id=tenant.id,
        hospital_name=tenant.hospital_name,
        schema_name=tenant.schema_name,
        contact_email=tenant.contact_email,
        contact_phone=tenant.contact_phone,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
        plan=tenant.plan,
        is_active=tenant.is_active,
        features=feature_map,
    )


@router.patch("/hospitals/{tenant_id}", response_model=TenantDetail)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    session: AsyncSession = Depends(get_session),
) -> TenantDetail:
    """Update a tenant's hospital_name, plan, or is_active status."""
    tenant = await _get_tenant_or_404(tenant_id, session)

    if body.hospital_name is not None:
        name = body.hospital_name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="hospital_name cannot be empty.")
        tenant.hospital_name = name

    if body.contact_email is not None:
        email = body.contact_email.strip()
        if not email:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="contact_email cannot be empty.")
        tenant.contact_email = email

    if body.contact_phone is not None:
        tenant.contact_phone = body.contact_phone.strip() or None

    if body.plan is not None:
        if body.plan not in PLAN_FEATURES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid plan '{body.plan}'. Must be one of: {list(PLAN_FEATURES.keys())}",
            )
        tenant.plan = body.plan

    if body.is_active is not None:
        tenant.is_active = body.is_active
        tenant.session_version += 1
        tenant.tokens_valid_after = datetime.now(timezone.utc)

    if body.logo_url is not None:
        tenant.logo_url = body.logo_url.strip() or None
    if body.primary_color is not None:
        tenant.primary_color = _validate_color(body.primary_color, "primary_color")
    if body.secondary_color is not None:
        tenant.secondary_color = _validate_color(body.secondary_color, "secondary_color")

    await session.commit()
    await session.refresh(tenant)

    if body.is_active is not None:
        # Deactivating (or reactivating) a tenant must take effect immediately —
        # invalidate the tenant-status cache used by TenantMiddleware and force
        # all existing sessions for this tenant to re-authenticate.
        await invalidate_tenant_status_cache(tenant.id)
        await invalidate_feature_cache(tenant.id)

    feature_map = await _get_feature_map(tenant.id, session)
    return TenantDetail(
        id=tenant.id,
        hospital_name=tenant.hospital_name,
        schema_name=tenant.schema_name,
        contact_email=tenant.contact_email,
        contact_phone=tenant.contact_phone,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
        plan=tenant.plan,
        is_active=tenant.is_active,
        features=feature_map,
    )


@router.put("/hospitals/{tenant_id}/features", response_model=TenantDetail)
async def bulk_set_features(
    tenant_id: uuid.UUID,
    body: FeatureBulkSet,
    session: AsyncSession = Depends(get_session),
) -> TenantDetail:
    """
    Bulk-set all features for a tenant.
    Features in enabled_features → enabled=True; all others → enabled=False.
    Typically called when changing a tenant's plan.
    """
    tenant = await _get_tenant_or_404(tenant_id, session)

    # Validate keys
    invalid = [f for f in body.enabled_features if f not in ALL_FEATURES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown feature keys: {invalid}",
        )

    feature_map = {f: (f in body.enabled_features) for f in ALL_FEATURES}
    await _upsert_features(tenant.id, feature_map, session)
    await invalidate_feature_cache(tenant.id)

    # Refresh and return
    updated_map = await _get_feature_map(tenant.id, session)
    return TenantDetail(
        id=tenant.id,
        hospital_name=tenant.hospital_name,
        schema_name=tenant.schema_name,
        contact_email=tenant.contact_email,
        contact_phone=tenant.contact_phone,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
        plan=tenant.plan,
        is_active=tenant.is_active,
        features=updated_map,
    )


@router.patch("/hospitals/{tenant_id}/features/{feature}", response_model=TenantDetail)
async def toggle_feature(
    tenant_id: uuid.UUID,
    feature: str,
    body: FeatureToggle,
    session: AsyncSession = Depends(get_session),
) -> TenantDetail:
    """Toggle a single feature on or off for a tenant."""
    if feature not in ALL_FEATURES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown feature '{feature}'. Must be one of: {ALL_FEATURES}",
        )

    tenant = await _get_tenant_or_404(tenant_id, session)

    existing = (await session.execute(
        select(TenantFeature).where(
            TenantFeature.tenant_id == tenant_id,
            TenantFeature.feature == feature,
        )
    )).scalar_one_or_none()

    if existing:
        existing.enabled = body.enabled
    else:
        session.add(TenantFeature(tenant_id=tenant_id, feature=feature, enabled=body.enabled))

    await session.commit()
    await invalidate_feature_cache(tenant_id)

    feature_map = await _get_feature_map(tenant.id, session)
    return TenantDetail(
        id=tenant.id,
        hospital_name=tenant.hospital_name,
        schema_name=tenant.schema_name,
        contact_email=tenant.contact_email,
        contact_phone=tenant.contact_phone,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
        plan=tenant.plan,
        is_active=tenant.is_active,
        features=feature_map,
    )


@router.post("/hospitals", response_model=CreateTenantResponse, status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    session: AsyncSession = Depends(get_session),
) -> CreateTenantResponse:
    """
    Provision a new tenant hospital:
    1. Validate & create Tenant record
    2. Create PostgreSQL schema
    3. Seed plan features
    4. Run alembic upgrade head (provisions schema tables)
    5. Create default hospital_admin user (username=hospitalAdmin, password=securely generated, must change on first login)
    """
    _validate_schema_name(body.schema_name)

    if body.plan not in PLAN_FEATURES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid plan. Must be one of: {list(PLAN_FEATURES.keys())}",
        )

    primary_color = _validate_color(body.primary_color, "primary_color")
    secondary_color = _validate_color(body.secondary_color, "secondary_color")

    # Uniqueness check
    dup_schema = (await session.execute(
        select(Tenant.id).where(Tenant.schema_name == body.schema_name)
    )).scalar_one_or_none()
    if dup_schema:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Schema '{body.schema_name}' is already in use.")

    dup_email = (await session.execute(
        select(Tenant.id).where(Tenant.contact_email == body.contact_email)
    )).scalar_one_or_none()
    if dup_email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A tenant with email '{body.contact_email}' already exists.")

    # 1. Create Tenant record
    tenant = Tenant(
        id=uuid.uuid4(),
        hospital_name=body.hospital_name,
        schema_name=body.schema_name,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
        logo_url=body.logo_url.strip() if body.logo_url else None,
        primary_color=primary_color,
        secondary_color=secondary_color,
        plan=body.plan,
        is_active=True,
    )
    session.add(tenant)
    await session.flush()   # assigns tenant.id before commit

    # 2. Create PostgreSQL schema
    await session.execute(text("SET search_path TO public"))
    await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{body.schema_name}"'))
    await session.commit()

    # 3. Seed plan features (run after commit so tenant.id is stable)
    plan_feature_map = {f: (f in PLAN_FEATURES[body.plan]) for f in ALL_FEATURES}
    await _upsert_features(tenant.id, plan_feature_map, session)

    # 4. Run alembic upgrade head in a thread (picks up new schema from DB)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_alembic_upgrade)
    except Exception as exc:
        # Best-effort rollback: drop schema + delete tenant + features
        await session.execute(text(f'DROP SCHEMA IF EXISTS "{body.schema_name}" CASCADE'))
        await session.execute(sa_delete(TenantFeature).where(TenantFeature.tenant_id == tenant.id))
        stale = await session.get(Tenant, tenant.id)
        if stale:
            await session.delete(stale)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Schema migration failed — tenant rolled back. Details: {exc}",
        )

    # 5. Create default hospital_admin user
    username = await _generate_admin_username(session)
    # Unique, cryptographically random per tenant creation — never a fixed/predictable
    # value. Returned exactly once in this super_admin-only response as the approved
    # one-time credential handoff; the account must change it on first login.
    default_password = generate_temp_password()
    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tenant_name=body.schema_name,
        email=f"admin@{body.schema_name}.local",
        username=username,
        hashed_password=hash_password(default_password),
        full_name="Hospital Admin",
        role="hospital_admin",
        must_change_password=True,
        password_changed_at=None,
    )
    session.add(admin)
    await session.commit()

    return CreateTenantResponse(
        id=tenant.id,
        hospital_name=tenant.hospital_name,
        schema_name=tenant.schema_name,
        contact_email=tenant.contact_email,
        contact_phone=tenant.contact_phone,
        logo_url=tenant.logo_url,
        primary_color=tenant.primary_color,
        secondary_color=tenant.secondary_color,
        plan=tenant.plan,
        username=username,
        default_password=default_password,
    )


@router.delete("/hospitals/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Permanently delete a tenant:
    1. Delete all TenantFeature rows
    2. Delete all User rows belonging to this tenant
    3. Delete the Tenant record
    4. Drop the PostgreSQL schema (CASCADE — removes all tables)
    """
    tenant = await _get_tenant_or_404(tenant_id, session)
    schema_name = tenant.schema_name

    await session.execute(sa_delete(TenantFeature).where(TenantFeature.tenant_id == tenant_id))
    await session.execute(sa_delete(User).where(User.tenant_id == tenant_id))
    await session.delete(tenant)
    await session.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
    await session.commit()
