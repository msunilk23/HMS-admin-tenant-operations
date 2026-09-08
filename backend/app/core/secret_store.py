"""Fail-closed provider secret storage backed by AES-256-GCM.

The implementation is intentionally provider-neutral and supports replacing the
encrypted-database backend with a Vault-backed implementation without changing
callers.
"""
from __future__ import annotations

import base64
import hashlib
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


class EncryptedDatabaseSecretStore:
    """Encrypt provider secrets with a mounted master key and bind them to tenant."""

    ALGORITHM = "AES-256-GCM"
    KEY_VERSION = "k1"
    _cache: dict[tuple[str, str, str, str, int], tuple[str, datetime]] = {}

    def __init__(self, master_key: str | None = None, *, key_path: str | None = None, test_mode: bool = False):
        self._key = self._derive_key(master_key=master_key, key_path=key_path, test_mode=test_mode)
        self._aes = AESGCM(self._key)

    @staticmethod
    def _derive_key(*, master_key: str | None, key_path: str | None, test_mode: bool) -> bytes:
        if master_key:
            raw = master_key.strip().encode("utf-8")
            if len(raw) < 32:
                raise ValueError("integration master key must be at least 32 bytes")
            return hashlib.sha256(raw).digest()
        if key_path:
            try:
                with open(key_path, "rb") as handle:
                    value = handle.read().strip()
            except FileNotFoundError as exc:
                raise RuntimeError(f"Integration master key file missing: {key_path}") from exc
            if not value:
                raise RuntimeError(f"Integration master key file is empty: {key_path}")
            return hashlib.sha256(value).digest()
        if test_mode:
            return hashlib.sha256(b"ephemeral-test-secret-store-key").digest()
        raise RuntimeError("Integration master key is not configured; startup fails closed")

    @staticmethod
    def _aad(*, tenant_id: str | uuid.UUID, provider: str, capability: str, environment: str, credential_version: int) -> bytes:
        text = f"{tenant_id}:{provider}:{capability}:{environment}:{credential_version}".encode("utf-8")
        return hashlib.sha256(text).digest()

    def _encrypt(self, secret: str, *, tenant_id: str | uuid.UUID, provider: str, capability: str, environment: str, credential_version: int) -> tuple[str, str]:
        nonce = os.urandom(12)
        aad = self._aad(
            tenant_id=tenant_id,
            provider=provider,
            capability=capability,
            environment=environment,
            credential_version=credential_version,
        )
        ciphertext = self._aes.encrypt(nonce, secret.encode("utf-8"), aad)
        return base64.b64encode(ciphertext).decode("ascii"), base64.b64encode(nonce).decode("ascii")

    def _decrypt(self, *, ciphertext_b64: str, nonce_b64: str, tenant_id: str | uuid.UUID, provider: str, capability: str, environment: str, credential_version: int) -> str:
        aad = self._aad(
            tenant_id=tenant_id,
            provider=provider,
            capability=capability,
            environment=environment,
            credential_version=credential_version,
        )
        return self._aes.decrypt(
            base64.b64decode(nonce_b64),
            base64.b64decode(ciphertext_b64),
            aad,
        ).decode("utf-8")

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
        )
        self._cache[(str(tenant_id), provider, capability, environment, credential_version)] = (secret, datetime.now(timezone.utc) + timedelta(minutes=5))
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
    test_mode = str(getattr(settings, "ENVIRONMENT", "production")).lower() in {"development", "test", "e2e"}
    if not key_path and not test_mode:
        raise RuntimeError("Production integration master key file is required")
    store = EncryptedDatabaseSecretStore(key_path=key_path, test_mode=test_mode)
    return store


secret_store = initialize_secret_store()
