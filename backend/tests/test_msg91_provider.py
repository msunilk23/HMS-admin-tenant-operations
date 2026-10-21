import httpx
import pytest

from app.integrations.msg91 import (
    MSG91Provider,
    MSG91ProviderError,
    MSG91TimeoutError,
)
from app.integrations.providers import get_provider_adapter


def _provider(client: httpx.AsyncClient) -> MSG91Provider:
    return MSG91Provider(
        auth_key="test-auth-key",
        otp_template_id="otp-approved-template",
        sms_template_id="sms-approved-template",
        client=client,
    )


@pytest.mark.asyncio
async def test_send_otp_posts_approved_template_and_normalized_mobile():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"type": "success", "request_id": "request-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _provider(client).send_otp(
            to="9876543210",
            otp_length=6,
            expiry_minutes=5,
        )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v5/otp"
    assert dict(request.url.params) == {
        "template_id": "otp-approved-template",
        "mobile": "+919876543210",
        "otp_length": "6",
        "otp_expiry": "5",
    }
    assert request.headers["authkey"] == "test-auth-key"
    assert result == {"type": "success", "request_id": "request-1"}


@pytest.mark.asyncio
async def test_verify_otp_gets_status_and_only_reports_boolean():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"type": "success", "message": "verified"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified = await _provider(client).verify_otp(to="+919876543210", otp="384729")

    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v5/otp/verify"
    assert dict(request.url.params) == {"mobile": "+919876543210", "otp": "384729"}
    assert verified is True


@pytest.mark.asyncio
async def test_invalid_otp_is_false_without_returning_provider_message():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "error", "message": "OTP did not match"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified = await _provider(client).verify_otp(to="9876543210", otp="000000")
    assert verified is False


@pytest.mark.asyncio
async def test_authentication_failure_during_verification_is_not_mistaken_for_invalid_otp():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "error", "message": "Invalid auth key"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MSG91ProviderError, match="rejected OTP"):
            await _provider(client).verify_otp(to="9876543210", otp="000000")


@pytest.mark.asyncio
async def test_otp_parameters_are_validated_before_provider_request():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="OTP length"):
            await _provider(client).send_otp(to="9876543210", otp_length=2)
        with pytest.raises(ValueError, match="expiry"):
            await _provider(client).send_otp(to="9876543210", expiry_minutes=0)


@pytest.mark.asyncio
async def test_resend_otp_uses_retry_endpoint_and_type():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"type": "success", "request_id": "request-2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _provider(client).resend_otp(to="9876543210")

    assert requests[0].method == "GET"
    assert requests[0].url.path == "/api/v5/otp/retry"
    assert dict(requests[0].url.params) == {"mobile": "+919876543210", "retrytype": "text"}
    assert result == {"type": "success", "request_id": "request-2"}


@pytest.mark.asyncio
async def test_sms_flow_posts_template_and_variables():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"type": "success", "request_id": "flow-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _provider(client).send_sms(
            to="9876543210",
            variables={"var1": "Asha"},
        )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v5/flow"
    assert request.headers["authkey"] == "test-auth-key"
    assert request.read() == (
        b'{"template_id":"sms-approved-template","recipients":'
        b'[{"mobiles":"+919876543210","var1":"Asha"}]}'
    )
    assert result == {"type": "success", "request_id": "flow-1"}


@pytest.mark.asyncio
async def test_send_message_uses_sms_template_variable_without_logging():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json={"type": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _provider(client).send_message(to="9876543210", body="One-time code: 234567")

    assert b"One-time code: 234567" in captured["body"]


@pytest.mark.asyncio
async def test_adapter_does_not_log_auth_key_or_otp(caplog):
    caplog.set_level("DEBUG")
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "success", "request_id": "safe-id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        await provider.send_otp(to="9876543210")
        await provider.verify_otp(to="9876543210", otp="728194")

    assert "test-auth-key" not in caplog.text
    assert "728194" not in caplog.text
    assert "919876543210" not in caplog.text


@pytest.mark.asyncio
async def test_http_failure_does_not_expose_provider_body_or_auth_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="test-auth-key and OTP 123456")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MSG91ProviderError) as error:
            await _provider(client).send_sms(to="9876543210")

    assert "test-auth-key" not in str(error.value)
    assert "123456" not in str(error.value)


@pytest.mark.asyncio
async def test_provider_error_response_is_safe():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "error", "message": "test-auth-key"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MSG91ProviderError) as error:
            await _provider(client).send_otp(to="9876543210")

    assert "test-auth-key" not in str(error.value)


@pytest.mark.asyncio
async def test_timeout_is_reported_without_exposing_transport_details():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test-auth-key OTP=123456")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MSG91TimeoutError) as error:
            await _provider(client).send_otp(to="9876543210")

    assert "test-auth-key" not in str(error.value)
    assert "123456" not in str(error.value)


@pytest.mark.asyncio
async def test_twilio_adapter_remains_registered():
    adapter = get_provider_adapter("twilio")
    assert adapter.provider_name == "twilio"
    result = await adapter.send_message(to="+919876543210", body="test")
    assert result["provider"] == "twilio"
