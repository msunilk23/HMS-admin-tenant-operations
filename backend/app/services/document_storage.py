"""Storage abstraction for immutable rendered documents (invoice/prescription PDFs).

Phase 1 ships only `LocalFileDocumentStorage` (uploads/ on local/container disk).
This is explicitly NOT production-durable: container filesystems are ephemeral
and not shared across replicas. Production deployments MUST swap this for a
durable, shared, versioned object store (e.g. S3/Azure Blob/GCS) implementing
the same `DocumentStorage` interface — no caller-side code should need to
change since callers only depend on this interface, never on file paths.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path


class DocumentStorage(ABC):
    """Content-addressed, write-once storage for rendered document bytes."""

    @abstractmethod
    def write(self, key: str, data: bytes) -> int:
        """Persist `data` under immutable `key`. Returns byte size.

        Never overwrites a key with *different* content. If the exact same
        key already holds byte-identical content (safe retry of a partially
        committed finalization), this is a no-op success. If the key exists
        with *different* content, raises `DocumentStorageConflict`.
        """

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Return the raw bytes stored under `key`. Raises FileNotFoundError if missing."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...


class DocumentStorageConflict(Exception):
    """Raised when a storage key already holds different content than requested."""


class DocumentStorageError(Exception):
    """Raised on unexpected storage I/O failure (disk full, permissions, etc.)."""


def _resolve_uploads_root() -> Path:
    container_path = Path("/app/uploads")
    if container_path.exists():
        return container_path
    return Path(__file__).resolve().parents[3] / "uploads"


class LocalFileDocumentStorage(DocumentStorage):
    """Local/container-disk implementation. See module docstring for Phase 1 caveat."""

    def __init__(self, subroot: str = "documents"):
        self._root = _resolve_uploads_root() / subroot

    def _path(self, key: str) -> Path:
        return self._root / key

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def write(self, key: str, data: bytes) -> int:
        path = self._path(key)
        if path.exists():
            existing = path.read_bytes()
            if existing == data:
                return len(existing)
            raise DocumentStorageConflict(f"Storage key already exists with different content: {key}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create — a second concurrent writer for a genuinely new
            # key (race) fails fast instead of silently overwriting.
            with open(path, "xb") as fh:
                fh.write(data)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != data:
                raise DocumentStorageConflict(f"Storage key already exists with different content: {key}")
        except OSError as exc:
            raise DocumentStorageError(str(exc)) from exc
        return len(data)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return path.read_bytes()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
