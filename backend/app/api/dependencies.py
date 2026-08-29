from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.engine import get_session


async def get_tenant_id_from_token(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> uuid.UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant context is missing")
    try:
        return uuid.UUID(str(tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant context is invalid") from exc


async def get_facility_id(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> uuid.UUID:
    facility_id = current_user.get("facility_id")
    if not facility_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Facility context is missing")
    try:
        return uuid.UUID(str(facility_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Facility context is invalid") from exc


__all__ = [
    "get_current_user",
    "get_session",
    "get_tenant_id_from_token",
    "get_facility_id",
]
