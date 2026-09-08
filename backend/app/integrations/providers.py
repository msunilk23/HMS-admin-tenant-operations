"""Provider adapters and capability interfaces for tenant-scoped integrations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class CommunicationProvider(Protocol):
    provider_name: str

    async def send_message(self, *, to: str, body: str, **kwargs: Any) -> dict[str, Any]: ...


class PaymentProvider(Protocol):
    provider_name: str

    async def create_order(self, *, amount: int, currency: str, metadata: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]: ...

    async def verify_webhook(self, *, payload: bytes, signature: str, secret: str, **kwargs: Any) -> bool: ...


class DocumentStorageProvider(Protocol):
    provider_name: str

    async def upload_private(self, *, tenant_id: str, prefix: str, filename: str, content: bytes, **kwargs: Any) -> dict[str, Any]: ...

    async def signed_url(self, *, tenant_id: str, resource_path: str, ttl_seconds: int = 300, **kwargs: Any) -> str: ...


@dataclass(frozen=True)
class ProviderField:
    field_code: str
    label: str
    required: bool
    masked: bool = True


@dataclass(frozen=True)
class ProviderConfig:
    provider_code: str
    display_name: str
    capability: str
    adapter_key: str
    supported_environments: tuple[str, ...]
    public_fields: tuple[ProviderField, ...]
    secret_fields: tuple[ProviderField, ...]
    supports_connection_test: bool
    supports_webhooks: bool
    credential_schema_version: int
    enabled_for_tenant_selection: bool = True

    @property
    def key(self) -> str:
        return self.provider_code

    @property
    def label(self) -> str:
        return self.display_name


def _field(field_code: str, label: str, *, required: bool, masked: bool = True) -> ProviderField:
    return ProviderField(field_code=field_code, label=label, required=required, masked=masked)


class TwilioProvider:
    provider_name = "twilio"

    async def send_message(self, *, to: str, body: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "queued", "to": to, "body": body, "provider": self.provider_name}


class RazorpayProvider:
    provider_name = "razorpay"

    async def create_order(self, *, amount: int, currency: str, metadata: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        return {"id": "order_test_123", "amount": amount, "currency": currency, "metadata": metadata or {}, "provider": self.provider_name}

    async def verify_webhook(self, *, payload: bytes, signature: str, secret: str, **kwargs: Any) -> bool:
        return bool(payload and signature and secret)


class CloudinaryProvider:
    provider_name = "cloudinary"

    async def upload_private(self, *, tenant_id: str, prefix: str, filename: str, content: bytes, **kwargs: Any) -> dict[str, Any]:
        return {"provider": self.provider_name, "tenant_id": tenant_id, "prefix": prefix, "filename": filename, "bytes": len(content), "private": True}

    async def signed_url(self, *, tenant_id: str, resource_path: str, ttl_seconds: int = 300, **kwargs: Any) -> str:
        return f"https://example.invalid/{tenant_id}/{resource_path}?expires={ttl_seconds}"


PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
    "twilio": ProviderConfig("twilio", "Twilio", "communication", "twilio", ("TEST", "LIVE"), (_field("account_sid", "Account SID", required=True), _field("api_key_sid", "API Key SID", required=True), _field("sender_phone_number", "Sender Phone Number", required=False), _field("messaging_service_sid", "Messaging Service SID", required=False), _field("region", "Region", required=False)), (_field("api_key_secret", "API Key Secret", required=True), _field("auth_token", "Auth Token", required=False)), True, True, 1),
    "razorpay": ProviderConfig("razorpay", "Razorpay", "payment", "razorpay", ("TEST", "LIVE"), (_field("key_id", "Key ID", required=True),), (_field("key_secret", "Key Secret", required=True), _field("webhook_secret", "Webhook Secret", required=True)), True, True, 1),
    "cloudinary": ProviderConfig("cloudinary", "Cloudinary", "document_storage", "cloudinary", ("TEST", "LIVE"), (_field("cloud_name", "Cloud Name", required=True), _field("api_key", "API Key", required=True), _field("tenant_folder", "Tenant Folder", required=True)), (_field("api_secret", "API Secret", required=True),), True, False, 1),
}


def get_provider_config(provider_code: str, *, selectable: bool = False) -> ProviderConfig:
    config = PROVIDER_CONFIGS.get(provider_code.lower())
    if config is None:
        raise ValueError("Unsupported provider")
    if selectable and not config.enabled_for_tenant_selection:
        raise ValueError("Provider is not enabled for tenant selection")
    return config


def validate_provider_configuration(*, provider_code: str, capability: str, environment: str, public_configuration: dict[str, str], secrets: dict[str, str]) -> ProviderConfig:
    config = get_provider_config(provider_code, selectable=True)
    if capability != config.capability:
        raise ValueError("Selected capability does not match provider")
    if environment.upper() not in config.supported_environments:
        raise ValueError("Selected environment is not supported by provider")
    public_codes = {field.field_code for field in config.public_fields}
    secret_codes = {field.field_code for field in config.secret_fields}
    if set(public_configuration) - public_codes:
        raise ValueError("Unknown or secret public configuration field")
    if set(secrets) - secret_codes:
        raise ValueError("Unknown secret configuration field")
    for field in config.public_fields:
        if field.required and not str(public_configuration.get(field.field_code, "")).strip():
            raise ValueError(f"Missing required public configuration field: {field.field_code}")
    for field in config.secret_fields:
        if field.required and not str(secrets.get(field.field_code, "")).strip():
            raise ValueError(f"Missing required secret configuration field: {field.field_code}")
    return config


def public_provider_catalogue() -> list[dict[str, Any]]:
    return [{
        "provider_code": config.provider_code,
        "display_name": config.display_name,
        "capability": config.capability,
        "supported_environments": list(config.supported_environments),
        "public_fields": [{"field_code": field.field_code, "label": field.label, "required": field.required, "masked": field.masked} for field in config.public_fields],
        "secret_fields": [{"field_code": field.field_code, "label": field.label, "required": field.required, "write_only": True, "configured": False} for field in config.secret_fields],
        "supports_connection_test": config.supports_connection_test,
        "supports_webhooks": config.supports_webhooks,
    } for config in PROVIDER_CONFIGS.values() if config.enabled_for_tenant_selection]


def get_provider_adapter(provider: str) -> Any:
    normalized = get_provider_config(provider).adapter_key
    if normalized == "twilio":
        return TwilioProvider()
    if normalized == "razorpay":
        return RazorpayProvider()
    if normalized == "cloudinary":
        return CloudinaryProvider()
    raise ValueError(f"Unsupported provider: {provider}")
