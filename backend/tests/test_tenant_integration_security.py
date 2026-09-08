import pytest

from app.core.config import settings
from app.core.secret_store import EncryptedDatabaseSecretStore, initialize_secret_store


@pytest.mark.parametrize(
    "value",
    [
        "12345678901234567890123456789012",
        "abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_initialize_secret_store_accepts_raw_master_key_in_production(monkeypatch, value):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "INTEGRATION_MASTER_KEY_FILE", None, raising=False)
    monkeypatch.setattr(settings, "INTEGRATION_MASTER_KEY", value, raising=False)

    store = initialize_secret_store()

    assert isinstance(store, EncryptedDatabaseSecretStore)
    assert len(store._key) == 32


def test_initialize_secret_store_requires_explicit_key_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "INTEGRATION_MASTER_KEY_FILE", None, raising=False)
    monkeypatch.setattr(settings, "INTEGRATION_MASTER_KEY", None, raising=False)

    with pytest.raises(RuntimeError, match="Integration master key"):
        initialize_secret_store()


def test_encrypted_secret_store_rejects_short_raw_key():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        EncryptedDatabaseSecretStore(master_key="short")
