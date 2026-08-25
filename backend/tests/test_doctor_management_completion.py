"""Focused doctor onboarding and password-reset security tests."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.doctors import reset_doctor_password
from app.core.dependencies import require_role
from app.schemas.doctor_reset import DoctorPasswordResetRequest


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class Session:
    def __init__(self, tenant, doctor, user):
        self.tenant = tenant
        self.doctor = doctor
        self.user = user
        self.added = []
        self.commits = 0

    async def execute(self, statement):
        text = str(statement)
        if "tenants" in text:
            return Result(self.tenant)
        if "doctors" in text:
            return Result(self.doctor)
        return Result(self.user)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def _request():
    return Request({"type": "http", "client": ("203.0.113.10", 1234), "headers": []})


def _state(role="doctor"):
    tenant_id = uuid.uuid4()
    tenant = SimpleNamespace(id=tenant_id, schema_name="tenant_a", hospital_name="Hospital A")
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=True,
        username="doctor_a", phone="+919876543210", full_name="Dr A",
        hashed_password="old", must_change_password=False,
        password_changed_at=None, session_version=2, tokens_valid_after=None,
    )
    doctor = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, tenant_id=tenant_id, is_active=True)
    return tenant, doctor, user


@pytest.mark.asyncio
async def test_hospital_admin_reset_hashes_and_invalidates_doctor(monkeypatch):
    tenant, doctor, user = _state()
    session = Session(tenant, doctor, user)
    monkeypatch.setattr("app.api.v1.doctors.allow_tenant_admin_password_reset", lambda *_: _allowed(True))
    monkeypatch.setattr("app.api.v1.doctors.generate_temp_password", lambda: "DoctorTemp9!")
    monkeypatch.setattr("app.api.v1.doctors.hash_password", lambda value: f"bcrypt:{value}")

    result = await reset_doctor_password(
        doctor.id,
        DoctorPasswordResetRequest(reason="Doctor requested account recovery", send_via="none"),
        session,
        {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": tenant.schema_name},
    )

    assert result.temporary_password == "DoctorTemp9!"
    assert result.phone == "******3210"
    assert user.hashed_password == "bcrypt:DoctorTemp9!"
    assert user.must_change_password is True
    assert user.session_version == 3
    assert session.commits == 1
    assert session.added[0].action == "DOCTOR_PASSWORD_RESET"
    assert "DoctorTemp9!" not in session.added[0].reason


@pytest.mark.asyncio
async def test_non_hospital_roles_cannot_reset_doctor():
    for role in ("receptionist", "doctor", "nurse", "super_admin"):
        with pytest.raises(HTTPException) as error:
            await require_role("hospital_admin")({"role": role})
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_target_must_have_doctor_role(monkeypatch):
    tenant, doctor, user = _state(role="hospital_admin")
    monkeypatch.setattr("app.api.v1.doctors.allow_tenant_admin_password_reset", lambda *_: _allowed(True))
    with pytest.raises(HTTPException) as error:
        await reset_doctor_password(
            doctor.id,
            DoctorPasswordResetRequest(reason="Account recovery requested", send_via="none"),
            Session(tenant, doctor, user),
            {"sub": str(uuid.uuid4()), "role": "hospital_admin", "tenant_schema": tenant.schema_name},
        )
    assert error.value.status_code == 404


def _allowed(value):
    async def result():
        return value
    return result()
