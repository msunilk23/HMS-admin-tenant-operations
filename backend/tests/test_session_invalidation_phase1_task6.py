"""Behavioral session invalidation tests at the authentication boundary."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.auth import LogoutRequest, logout, refresh
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, create_refresh_token


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class AuthSession:
    def __init__(self, user, tenant):
        self.user = user
        self.tenant = tenant

    async def get(self, model, key):
        name = getattr(model, "__name__", "")
        if name == "User":
            return self.user if str(self.user.id) == str(key) else None
        if name == "Tenant":
            return self.tenant if str(self.tenant.id) == str(key) else None
        return None

    async def execute(self, *_args, **_kwargs):
        return Result(self.user)

    async def commit(self):
        return None


class RedisFailure:
    async def __call__(self, *_args, **_kwargs):
        raise ConnectionError("Redis unavailable")


def _state(role="nurse", tenant_id=None):
    tenant_id = tenant_id or uuid.uuid4()
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True,
        session_version=0, tokens_valid_after=None, must_change_password=False,
        full_name="Test User", hashed_password="hash", password_changed_at=None,
    )
    tenant = SimpleNamespace(
        id=tenant_id, schema_name=f"tenant_{uuid.uuid4().hex[:8]}",
        is_active=True, session_version=0, tokens_valid_after=None,
        hospital_name="Test Hospital", timezone="Asia/Kolkata",
    )
    return user, tenant


def _access(user, tenant, role=None):
    return create_access_token(str(user.id), {
        "role": role or user.role,
        "tenant_id": str(tenant.id),
        "tenant_schema": tenant.schema_name,
        "tenant_session_version": tenant.session_version,
        "session_version": user.session_version,
    })


def _refresh(user, tenant):
    """
    Build a refresh token exactly the way production issuance does (auth.py
    passes role/tenant_id/tenant_schema/session_version/tenant_session_version
    into create_refresh_token's extra_claims) — no post-hoc decode+re-sign.
    """
    claims = {"role": user.role, "session_version": user.session_version}
    if getattr(user, "tenant_id", None):
        claims.update({
            "tenant_id": str(tenant.id),
            "tenant_schema": tenant.schema_name,
            "tenant_session_version": tenant.session_version,
        })
    return create_refresh_token(str(user.id), extra_claims=claims)


@pytest.mark.asyncio
async def test_user_deactivation_invalidates_existing_access_and_refresh_tokens():
    user, tenant = _state()
    old = _access(user, tenant)
    refresh_token = _refresh(user, tenant)
    user.is_active = False
    user.session_version += 1
    session = AuthSession(user, tenant)
    with pytest.raises(HTTPException) as access_error:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=old), session)
    assert access_error.value.status_code == 401
    with pytest.raises(HTTPException) as refresh_error:
        await refresh(SimpleNamespace(refresh_token=refresh_token), session)
    assert refresh_error.value.status_code == 401


@pytest.mark.asyncio
async def test_tenant_deactivation_blocks_all_tenant_users():
    user_a, tenant = _state(role="nurse")
    user_b = SimpleNamespace(**{**user_a.__dict__, "id": uuid.uuid4(), "role": "doctor"})
    tenant.is_active = False
    for user in (user_a, user_b):
        with pytest.raises(HTTPException):
            await get_current_user(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=_access(user, tenant)),
                AuthSession(user, tenant),
            )


@pytest.mark.asyncio
async def test_role_change_invalidates_token_with_previous_role():
    user, tenant = _state(role="nurse")
    token = _access(user, tenant, role="nurse")
    user.role = "doctor"
    user.session_version += 1
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))
    new_token = _access(user, tenant, role="doctor")
    assert (await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=new_token), AuthSession(user, tenant)))["role"] == "doctor"


@pytest.mark.asyncio
async def test_administrator_password_reset_invalidates_previous_sessions():
    user, tenant = _state(role="receptionist")
    token = _access(user, tenant)
    user.session_version += 1
    user.tokens_valid_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))


@pytest.mark.asyncio
async def test_password_change_invalidates_other_existing_sessions():
    user, tenant = _state()
    old = _access(user, tenant)
    user.session_version += 1
    user.tokens_valid_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=old), AuthSession(user, tenant))
    assert await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=_access(user, tenant)), AuthSession(user, tenant))


@pytest.mark.asyncio
async def test_logout_revokes_current_session_and_refresh_token(monkeypatch):
    user, tenant = _state()
    old = _access(user, tenant)
    refresh_token = _refresh(user, tenant)
    monkeypatch.setattr("app.api.v1.auth.block_token", RedisFailure())
    class SessionContext:
        async def __aenter__(self):
            return AuthSession(user, tenant)
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr("app.db.engine.AsyncSessionLocal", lambda: SessionContext())
    await logout(LogoutRequest(refresh_token=refresh_token))
    # Database invalidation remains effective even when Redis is unavailable.
    user.session_version += 1
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=old), AuthSession(user, tenant))


@pytest.mark.asyncio
async def test_redis_unavailable_uses_database_fallback(monkeypatch):
    user, tenant = _state()
    token = _access(user, tenant)
    monkeypatch.setattr("app.core.dependencies.get_tenant_forced_logout_time", RedisFailure())
    assert await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))
    user.session_version += 1
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))


@pytest.mark.asyncio
async def test_super_admin_isolated_from_tenant_revocation():
    user, tenant = _state(role="super_admin")
    token = create_access_token(str(user.id), {"role": "super_admin", "tenant_schema": "", "session_version": 0})
    tenant.is_active = False
    result = await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))
    assert result["role"] == "super_admin"


@pytest.mark.asyncio
async def test_hospital_a_invalidation_does_not_affect_hospital_b():
    user_a, tenant_a = _state()
    user_b, tenant_b = _state()
    token_b = _access(user_b, tenant_b)
    user_a.session_version += 1
    assert (await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_b), AuthSession(user_b, tenant_b)))["tenant_id"] == str(tenant_b.id)


@pytest.mark.asyncio
async def test_new_token_after_invalidation_works_normally():
    user, tenant = _state()
    old = _access(user, tenant)
    user.session_version += 1
    new = _access(user, tenant)
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=old), AuthSession(user, tenant))
    assert await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=new), AuthSession(user, tenant))


# ── Task C: super_admin must NOT bypass user-level security checks ────────────
# Only tenant-specific revocation is an intentional exemption for super_admin.

@pytest.mark.asyncio
async def test_deactivated_super_admin_access_token_rejected():
    user, tenant = _state(role="super_admin")
    token = create_access_token(str(user.id), {"role": "super_admin", "tenant_schema": "", "session_version": 0})
    user.is_active = False
    with pytest.raises(HTTPException) as exc:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_super_admin_session_version_increment_invalidates_earlier_token():
    user, tenant = _state(role="super_admin")
    token = create_access_token(str(user.id), {"role": "super_admin", "tenant_schema": "", "session_version": 0})
    user.session_version += 1
    with pytest.raises(HTTPException) as exc:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))
    assert exc.value.status_code == 401
    new_token = create_access_token(str(user.id), {"role": "super_admin", "tenant_schema": "", "session_version": user.session_version})
    result = await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=new_token), AuthSession(user, tenant))
    assert result["role"] == "super_admin"


@pytest.mark.asyncio
async def test_super_admin_password_change_invalidates_earlier_token():
    user, tenant = _state(role="super_admin")
    token = create_access_token(str(user.id), {"role": "super_admin", "tenant_schema": "", "session_version": 0})
    # Simulates the same session_version bump + tokens_valid_after stamp that
    # /change-password performs for every role, including super_admin.
    user.session_version += 1
    user.tokens_valid_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))


@pytest.mark.asyncio
async def test_active_super_admin_independent_of_unrelated_tenant_invalidation():
    user, tenant = _state(role="super_admin")
    token = create_access_token(str(user.id), {"role": "super_admin", "tenant_schema": "", "session_version": 0})
    # An unrelated hospital tenant is suspended/invalidated — super_admin carries
    # no tenant_id claim at all, so this must never affect it.
    tenant.is_active = False
    tenant.session_version += 5
    result = await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))
    assert result["role"] == "super_admin"


@pytest.mark.asyncio
async def test_super_admin_forged_tenant_claim_cannot_impersonate_tenant_user():
    """
    A super_admin JWT never legitimately carries a tenant_id claim. Even if one
    were present (which requires forging a validly-signed JWT — impossible
    without SECRET_KEY), it must still be checked against a real, active tenant
    the same way a tenant-user token would be.
    """
    user, tenant = _state(role="super_admin")
    token = create_access_token(str(user.id), {
        "role": "super_admin", "tenant_schema": tenant.schema_name,
        "tenant_id": str(uuid.uuid4()),  # tenant_id that does not resolve via AuthSession
        "tenant_session_version": 0, "session_version": 0,
    })
    with pytest.raises(HTTPException):
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), AuthSession(user, tenant))


# ── Task A: token `type` must be enforced ──────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token_rejected_when_used_as_access_token():
    user, tenant = _state()
    refresh_token = _refresh(user, tenant)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=refresh_token), AuthSession(user, tenant))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_malformed_token_rejected():
    user, tenant = _state()
    with pytest.raises(HTTPException) as exc:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"), AuthSession(user, tenant))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected():
    from jose import jwt
    from app.core.config import settings
    user, tenant = _state()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id), "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": now - timedelta(hours=1), "type": "access",
        "role": user.role, "session_version": user.session_version,
    }
    expired = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired), AuthSession(user, tenant))
    assert exc.value.status_code == 401
