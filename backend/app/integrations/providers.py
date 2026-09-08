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


@dataclass
class ProviderConfig:
    key: str
    label: str
    fields: list[str]
    capability: str
    status: str = "DISABLED"
    environment: str = "TEST"


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
    "twilio": ProviderConfig("twilio", "Twilio", ["account_sid", "api_key_sid", "api_key_secret", "sender_phone_number"], "communication"),
    "razorpay": ProviderConfig("razorpay", "Razorpay", ["key_id", "key_secret", "webhook_secret"], "payment"),
    "cloudinary": ProviderConfig("cloudinary", "Cloudinary", ["cloud_name", "api_key", "api_secret", "tenant_folder"], "document_storage"),
}


def get_provider_adapter(provider: str) -> Any:
    normalized = provider.lower()
    if normalized == "twilio":
        return TwilioProvider()
    if normalized == "razorpay":
        return RazorpayProvider()
    if normalized == "cloudinary":
        return CloudinaryProvider()
    raise ValueError(f"Unsupported provider: {provider}")
