import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.engine import get_session
from app.core.redis_client import get_cached_features, set_cached_features, get_tenant_forced_logout_time
from app.models.public.user import Tenant, User

bearer_scheme = HTTPBearer()
logger = logging.getLogger(__name__)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Decode JWT and return the current user payload dict."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    session_invalidated_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Your session has been invalidated. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            raise credentials_exception

        token_iat = payload.get("iat")
        user = await session.get(User, user_id)
        # User-level checks apply to EVERY role, including super_admin: existence,
        # active flag, session_version and forced-logout (tokens_valid_after) must
        # always be enforced. Only tenant-level revocation is exempt for super_admin
        # (a platform operator has no tenant context).
        if not user or not user.is_active:
            raise session_invalidated_exception
        if payload.get("session_version", 0) != getattr(user, "session_version", 0):
            raise session_invalidated_exception
        if user.tokens_valid_after and token_iat is not None and token_iat < int(user.tokens_valid_after.timestamp()):
            raise session_invalidated_exception

        # Check forced-logout for tenant users — super_admin is never bound to a
        # tenant so it never carries a tenant_id claim and this block is skipped
        # for that role naturally.
        tenant_id_str = payload.get("tenant_id")
        if tenant_id_str:
            tenant = await session.get(Tenant, tenant_id_str)
            if not tenant or not tenant.is_active:
                raise session_invalidated_exception
            if payload.get("tenant_session_version", 0) != tenant.session_version:
                raise session_invalidated_exception
            if tenant.tokens_valid_after and token_iat is not None and token_iat < int(tenant.tokens_valid_after.timestamp()):
                raise session_invalidated_exception
            try:
                forced_logout_time = await get_tenant_forced_logout_time(tenant_id_str)
            except Exception:
                forced_logout_time = None
            if forced_logout_time is not None:
                token_iat = payload.get("iat")
                if token_iat is not None and token_iat < int(forced_logout_time):
                    raise session_invalidated_exception

        return payload
    except HTTPException:
        raise
    except JWTError:
        raise credentials_exception


def require_role(*roles: str):
    """Dependency factory: enforces that the JWT role is one of the allowed roles."""

    async def _check(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        if current_user.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _check


def require_permission(*permissions: str):
    """Compatibility wrapper for dependency and direct service authorization checks."""
    if permissions and not all(isinstance(permission, str) for permission in permissions):
        session = permissions[0]
        user_id = permissions[1]
        requested_permissions = permissions[2:]
        if not requested_permissions:
            raise ValueError("A permission code is required")

        async def _direct_check() -> bool:
            from app.models.public.user import User
            from app.models.public.permission import Permission, RolePermission

            user = await session.get(User, str(user_id)) if user_id is not None else None
            if user is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not found")
            role = getattr(user, "role", None)
            if not role or role == "super_admin":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

            allowed = await session.scalar(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(
                    RolePermission.role == role,
                    Permission.code.in_(requested_permissions),
                    Permission.is_active == True,  # noqa: E712
                )
                .limit(1)
            )
            if allowed is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
            return True

        return _direct_check()

    async def _check(
        current_user: Annotated[dict, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict:
        role = current_user.get("role")
        if not role or role == "super_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        from app.models.public.permission import Permission, RolePermission

        allowed = await session.scalar(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(
                RolePermission.role == role,
                Permission.code.in_(permissions),
                Permission.is_active == True,  # noqa: E712
            )
            .limit(1)
        )
        if allowed is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _check


async def require_tenant_user(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """
    Blocks super_admin from all tenant-scoped endpoints.
    super_admin operates exclusively through /super/* routes and has no
    tenant schema context, so any attempt to reach tenant data must be
    rejected at the backend regardless of frontend state.
    """
    if current_user.get("role") == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin cannot access tenant resources.",
        )
    return current_user


def require_feature(feature: str):
    """
    Dependency factory: enforces that the authenticated tenant has a feature enabled.

    Enforcement order (most authoritative first):
      1. Redis cache — populated on login and refreshed every 5 min. Invalidated
         immediately when a super_admin toggles a feature, so disabling a feature
         takes effect for all active sessions within seconds.
      2. Database — fallback when the cache key is absent (first request after
         invalidation or after a Redis restart). Result is written back to cache.

    The JWT features claim is intentionally NOT trusted here; it can be up to
    60 minutes stale. Redis is the source of truth for live enforcement.
    """

    async def _check(
        current_user: Annotated[dict, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict:
        await ensure_feature_enabled(feature, current_user, session)
        return current_user

    return _check


async def ensure_feature_enabled(
    feature: str,
    current_user: dict,
    session: AsyncSession,
) -> None:
    """Enforce a feature from authoritative tenant data, with optional Redis cache."""
    import uuid
    from app.models.public.tenant_feature import TenantFeature

    tenant_id_str = current_user.get("tenant_id")
    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant feature context is missing; please sign in again.",
        )
    try:
        tenant_id = uuid.UUID(str(tenant_id_str))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid tenant feature context") from exc

    enabled: list[str] | None = None
    try:
        enabled = await get_cached_features(tenant_id)
    except Exception:
        logger.warning("Tenant feature cache unavailable; reading PostgreSQL", exc_info=True)

    if enabled is None:
        rows = await session.execute(
            select(TenantFeature.feature)
            .where(TenantFeature.tenant_id == tenant_id, TenantFeature.enabled == True)  # noqa: E712
        )
        enabled = [row[0] for row in rows.fetchall()]
        try:
            await set_cached_features(tenant_id, enabled)
        except Exception:
            logger.warning("Tenant feature cache write failed", exc_info=True)

    if feature not in enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Feature '{feature}' is not enabled for your hospital's plan.",
        )
