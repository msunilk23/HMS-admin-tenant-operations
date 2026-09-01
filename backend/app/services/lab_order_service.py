"""Shared server-authoritative snapshot logic for Lab Test Master orders.

Both the direct `/lab` order-creation endpoint and the doctor's prescription
lab-tests upsert must snapshot the SAME server-derived fields at order time —
client-supplied price or clinical metadata is never authoritative.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.lab_test_master import LabTestMaster


async def snapshot_lab_test(session: AsyncSession, test_id: uuid.UUID, notes: str | None = None) -> dict:
    """Validate an active controlled test and return its server-derived snapshot dict."""
    test_master = await session.get(LabTestMaster, test_id)
    if not test_master:
        raise HTTPException(status_code=404, detail=f"Lab test not found: {test_id}")
    if not test_master.is_active:
        raise HTTPException(status_code=400, detail=f"Lab test is inactive: {test_master.code}")
    return {
        "test_id": str(test_id),
        "test_code": test_master.code,
        "test_name": test_master.name,
        "category": test_master.category,
        "sample_type": test_master.sample_type,
        "unit": test_master.unit,
        "reference_range": test_master.reference_range,
        "price": float(test_master.price),
        "notes": notes,
    }


def reject_duplicate_test_ids(test_ids: list[uuid.UUID]) -> None:
    seen = set()
    for test_id in test_ids:
        key = str(test_id)
        if key in seen:
            raise HTTPException(status_code=400, detail="Duplicate lab test selected within one order")
        seen.add(key)
