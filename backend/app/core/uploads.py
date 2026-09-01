"""Shared resolution for the writable uploads directory.

Mounted at /uploads by app.main; used by any endpoint that needs to persist
a file to local disk (lab reports historically use Cloudinary instead — this
is for assets that don't need a CDN, e.g. tenant logos).
"""
import os
from pathlib import Path

import app as _app_package

_REPO_ROOT = Path(_app_package.__file__).resolve().parent.parent.parent


def get_uploads_dir() -> Path:
    uploads_dir = Path(os.getenv("UPLOADS_DIR", "/app/uploads"))
    if not uploads_dir.parent.exists() or not os.access(uploads_dir.parent, os.W_OK):
        uploads_dir = _REPO_ROOT / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir
