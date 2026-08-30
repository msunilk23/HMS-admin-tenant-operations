import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

import pytest
from types import SimpleNamespace

from app.api.v1.auth import change_password, login
from app.schemas.auth import ChangePasswordRequest, LoginRequest


class DummyResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def __iter__(self):
        return iter(self._value)


class DummySession:
    def __init__(self, *values):
        self.values = list(values)
        self.index = 0

    async def execute(self, *_args, **_kwargs):
        assert self.index < len(self.values), "Test fixture did not provide a result for this query"
        value = self.values[self.index]
        self.index += 1
        return DummyResult(value)

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_login_returns_force_change_flag_for_new_staff(monkeypatch):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    access_call = {}
    refresh_call = {}
    user = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="receptionist",
        is_active=True,
        must_change_password=True,
        hashed_password="hashed",
        full_name="Asha Nurse",
        username="asha_nurse",
        email="asha@example.com",
        session_version=7,
    )
    tenant = SimpleNamespace(
        id=tenant_id,
        is_active=True,
        schema_name="demo_tenant",
        hospital_name="Demo Hospital",
        timezone="Asia/Kolkata",
        logo_url=None,
        primary_color=None,
        secondary_color=None,
        session_version=3,
    )

    def fake_create_access_token(subject, extra_claims=None):
        access_call["subject"] = subject
        access_call["claims"] = extra_claims
        return "access-token"

    def fake_create_refresh_token(subject, extra_claims=None):
        refresh_call["subject"] = subject
        refresh_call["claims"] = extra_claims
        return "refresh-token"

    monkeypatch.setattr("app.api.v1.auth.verify_password", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.api.v1.auth.create_access_token", fake_create_access_token)
    monkeypatch.setattr("app.api.v1.auth.create_refresh_token", fake_create_refresh_token)

    async def fake_load_features(*args, **kwargs):
        return ["pharmacy"]

    monkeypatch.setattr("app.api.v1.auth._load_enabled_features", fake_load_features)

    session = DummySession(user, tenant, [(facility_id,)])
    result = await login(LoginRequest(login_id="asha_nurse", password="Password@123"), session)

    assert result.access_token == "access-token"
    assert result.refresh_token == "refresh-token"
    assert result.must_change_password is True
    assert access_call["subject"] == str(user.id)
    assert access_call["claims"] == {
        "role": "receptionist",
        "tenant_id": str(tenant_id),
        "tenant_schema": "demo_tenant",
        "hospital_name": "Demo Hospital",
        "timezone": "Asia/Kolkata",
        "logo_url": None,
        "primary_color": None,
        "secondary_color": None,
        "full_name": "Asha Nurse",
        "features": ["pharmacy"],
        "must_change_password": True,
        "session_version": 7,
        "tenant_session_version": 3,
        "facility_id": str(facility_id),
    }
    assert refresh_call["subject"] == str(user.id)
    assert refresh_call["claims"] == {
        "role": "receptionist",
        "tenant_id": str(tenant_id),
        "tenant_schema": "demo_tenant",
        "session_version": 7,
        "tenant_session_version": 3,
    }
    assert session.index == 3


@pytest.mark.asyncio
async def test_change_password_resets_force_flag_and_updates_timestamp(monkeypatch):
    tenant_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    access_call = {}
    refresh_call = {}
    user = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="nurse",
        is_active=True,
        must_change_password=True,
        hashed_password="old_hash",
        full_name="Nurse Asha",
        username="nurse_asha",
        email="nurse@example.com",
        session_version=4,
    )
    tenant = SimpleNamespace(
        id=tenant_id,
        is_active=True,
        schema_name="demo_tenant",
        hospital_name="Demo Hospital",
        timezone="Asia/Kolkata",
        logo_url=None,
        primary_color=None,
        secondary_color=None,
        session_version=2,
    )

    def fake_create_access_token(subject, extra_claims=None):
        access_call["subject"] = subject
        access_call["claims"] = extra_claims
        return "new-access-token"

    def fake_create_refresh_token(subject, extra_claims=None):
        refresh_call["subject"] = subject
        refresh_call["claims"] = extra_claims
        return "new-refresh-token"

    monkeypatch.setattr("app.api.v1.auth.verify_password", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.api.v1.auth.hash_password", lambda password: f"hashed:{password}")
    monkeypatch.setattr("app.api.v1.auth.create_access_token", fake_create_access_token)
    monkeypatch.setattr("app.api.v1.auth.create_refresh_token", fake_create_refresh_token)

    async def fake_load_features(*args, **kwargs):
        return ["pharmacy"]

    monkeypatch.setattr("app.api.v1.auth._load_enabled_features", fake_load_features)

    session = DummySession(user, tenant, [(facility_id,)])
    result = await change_password(
        ChangePasswordRequest(current_password="Password@123", new_password="BrandNew@456"),
        session,
        {"sub": str(user.id)},
    )

    assert user.must_change_password is False
    assert user.password_changed_at is not None
    assert result.must_change_password is False
    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"
    assert access_call["subject"] == str(user.id)
    assert access_call["claims"] == {
        "role": "nurse",
        "tenant_id": str(tenant_id),
        "tenant_schema": "demo_tenant",
        "hospital_name": "Demo Hospital",
        "timezone": "Asia/Kolkata",
        "logo_url": None,
        "primary_color": None,
        "secondary_color": None,
        "full_name": "Nurse Asha",
        "features": ["pharmacy"],
        "must_change_password": False,
        "session_version": 5,
        "tenant_session_version": 2,
        "facility_id": str(facility_id),
    }
    assert refresh_call["subject"] == str(user.id)
    assert refresh_call["claims"] == {
        "role": "nurse",
        "tenant_id": str(tenant_id),
        "tenant_schema": "demo_tenant",
        "session_version": 5,
        "tenant_session_version": 2,
    }
    assert session.index == 3
