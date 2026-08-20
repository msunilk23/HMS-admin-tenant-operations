"""
Username generation utility.

Pattern: {first_initial}{last[:5]}{NN}
  e.g.  "Sai Krishna Reddy"  →  base="skredd"  →  "skredd03"
        "Anita"               →  base="anita"   →  "anita07"

Guarantees uniqueness by querying public.users and incrementing the suffix.
"""
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.public.user import User


def _base(full_name: str) -> str:
    """Derive the base slug from a full name (no digits, max 8 chars)."""
    parts = re.sub(r"[^a-zA-Z\s]", "", full_name).split()
    if not parts:
        return "user"
    if len(parts) == 1:
        return parts[0][:8].lower()
    # first initial + up to 5 chars of last word
    return (parts[0][0] + parts[-1][:5]).lower()


async def generate_username(full_name: str, session: AsyncSession) -> str:
    """
    Return a unique username for the given full_name.
    Tries base+00 through base+99, then appends a longer suffix.
    """
    base = _base(full_name)
    for n in range(100):
        candidate = f"{base}{n:02d}"
        exists = (
            await session.execute(
                select(User.id).where(User.username == candidate)
            )
        ).scalar_one_or_none()
        if not exists:
            return candidate
    # Extremely unlikely fallback: use 4-digit suffix
    import random
    for _ in range(1000):
        candidate = f"{base}{random.randint(1000, 9999)}"
        exists = (
            await session.execute(
                select(User.id).where(User.username == candidate)
            )
        ).scalar_one_or_none()
        if not exists:
            return candidate
    raise RuntimeError(f"Could not generate a unique username for base '{base}'")
