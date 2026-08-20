"""
Redis client singleton for the backend.
Used for:
  - Refresh token JTI blocklist (logout / suspend)
  - Tenant feature cache (live enforcement, TTL 5 min)
  - Tenant forced-logout timestamp (feature toggle forces re-login)
  - WebSocket pub/sub (see websocket/redis_bridge.py)

Intentionally lightweight — one module-level client reused across requests.
"""
import json
import time
import uuid

import redis.asyncio as aioredis

from app.core.config import settings

# Key prefix for the token blocklist in Redis
_BLOCKLIST_PREFIX = "blocklist:jti:"

# Key prefix for tenant feature sets — value is a JSON list of enabled feature keys.
# TTL is intentionally short: super_admin toggling a feature takes effect within 5 min
# even for users who already have a live JWT.
_FEATURE_PREFIX = "tenant:features:"
_FEATURE_TTL = 300  # 5 minutes

# Key prefix for forced-logout timestamp — set when super_admin toggles tenant features.
# Any JWT whose iat < this timestamp is immediately rejected (access + refresh).
# TTL = refresh token lifetime so old refresh tokens can never be reused.
_FORCED_LOGOUT_PREFIX = "tenant:forced_logout:"
_FORCED_LOGOUT_TTL = 60 * 60 * 24 * 7  # 7 days (matches refresh token lifetime)

# Module-level singleton (lazily initialized; safe for asyncio)
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def block_token(jti: str, ttl_seconds: int) -> None:
    """Add a refresh token JTI to the blocklist with an expiry matching the token's remaining lifetime."""
    redis = get_redis()
    await redis.setex(f"{_BLOCKLIST_PREFIX}{jti}", ttl_seconds, "1")


async def is_token_blocked(jti: str) -> bool:
    """Return True if this token JTI has been revoked (logged out or tenant suspended)."""
    redis = get_redis()
    return await redis.exists(f"{_BLOCKLIST_PREFIX}{jti}") > 0


# ── Tenant feature cache ───────────────────────────────────────────────────────

def _feature_key(tenant_id: uuid.UUID | str) -> str:
    return f"{_FEATURE_PREFIX}{tenant_id}"


async def get_cached_features(tenant_id: uuid.UUID | str) -> list[str] | None:
    """
    Return the cached list of enabled feature keys for a tenant, or None if the
    cache entry has expired / doesn't exist yet.
    """
    redis = get_redis()
    raw = await redis.get(_feature_key(tenant_id))
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached_features(tenant_id: uuid.UUID | str, enabled_features: list[str]) -> None:
    """Write (or refresh) the feature cache for a tenant with a 5-minute TTL."""
    redis = get_redis()
    await redis.setex(_feature_key(tenant_id), _FEATURE_TTL, json.dumps(enabled_features))


async def invalidate_feature_cache(tenant_id: uuid.UUID | str) -> None:
    """
    Immediately remove the feature cache for a tenant and record a forced-logout
    timestamp. Any JWT (access or refresh) issued before this moment will be
    rejected, forcing all active users of this tenant to re-login.
    """
    redis = get_redis()
    await redis.delete(_feature_key(tenant_id))
    # Record the forced-logout wall-clock time so get_current_user can compare iat
    await redis.setex(
        f"{_FORCED_LOGOUT_PREFIX}{tenant_id}",
        _FORCED_LOGOUT_TTL,
        str(time.time()),
    )


async def get_tenant_forced_logout_time(tenant_id: uuid.UUID | str) -> float | None:
    """
    Return the Unix timestamp after which tokens are considered valid, or None if
    no forced-logout is in effect for this tenant.
    """
    redis = get_redis()
    val = await redis.get(f"{_FORCED_LOGOUT_PREFIX}{tenant_id}")
    return float(val) if val is not None else None
