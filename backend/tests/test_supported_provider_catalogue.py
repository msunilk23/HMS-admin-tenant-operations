import pytest

from app.integrations.providers import PROVIDER_CONFIGS, public_provider_catalogue, validate_provider_configuration


def valid_razorpay_configuration():
    return {
        "provider_code": "razorpay",
        "capability": "payment",
        "environment": "TEST",
        "public_configuration": {"key_id": "rzp_test_identifier"},
        "secrets": {"key_secret": "not-returned", "webhook_secret": "not-returned"},
    }


def test_catalogue_contains_only_enabled_registered_providers_and_no_secret_values():
    catalogue = public_provider_catalogue()
    assert [(item["capability"], item["provider_code"], item["display_name"]) for item in catalogue] == [
        ("communication", "twilio", "Twilio"),
        ("communication", "msg91", "MSG91"),
        ("payment", "razorpay", "Razorpay"),
        ("document_storage", "cloudinary", "Cloudinary"),
    ]
    assert all(field["write_only"] and "value" not in field for item in catalogue for field in item["secret_fields"])
    by_provider = {item["provider_code"]: item for item in catalogue}
    assert by_provider["twilio"]["supported_channels"] == ["SMS", "WHATSAPP"]
    assert by_provider["msg91"]["supported_channels"] == ["SMS"]
    assert by_provider["msg91"]["secret_fields"][0]["field_code"] == "auth_key"
    assert all(field["field_code"] != "auth_key" for field in by_provider["msg91"]["public_fields"])


@pytest.mark.parametrize("change, message", [
    ({"provider_code": "custom_vendor"}, "Unsupported provider"),
    ({"capability": "communication"}, "capability"),
    ({"environment": "SANDBOX"}, "environment"),
    ({"public_configuration": {}}, "key_id"),
    ({"public_configuration": {"key_id": "id", "key_secret": "leak"}}, "Unknown or secret"),
    ({"public_configuration": {"key_id": "id", "unexpected": "value"}}, "Unknown or secret"),
])
def test_provider_contract_rejects_invalid_tenant_selection(change, message):
    payload = valid_razorpay_configuration()
    payload.update(change)
    with pytest.raises(ValueError, match=message):
        validate_provider_configuration(**payload)


def test_disabled_provider_cannot_be_selected(monkeypatch):
    config = PROVIDER_CONFIGS["razorpay"]
    monkeypatch.setitem(PROVIDER_CONFIGS, "razorpay", type(config)(**{**config.__dict__, "enabled_for_tenant_selection": False}))
    with pytest.raises(ValueError, match="not enabled"):
        validate_provider_configuration(**valid_razorpay_configuration())


def test_valid_msg91_configuration_requires_templates_and_keeps_auth_key_secret():
    config = validate_provider_configuration(
        provider_code="msg91",
        capability="communication",
        environment="TEST",
        public_configuration={"otp_template_id": "otp-template", "sms_template_id": "sms-template"},
        secrets={"auth_key": "secret-auth-key"},
    )
    assert config.supported_channels == ("SMS",)


def test_msg91_configuration_rejects_missing_template_or_secret():
    with pytest.raises(ValueError, match="otp_template_id"):
        validate_provider_configuration(
            provider_code="msg91",
            capability="communication",
            environment="TEST",
            public_configuration={"sms_template_id": "sms-template"},
            secrets={"auth_key": "secret-auth-key"},
        )
    with pytest.raises(ValueError, match="auth_key"):
        validate_provider_configuration(
            provider_code="msg91",
            capability="communication",
            environment="TEST",
            public_configuration={"otp_template_id": "otp-template", "sms_template_id": "sms-template"},
            secrets={},
        )