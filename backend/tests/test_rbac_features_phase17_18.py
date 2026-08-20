import os
import uuid

import pytest

os.environ.setdefault("SECRET_KEY", "phase17-18-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

from fastapi import HTTPException

from app.core import dependencies


class FeatureRows:
    def __init__(self, features):
        self.features = features

    def fetchall(self):
        return [(feature,) for feature in self.features]


class FeatureSession:
    async def execute(self, _statement):
        return FeatureRows(["billing"])


@pytest.mark.asyncio
async def test_require_role_rejects_forbidden_role():
    check = dependencies.require_role("doctor")

    with pytest.raises(HTTPException) as error:
        await check({"role": "billing_officer"})

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_feature_check_rejects_missing_tenant_context(monkeypatch):
    with pytest.raises(HTTPException) as error:
        await dependencies.ensure_feature_enabled("billing", {"role": "billing_officer"}, FeatureSession())

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_feature_check_uses_cache_and_rejects_disabled_feature(monkeypatch):
    tenant_id = str(uuid.uuid4())
    monkeypatch.setattr(dependencies, "get_cached_features", lambda _tenant: _features(["billing"]))

    await dependencies.ensure_feature_enabled(
        "billing", {"tenant_id": tenant_id, "role": "billing_officer"}, FeatureSession()
    )
    with pytest.raises(HTTPException) as error:
        await dependencies.ensure_feature_enabled(
            "lab", {"tenant_id": tenant_id, "role": "billing_officer"}, FeatureSession()
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_feature_check_falls_back_to_postgres_when_redis_is_unavailable(monkeypatch):
    tenant_id = str(uuid.uuid4())

    async def unavailable(_tenant):
        raise ConnectionError("redis unavailable")

    async def no_op_cache(_tenant, _features):
        return None

    monkeypatch.setattr(dependencies, "get_cached_features", unavailable)
    monkeypatch.setattr(dependencies, "set_cached_features", no_op_cache)

    await dependencies.ensure_feature_enabled(
        "billing", {"tenant_id": tenant_id, "role": "billing_officer"}, FeatureSession()
    )


def _features(features):
    async def loader(_tenant):
        return features

    return loader
