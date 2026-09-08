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
        ("payment", "razorpay", "Razorpay"),
        ("document_storage", "cloudinary", "Cloudinary"),
    ]
    assert all(field["write_only"] and "value" not in field for item in catalogue for field in item["secret_fields"])


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