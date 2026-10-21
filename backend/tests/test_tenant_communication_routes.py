import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.models.public.tenant_integration import TenantCommunicationRoute
from app.services.tenant_integration_service import (
    get_msg91_sms_provider,
    list_communication_routes,
    rotate_secret,
    set_communication_route,
    submit_secret,
)


class Result:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class Session:
    def __init__(self, scalar_values=(), routes=()):
        self.scalar_values = list(scalar_values)
        self.routes = list(routes)
        self.statements = []
        self.added = []
        self.commits = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.scalar_values.pop(0)

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.routes)

    def add(self, value):
        self.added.append(value)

    async def delete(self, _value):
        return None

    async def commit(self):
        self.commits += 1


class SecretStore:
    def __init__(self):
        self.stored = []
        self.invalidated = []

    async def store_secret(self, **kwargs):
        self.stored.append(kwargs)
        return "ciphertext", "nonce", "AES-256-GCM", "k1"

    def invalidate_cache(self, **kwargs):
        self.invalidated.append(kwargs)


@pytest.mark.asyncio
async def test_tenant_can_select_independent_enabled_provider_per_channel():
    tenant_id = uuid.uuid4()
    msg91_connection = SimpleNamespace(credential_version=1)
    twilio_connection = SimpleNamespace(credential_version=2)
    session = Session(
        scalar_values=[
            msg91_connection, object(), None,
            twilio_connection, object(), None,
        ],
    )

    sms = await set_communication_route(
        session=session,
        tenant_id=tenant_id,
        channel="sms",
        provider="MSG91",
        environment="test",
    )
    whatsapp = await set_communication_route(
        session=session,
        tenant_id=tenant_id,
        channel="whatsapp",
        provider="twilio",
        environment="LIVE",
    )

    routes = [item for item in session.added if isinstance(item, TenantCommunicationRoute)]
    assert sms == {"channel": "SMS", "provider": "msg91", "environment": "TEST"}
    assert whatsapp == {"channel": "WHATSAPP", "provider": "twilio", "environment": "LIVE"}
    assert [(route.channel, route.provider, route.environment, route.tenant_id) for route in routes] == [
        ("SMS", "msg91", "TEST", tenant_id),
        ("WHATSAPP", "twilio", "LIVE", tenant_id),
    ]
    assert session.commits == 2
    assert all(tenant_id in statement.compile().params.values() for statement in session.statements)


@pytest.mark.asyncio
async def test_msg91_cannot_be_selected_for_whatsapp_before_whatsapp_support():
    session = Session()
    with pytest.raises(ValueError, match="does not support the WHATSAPP"):
        await set_communication_route(
            session=session,
            tenant_id=uuid.uuid4(),
            channel="WHATSAPP",
            provider="msg91",
            environment="TEST",
        )
    assert session.statements == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_route_requires_an_enabled_provider_connection_for_same_tenant():
    tenant_id = uuid.uuid4()
    session = Session(scalar_values=[None])
    with pytest.raises(ValueError, match="enabled communication provider connection"):
        await set_communication_route(
            session=session,
            tenant_id=tenant_id,
            channel="SMS",
            provider="msg91",
            environment="TEST",
        )
    assert tenant_id in session.statements[0].compile().params.values()
    assert session.commits == 0


@pytest.mark.asyncio
async def test_route_listing_returns_only_channel_provider_and_environment():
    tenant_id = uuid.uuid4()
    session = Session(routes=[
        SimpleNamespace(channel="SMS", provider="msg91", environment="TEST"),
    ])
    assert await list_communication_routes(session=session, tenant_id=tenant_id) == {
        "SMS": {"provider": "msg91", "environment": "TEST"},
        "WHATSAPP": None,
    }
    assert tenant_id in session.statements[0].compile().params.values()


@pytest.mark.asyncio
async def test_msg91_auth_key_rotation_keeps_credential_version_tenant_scoped_to_communication():
    tenant_id = uuid.uuid4()
    connection = SimpleNamespace(
        credential_version=1,
        provider="msg91",
        capability="communication",
        environment="TEST",
        status="TEST",
    )
    session = Session(scalar_values=[connection])
    store = SecretStore()

    result = await rotate_secret(
        session=session,
        tenant_id=tenant_id,
        provider="msg91",
        environment="TEST",
        credential_type="auth_key",
        secret="tenant-auth-key",
        secret_store=store,
    )

    credential = next(item for item in session.added if hasattr(item, "secret_ciphertext"))
    audit = next(item for item in session.added if hasattr(item, "event_type"))
    assert result["credential_version"] == 2
    assert credential.capability == "communication"
    assert audit.capability == "communication"
    assert store.stored[0]["tenant_id"] == tenant_id
    assert store.stored[0]["provider"] == "msg91"
    assert store.stored[0]["secret"] == "tenant-auth-key"
    assert "secret" not in result


@pytest.mark.asyncio
async def test_msg91_submitted_auth_key_uses_communication_credential_scope():
    tenant_id = uuid.uuid4()
    session = Session()
    store = SecretStore()

    await submit_secret(
        session=session,
        tenant_id=tenant_id,
        provider="msg91",
        environment="TEST",
        credential_type="auth_key",
        secret="tenant-auth-key",
        credential_version=1,
        secret_store=store,
    )

    credential = next(item for item in session.added if hasattr(item, "secret_ciphertext"))
    audit = next(item for item in session.added if hasattr(item, "event_type"))
    assert credential.capability == "communication"
    assert audit.capability == "communication"
    assert store.stored[0]["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_msg91_provider_resolution_uses_only_the_tenant_sms_route_and_credentials(monkeypatch):
    tenant_id = uuid.uuid4()
    route = SimpleNamespace(provider="msg91", channel="SMS", environment="TEST")
    connection = SimpleNamespace(
        provider="msg91",
        capability="communication",
        environment="TEST",
        credential_version=3,
        status="TEST",
        public_configuration={
            "otp_template_id": "tenant-otp-template",
            "sms_template_id": "tenant-sms-template",
        },
    )
    session = Session(scalar_values=[route, connection])
    monkeypatch.setattr(
        "app.services.tenant_integration_service.get_persisted_secret",
        lambda **kwargs: _async_secret(kwargs, tenant_id),
    )
    captured = {}

    def handler(request):
        captured["request"] = request
        return httpx.Response(200, json={"type": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = await get_msg91_sms_provider(
            session=session,
            tenant_id=tenant_id,
            http_client=client,
        )
        await provider.send_sms(to="9876543210")

    assert captured["request"].headers["authkey"] == "tenant-msg91-key"
    assert captured["request"].read() == (
        b'{"template_id":"tenant-sms-template","recipients":'
        b'[{"mobiles":"+919876543210"}]}'
    )
    assert all(tenant_id in statement.compile().params.values() for statement in session.statements)


@pytest.mark.asyncio
async def test_msg91_provider_resolution_rejects_other_tenant_route():
    tenant_id = uuid.uuid4()
    session = Session(scalar_values=[None])

    with pytest.raises(ValueError, match="not configured for this tenant"):
        await get_msg91_sms_provider(session=session, tenant_id=tenant_id)
    assert tenant_id in session.statements[0].compile().params.values()


def _async_secret(kwargs, tenant_id):
    async def result():
        assert kwargs["tenant_id"] == tenant_id
        assert kwargs["provider"] == "msg91"
        assert kwargs["capability"] == "communication"
        assert kwargs["credential_version"] == 3
        return '{"auth_key": "tenant-msg91-key"}'

    return result()
