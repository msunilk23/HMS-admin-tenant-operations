from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select, text

from app.db.engine import AsyncSessionLocal, tenant_schema_var
from app.models.public.user import Tenant
from app.models.tenant.patient_route import PatientRoute
from app.services.patient_routing import expire_steps

logger = logging.getLogger(__name__)
EXPIRY_INTERVAL_SECONDS = 30


async def expire_all_tenant_routes() -> int:
    total = 0
    async with AsyncSessionLocal() as public_session:
        await public_session.execute(text("SET search_path TO public"))
        tenants = (await public_session.execute(select(Tenant.id, Tenant.schema_name).where(Tenant.is_active.is_(True)))).all()
    for tenant_id, schema in tenants:
        token = tenant_schema_var.set(schema)
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text(f'SET search_path TO "{schema}", public'))
                facilities = (await session.execute(select(PatientRoute.facility_id).where(PatientRoute.facility_id.is_not(None)).distinct())).scalars().all()
                for facility_id in facilities:
                    system_user = {"sub": None, "role": "system", "tenant_id": str(tenant_id), "facility_id": str(facility_id), "tenant_schema": schema}
                    total += await expire_steps(session, system_user, facility_id=facility_id)
                await session.commit()
        except Exception:
            logger.exception("PF-1 route expiry failed for tenant schema=%s", schema)
        finally:
            tenant_schema_var.reset(token)
    return total


async def routing_expiry_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await expire_all_tenant_routes()
        except Exception:
            logger.exception("PF-1 route expiry worker iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=EXPIRY_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue