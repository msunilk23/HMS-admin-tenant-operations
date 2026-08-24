"""Focused security tests for the Super Admin tenant-admin reset boundary."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.super_admin import (
    TenantAdminPasswordResetRequest,
    reset_tenant_admin_password,
)
from app.core.dependencies import require_role


class AdminResult:
    def __init__(self, admins):
        self.admins = admins

    def scalars(self):
        return self

    def all(self):
        return self.admins


class Session:
    def __init__(self, tenant, admins):
        self.tenant = tenant
        self.admins = admins
        self.added = []
        self.commits = 0

    async def get(self, model, key):
        return self.tenant if str(key) == str(self.tenant.id) else None

    async def execute(self, _statement):
        return AdminResult(self.admins)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def request():
    return Request({"type": "http", "client": ("198.51.100.20", 1234), "headers": []})


def state(role="hospital_admin", tenant_id=None, active=True):
    tenant_id = tenant_id or uuid.uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True, schema_name="hospital_a")
    admin = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=active,
        username="hospitaladmin", email="admin@example.test", hashed_password="old-hash",
        must_change_password=False, password_changed_at=None, session_version=4,
        tokens_valid_after=None,
    )
    return tenant, admin


@pytest.mark.asyncio
async def test_active_super_admin_resets_only_active_hospital_admin(monkeypatch):
    tenant, admin = state()
    session = Session(tenant, [admin])
    monkeypatch.setattr("app.api.v1.super_admin.allow_tenant_admin_password_reset", lambda *_: _allowed())
    monkeypatch.setattr("app.api.v1.super_admin.generate_temp_password", lambda: "SecureTemp9!")
    monkeypatch.setattr("app.api.v1.super_admin.hash_password", lambda value: f"bcrypt:{value}")
    monkeypatch.setattr("app.api.v1.super_admin.invalidate_tenant_status_cache", lambda *_: _allowed())
    monkeypatch.setattr("app.services.audit_service.get_audit_request_context", lambda: ("req-123", "198.51.100.20"))

    result = await reset_tenant_admin_password(
        tenant.id, TenantAdminPasswordResetRequest(reason="Account recovery request"), request(), session,
        {"sub": str(uuid.uuid4()), "role": "super_admin"},
    )

    assert result.temporary_password == "SecureTemp9!"
    assert admin.hashed_password == "bcrypt:SecureTemp9!"
    assert admin.must_change_password is True
    assert admin.session_version == 5
    assert admin.tokens_valid_after is not None
    assert session.commits == 1
    audit = session.added[0]
    assert audit.action == "TENANT_ADMIN_PASSWORD_RESET"
    assert audit.tenant_id == tenant.id
    assert audit.target_user_id == admin.id
    assert audit.reason == "Account recovery request"
    assert audit.request_id == "req-123"
    assert audit.source_ip == "198.51.100.20"
    assert "password" not in audit.__dict__


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["hospital_admin", "doctor", "nurse", "receptionist"])
async def test_non_super_admin_roles_are_rejected(role):
    check = require_role("super_admin")
    with pytest.raises(HTTPException) as error:
        await check({"role": role})
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_inactive_tenant_and_non_admin_target_are_rejected(monkeypatch):
    tenant, admin = state(role="nurse")
    tenant.is_active = False
    session = Session(tenant, [admin])
    monkeypatch.setattr("app.api.v1.super_admin.allow_tenant_admin_password_reset", lambda *_: _allowed())
    with pytest.raises(HTTPException) as error:
        await reset_tenant_admin_password(
            tenant.id, TenantAdminPasswordResetRequest(reason="Recovery requested by tenant"), request(), session,
            {"sub": str(uuid.uuid4()), "role": "super_admin"},
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_multiple_active_admins_are_ambiguous(monkeypatch):
    tenant, admin = state()
    second_values = dict(admin.__dict__)
    second_values["id"] = uuid.uuid4()
    second = SimpleNamespace(**second_values)
    session = Session(tenant, [admin, second])
    monkeypatch.setattr("app.api.v1.super_admin.allow_tenant_admin_password_reset", lambda *_: _allowed())
    with pytest.raises(HTTPException) as error:
        await reset_tenant_admin_password(
            tenant.id, TenantAdminPasswordResetRequest(reason="Recovery requested by tenant"), request(), session,
            {"sub": str(uuid.uuid4()), "role": "super_admin"},
        )
    assert error.value.status_code == 409


def _allowed():
    async def result():
        return True
    return result()
