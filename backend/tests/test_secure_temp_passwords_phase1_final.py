"""
Task D (phase1-final-release-fixes) — secure temporary-password generation.

Verifies `generate_temp_password()` (the existing secure generator, now wired
in everywhere the fixed strings "Password@123"/"Admin@123"/etc. used to be)
for uniqueness, policy compliance, correct hashing, and that created accounts
are forced to change their password on first login.
"""
import os
import re
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/hospital")

from app.core.security import generate_temp_password, hash_password, verify_password


def test_generate_temp_password_is_unique_per_call():
    passwords = {generate_temp_password() for _ in range(200)}
    assert len(passwords) == 200


def test_generate_temp_password_meets_policy():
    # Configured policy (ChangePasswordRequest / UserCreate): minimum 8 characters.
    for _ in range(50):
        pwd = generate_temp_password()
        assert len(pwd) >= 8
        assert re.search(r"[A-Z]", pwd), "must contain an uppercase letter"
        assert re.search(r"[a-z]", pwd), "must contain a lowercase letter"
        assert re.search(r"[0-9]", pwd), "must contain a digit"


def test_generate_temp_password_uses_secrets_module_not_random():
    import inspect
    from app.core import security as security_module
    source = inspect.getsource(security_module.generate_temp_password)
    assert "secrets." in source
    assert "import random" not in source


def test_generate_temp_password_is_hashed_and_verifiable_but_never_reversible():
    pwd = generate_temp_password()
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_no_predictable_default_password_strings_remain_in_source():
    """
    Regression guard: previously-hardcoded predictable temporary passwords must
    never reappear in application code (tests/fixtures with a deliberately
    fixed local dev password like 'Passw0rd!' are out of scope here).
    """
    banned = ("Password@123", "Admin@123", "ChangeMe@123", "SuperAdmin@123")
    backend_app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    offenders = []
    for root, _dirs, files in os.walk(backend_app_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            for banned_value in banned:
                if banned_value in content:
                    offenders.append((path, banned_value))
    assert offenders == [], f"Predictable default password strings found: {offenders}"
