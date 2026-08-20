from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.core.dependencies import get_current_user
from app.core.security import verify_password, hash_password, create_access_token, create_refresh_token, decode_token
from app.core.redis_client import block_token, is_token_blocked, set_cached_features, get_tenant_forced_logout_time
from app.models.public.user import User, Tenant
from app.models.public.tenant_feature import TenantFeature
from app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest, ChangePasswordRequest

router = APIRouter()


async def _load_enabled_features(tenant_id, session: AsyncSession) -> list[str]:
    """
    Return the list of feature keys that are enabled for this tenant.
    Called by both login and refresh so the JWT and Redis cache are always consistent.
    """
    rows = await session.execute(
        select(TenantFeature.feature)
        .where(TenantFeature.tenant_id == tenant_id, TenantFeature.enabled == True)  # noqa: E712
    )
    features = [row[0] for row in rows.fetchall()]
    # Warm the Redis feature cache so require_feature reads from Redis, not the JWT
    await set_cached_features(tenant_id, features)
    return features


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    # Login accepts either email or username
    result = await session.execute(
        select(User).where(
            or_(User.email == payload.login_id, User.username == payload.login_id),
            User.is_active == True,  # noqa: E712
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    # super_admin is a platform operator — not bound to any hospital tenant.
    if user.role == "super_admin":
        extra_claims = {
            "role": "super_admin",
            "tenant_schema": "",
            "hospital_name": "",
            "full_name": user.full_name,
            "features": [],
            "must_change_password": False,
        }
    else:
        # Fetch the hospital tenant and enforce it must be active.
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.id == user.tenant_id)
        )
        tenant = tenant_result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital account is inactive",
            )
        extra_claims = {
            "role": user.role,
            "tenant_id": str(user.tenant_id),
            "tenant_schema": tenant.schema_name,
            "hospital_name": tenant.hospital_name,
            "logo_url": getattr(tenant, "logo_url", None),
            "primary_color": getattr(tenant, "primary_color", None),
            "secondary_color": getattr(tenant, "secondary_color", None),
            "full_name": user.full_name,
            "features": await _load_enabled_features(user.tenant_id, session),
            "must_change_password": bool(user.must_change_password),
        }

    access_token = create_access_token(subject=str(user.id), extra_claims=extra_claims)
    refresh_token = create_refresh_token(subject=str(user.id))

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        must_change_password=bool(user.must_change_password) if user.role != "super_admin" else False,
        logo_url=extra_claims.get("logo_url"),
        primary_color=extra_claims.get("primary_color"),
        secondary_color=extra_claims.get("secondary_color"),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, session: AsyncSession = Depends(get_session)):
    from jose import JWTError
    try:
        token_data = decode_token(payload.refresh_token)
        if token_data.get("type") != "refresh":
            raise ValueError
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Blocklist check — reject logged-out tokens immediately
    jti = token_data.get("jti")
    if jti and await is_token_blocked(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")

    result = await session.execute(
        select(User).where(User.id == token_data["sub"], User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Forced-logout check — reject refresh tokens issued before a feature-toggle event
    if user.role != "super_admin" and user.tenant_id:
        forced_logout_time = await get_tenant_forced_logout_time(str(user.tenant_id))
        if forced_logout_time is not None:
            token_iat = token_data.get("iat")
            if token_iat is not None and token_iat < forced_logout_time:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Your session has been invalidated. Please log in again.",
                )

    if user.role == "super_admin":
        extra_claims = {
            "role": "super_admin",
            "tenant_schema": "",
            "hospital_name": "",
            "full_name": user.full_name,
            "features": [],
            "must_change_password": False,
        }
    else:
        tenant_result = await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hospital account is inactive")
        extra_claims = {
            "role": user.role,
            "tenant_id": str(user.tenant_id),
            "tenant_schema": tenant.schema_name,
            "hospital_name": tenant.hospital_name,
            "logo_url": getattr(tenant, "logo_url", None),
            "primary_color": getattr(tenant, "primary_color", None),
            "secondary_color": getattr(tenant, "secondary_color", None),
            "full_name": user.full_name,
            "features": await _load_enabled_features(user.tenant_id, session),
            "must_change_password": bool(user.must_change_password),
        }

    access_token = create_access_token(subject=str(user.id), extra_claims=extra_claims)
    new_refresh = create_refresh_token(subject=str(user.id))
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        must_change_password=bool(user.must_change_password) if user.role != "super_admin" else False,
        logo_url=extra_claims.get("logo_url"),
        primary_color=extra_claims.get("primary_color"),
        secondary_color=extra_claims.get("secondary_color"),
    )


class LogoutRequest(BaseModel):
    refresh_token: str


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest):
    """
    Revoke a refresh token by adding its JTI to the Redis blocklist.
    The blocklist entry expires when the token itself would have expired,
    so Redis memory is self-managed.
    """
    from datetime import datetime, timezone
    from jose import JWTError
    try:
        token_data = decode_token(payload.refresh_token)
    except JWTError:
        # Already invalid — treat as successfully logged out
        return

    jti = token_data.get("jti")
    exp = token_data.get("exp")
    if jti and exp:
        remaining = int(exp - datetime.now(timezone.utc).timestamp())
        if remaining > 0:
            await block_token(jti, remaining)


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    payload: ChangePasswordRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Allow any authenticated user to change their own password and return refreshed tokens."""
    user_id: str = current_user.get("sub")
    user = (await session.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    await session.commit()

    if user.role == "super_admin":
        extra_claims = {
            "role": "super_admin",
            "tenant_schema": "",
            "hospital_name": "",
            "full_name": user.full_name,
            "features": [],
            "must_change_password": False,
        }
    else:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hospital account is inactive")
        extra_claims = {
            "role": user.role,
            "tenant_id": str(user.tenant_id),
            "tenant_schema": tenant.schema_name,
            "hospital_name": tenant.hospital_name,
            "logo_url": getattr(tenant, "logo_url", None),
            "primary_color": getattr(tenant, "primary_color", None),
            "secondary_color": getattr(tenant, "secondary_color", None),
            "full_name": user.full_name,
            "features": await _load_enabled_features(user.tenant_id, session),
            "must_change_password": False,
        }

    access_token = create_access_token(subject=str(user.id), extra_claims=extra_claims)
    refresh_token = create_refresh_token(subject=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, must_change_password=False)
