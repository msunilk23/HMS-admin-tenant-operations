"""Fail-closed provider secret storage backed by AES-256-GCM.

The implementation is intentionally provider-neutral and supports replacing the
encrypted-database backend with a Vault-backed implementation without changing
callers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretStore(Protocol):
    async def store_secret(
        self,
        *,
        tenant_id: str | uuid.UUID,
        provider: str,
        capability: str,
        environment: str,
        credential_version: int,
        secret: str,
        associated_data: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, str]: ...

    async def get_secret(
        self,
        *,
        tenant_id: str | uuid.UUID,
        provider: str,
        capability: str,
        environment: str,
        credential_version: int,
        associated_data: dict[str, Any] | None = None,
    ) -> str: ...

    async def rotate_secret(
        self,
        *,
        tenant_id: str | uuid.UUID,
        provider: str,
        capability: str,
        environment: str,
        current_version: int,
        new_secret: str,
        associated_data: dict[str, Any] | None = None,
    ) -> int: ...

    def invalidate_cache(self, *, tenant_id: str | uuid.UUID | None = None, provider: str | None = None, environment: str | None = None) -> None: ...


class EncryptedDatabaseSecretStore:
    """Encrypt provider secrets with a mounted master key and bind them to tenant."""

    ALGORITHM = "AES-256-GCM"
    KEY_VERSION = "k1"
    _cache: dict[tuple[str, str, str, str, int], tuple[str, datetime]] = {}
    _cache_max_entries = 256

    def __init__(self, master_key: str | None = None, *, key_path: str | None = None, test_mode: bool = False):
        self._key = self._derive_key(master_key=master_key, key_path=key_path, test_mode=test_mode)
        self._aes = AESGCM(self._key)

    @staticmethod
    def _derive_key(*, master_key: str | None, key_path: str | None, test_mode: bool) -> bytes:
        if master_key is not None:
            raw = master_key.strip().encode("utf-8")
            if len(raw) < 32:
                raise ValueError("integration master key must be at least 32 bytes")
            return hashlib.sha256(raw).digest()
        if key_path is not None:
            try:
                with open(key_path, "rb") as handle:
                    value = handle.read().strip()
            except FileNotFoundError as exc:
                raise RuntimeError(f"Integration master key file missing: {key_path}") from exc
            if not value:
                raise RuntimeError(f"Integration master key file is empty: {key_path}")
            if len(value) < 32:
                raise ValueError(f"Integration master key file is too short: {key_path}")
            return hashlib.sha256(value).digest()
        if test_mode:
            return hashlib.sha256(b"ephemeral-test-secret-store-key").digest()
        raise RuntimeError("Integration master key is not configured; startup fails closed")

    @staticmethod
    def _aad(*, tenant_id: str | uuid.UUID, provider: str, capability: str, environment: str, credential_version: int, associated_data: dict[str, Any] | None = None) -> bytes:
        payload: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "provider": str(provider),
            "capability": str(capability),
            "environment": str(environment),
            "credential_version": int(credential_version),
        }
        if associated_data:
            payload.update({str(key): str(value) for key, value in associated_data.items()})
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).digest()

    def _encrypt(self, secret: str, *, tenant_id: str | uuid.UUID, provider: str, capability: str, environment: str, credential_version: int, associated_data: dict[str, Any] | None = None) -> tuple[str, str]:
        nonce = os.urandom(12)
        aad = self._aad(
            tenant_id=tenant_id,
            provider=provider,
            capability=capability,
            environment=environment,
            credential_version=credential_version,
            associated_data=associated_data,
        )
        ciphertext = self._aes.encrypt(nonce, secret.encode("utf-8"), aad)
        return base64.b64encode(ciphertext).decode("ascii"), base64.b64encode(nonce).decode("ascii")

    def _decrypt(self, *, ciphertext_b64: str, nonce_b64: str, tenant_id: str | uuid.UUID, provider: str, capability: str, environment: str, credential_version: int, associated_data: dict[str, Any] | None = None) -> str:
        aad = self._aad(
            tenant_id=tenant_id,
            provider=provider,
            capability=capability,
            environment=environment,
            credential_version=credential_version,
            associated_data=associated_data,
        )
        try:
            plaintext = self._aes.decrypt(
                base64.b64decode(nonce_b64),
                base64.b64decode(ciphertext_b64),
                aad,
            )
            return plaintext.decode("utf-8")
        except Exception as exc:  # pragma: no cover - exercised by encryption tests
            raise ValueError("secret decryption failed; key, tenant, provider or data binding mismatch") from exc

    def invalidate_cache(self, *, tenant_id: str | uuid.UUID | None = None, provider: str | None = None, environment: str | None = None) -> None:
        if tenant_id is None and provider is None and environment is None:
            self._cache.clear()
            return
        for key in list(self._cache.keys()):
            tenant_key, provider_key, _, env_key, _ = key
            if tenant_id is not None and tenant_key != str(tenant_id):
                continue
            if provider is not None and provider_key != provider:
                continue
            if environment is not None and env_key != environment:
                continue
            del self._cache[key]

    async def store_secret(
        self,
        *,
        tenant_id: str | uuid.UUID,
        provider: str,
        capability: str,
        environment: str,
        credential_version: int,
        secret: str,
        associated_data: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, str]:
        ciphertext, nonce = self._encrypt(
            secret,
            tenant_id=tenant_id,
            provider=provider,
            capability=capability,
            environment=environment,
            credential_version=credential_version,
            associated_data=associated_data,
        )
        key = (str(tenant_id), provider, capability, environment, credential_version)
        self._cache[key] = (secret, datetime.now(timezone.utc) + timedelta(minutes=5))
        if len(self._cache) > self._cache_max_entries:
            oldest = sorted(self._cache.items(), key=lambda item: item[1][1])[: len(self._cache) - self._cache_max_entries]
            for old_key, _ in oldest:
                del self._cache[old_key]
        return ciphertext, nonce, self.ALGORITHM, self.KEY_VERSION

    async def get_secret(
        self,
        *,
        tenant_id: str | uuid.UUID,
        provider: str,
        capability: str,
        environment: str,
        credential_version: int,
        associated_data: dict[str, Any] | None = None,
    ) -> str:
        key = (str(tenant_id), provider, capability, environment, credential_version)
        cached = self._cache.get(key)
        if cached and cached[1] > datetime.now(timezone.utc):
            return cached[0]
        raise KeyError("Secret not available for tenant/provider/version")

    async def rotate_secret(
        self,
        *,
        tenant_id: str | uuid.UUID,
        provider: str,
        capability: str,
        environment: str,
        current_version: int,
        new_secret: str,
        associated_data: dict[str, Any] | None = None,
    ) -> int:
        next_version = (current_version or 0) + 1
        self.invalidate_cache(tenant_id=tenant_id, provider=provider, environment=environment)
        self._cache[(str(tenant_id), provider, capability, environment, next_version)] = (new_secret, datetime.now(timezone.utc) + timedelta(minutes=5))
        return next_version


_secret_store_singleton: SecretStore | None = None


def get_secret_store(*, master_key: str | None = None, key_path: str | None = None, test_mode: bool = False) -> SecretStore:
    global _secret_store_singleton
    if _secret_store_singleton is None:
        _secret_store_singleton = EncryptedDatabaseSecretStore(master_key=master_key, key_path=key_path, test_mode=test_mode)
    return _secret_store_singleton


def initialize_secret_store() -> SecretStore:
    from app.core.config import settings

    key_path = getattr(settings, "INTEGRATION_MASTER_KEY_FILE", None) or None
    master_key = getattr(settings, "INTEGRATION_MASTER_KEY", None) or None
    test_mode = str(getattr(settings, "ENVIRONMENT", "production")).lower() in {"development", "test", "e2e"}

    if master_key is not None:
        return EncryptedDatabaseSecretStore(master_key=master_key)
    if key_path is not None:
        return EncryptedDatabaseSecretStore(key_path=key_path)
    if test_mode:
        return EncryptedDatabaseSecretStore(test_mode=True)
    raise RuntimeError("Integration master key is not configured; startup fails closed")
    return store


secret_store = initialize_secret_store()
