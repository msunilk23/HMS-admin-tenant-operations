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
        if user_id is None:
            raise credentials_exception

        # Check forced-logout for tenant users — super_admin is never forced out
        tenant_id_str = payload.get("tenant_id")
        if tenant_id_str:
            forced_logout_time = await get_tenant_forced_logout_time(tenant_id_str)
            if forced_logout_time is not None:
                token_iat = payload.get("iat")
                if token_iat is not None and token_iat < forced_logout_time:
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
