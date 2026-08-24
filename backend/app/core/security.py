from datetime import datetime, timedelta, timezone
import secrets
import string
import uuid
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_temp_password(length: int = 10) -> str:
    """Generate a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits
    # Guarantee at least one uppercase, one lowercase, one digit
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
    ] + [secrets.choice(alphabet) for _ in range(length - 3)]
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)


def create_access_token(subject: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": expire, "type": "access"}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
    """
    Create a refresh token. Refresh tokens must carry the same session/tenant
    identity claims as access tokens (role, tenant_id, tenant_schema,
    session_version, tenant_session_version) so that refresh rotation and
    invalidation can be enforced without a database round-trip on every field.
    Callers must supply these from the current database state — never from
    client-supplied input.
    """
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())  # Unique token ID — used for blocklist on logout
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": expire, "type": "refresh", "jti": jti}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise
