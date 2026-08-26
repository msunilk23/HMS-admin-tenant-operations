import uuid

import pytest
from fastapi import HTTPException

from app.core.dependencies import require_permission


class FakeSession:
    def __init__(self, allowed: str | None):
        self.allowed = allowed

    async def scalar(self, _statement):
        return self.allowed


@pytest.mark.asyncio
async def test_permission_dependency_allows_matching_live_permission():
    check = require_permission("PHARMACY_MASTER_VIEW")
    user = {"sub": str(uuid.uuid4()), "role": "hospital_admin"}
    assert await check(user, FakeSession("PHARMACY_MASTER_VIEW")) == user


@pytest.mark.asyncio
async def test_permission_dependency_denies_missing_permission():
    check = require_permission("PHARMACY_MASTER_EDIT")
    user = {"sub": str(uuid.uuid4()), "role": "pharmacist"}
    with pytest.raises(HTTPException) as error:
        await check(user, FakeSession(None))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_permission_dependency_denies_super_admin_without_tenant_context():
    check = require_permission("PHARMACY_MASTER_VIEW")
    with pytest.raises(HTTPException) as error:
        await check({"role": "super_admin"}, FakeSession("PHARMACY_MASTER_VIEW"))
    assert error.value.status_code == 403
