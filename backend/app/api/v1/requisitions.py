"""
Internal Indents API — raise and track supply requests across departments.

All tenant users can raise indents for themselves.
hospital_admin can view all indents and update status / amount.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.db.engine import get_session
from app.models.tenant.requisition import Requisition
from app.schemas.requisition import RequisitionAmountUpdate, RequisitionCreate, RequisitionItemsUpdate, RequisitionRead, RequisitionStatusUpdate
from app.websocket.manager import ws_manager

router = APIRouter()

# Roles that can raise and view their own requisitions
_ANY_TENANT_ROLE = ("hospital_admin", "doctor", "nurse", "receptionist", "pharmacist", "lab_technician", "store_manager")
# Roles that can view ALL requisitions and update status / amount / items
_ADMIN_ROLES = ("hospital_admin", "store_manager")

VALID_STATUSES = {"pending", "approved", "rejected", "fulfilled"}
VALID_TO_LOCATIONS = {"Pharmacy", "General Store"}


async def _next_seq(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Requisition))
    return (result.scalar() or 0) + 1


async def _generate_req_number(session: AsyncSession) -> str:
    result = await session.execute(select(func.max(Requisition.seq)).select_from(Requisition))
    max_seq = result.scalar() or 0
    return f"IN-{max_seq + 1:04d}"


@router.get("", response_model=List[RequisitionRead])
async def list_requisitions(
    mine: bool = Query(False, description="If true, return only the caller's requisitions"),
    status_filter: Optional[str] = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ANY_TENANT_ROLE)),
):
    """
    List requisitions.
    - hospital_admin with mine=false → all requisitions (default)
    - Any user with mine=true → only their own
    - Non-admin always sees only their own regardless of the mine flag
    """
    stmt = select(Requisition).order_by(Requisition.seq.asc())

    is_admin = current_user.get("role") in _ADMIN_ROLES
    if not is_admin or mine:
        stmt = stmt.where(Requisition.requested_by_id == uuid.UUID(current_user["sub"]))

    if status_filter:
        stmt = stmt.where(Requisition.status == status_filter)

    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.post("", response_model=RequisitionRead, status_code=status.HTTP_201_CREATED)
async def create_requisition(
    payload: RequisitionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ANY_TENANT_ROLE)),
):
    """Raise a new internal requisition."""
    if payload.to_location not in VALID_TO_LOCATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"to_location must be one of: {sorted(VALID_TO_LOCATIONS)}",
        )
    if payload.need_by_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="need_by_date cannot be in the past.",
        )

    seq = await _next_seq(session)
    req_number = await _generate_req_number(session)

    req = Requisition(
        id=uuid.uuid4(),
        seq=seq,
        indent_number=req_number,
        requested_by_id=uuid.UUID(current_user["sub"]),
        requested_by_name=current_user.get("full_name", ""),
        from_location=payload.from_location,
        to_location=payload.to_location,
        request_date=date.today(),
        need_by_date=payload.need_by_date,
        items=payload.items,
        status="pending",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


@router.patch("/{req_id}/status", response_model=RequisitionRead)
async def update_requisition_status(
    req_id: uuid.UUID,
    payload: RequisitionStatusUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    """Update the status of a requisition (hospital_admin only)."""
    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {sorted(VALID_STATUSES)}",
        )
    req = await session.get(Requisition, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Indent not found")

    req.status = payload.status
    await session.commit()
    await session.refresh(req)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "indent:update", {
        "event": "indent_status_updated",
        "indent_id": str(req.id),
        "status": req.status,
    })
    return req


@router.patch("/{req_id}/amount", response_model=RequisitionRead)
async def update_requisition_amount(
    req_id: uuid.UUID,
    payload: RequisitionAmountUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    """Set / update the expenditure amount for an indent (hospital_admin only)."""
    req = await session.get(Requisition, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Indent not found")

    req.amount = payload.amount
    await session.commit()
    await session.refresh(req)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "indent:update", {
        "event": "indent_amount_updated",
        "indent_id": str(req.id),
    })
    return req


@router.patch("/{req_id}/items", response_model=RequisitionRead)
async def update_requisition_items(
    req_id: uuid.UUID,
    payload: RequisitionItemsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    """Update the items list for an indent (hospital_admin only)."""
    req = await session.get(Requisition, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Indent not found")

    req.items = payload.items.strip()
    await session.commit()
    await session.refresh(req)

    tenant = current_user.get("tenant_schema", "public")
    await ws_manager.broadcast(tenant, "indent:update", {
        "event": "indent_items_updated",
        "indent_id": str(req.id),
    })
    return req


@router.get("/stats")
async def indent_stats(
    period: str = Query("month", description="week | month | year"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(require_role(*_ADMIN_ROLES)),
):
    """Indent expenditure summary for the given period (hospital_admin only)."""
    today = date.today()
    if period == "week":
        since = today - timedelta(days=7)
    elif period == "year":
        since = today.replace(month=1, day=1)
    else:  # month (default)
        since = today.replace(day=1)

    stmt = select(Requisition).where(Requisition.request_date >= since)
    rows = (await session.execute(stmt)).scalars().all()

    total_count = len(rows)
    total_amount = sum((r.amount or 0) for r in rows)
    fulfilled = [r for r in rows if r.status == "fulfilled"]
    pending = [r for r in rows if r.status == "pending"]
    approved = [r for r in rows if r.status == "approved"]

    # Group expenditure by date for sparkline
    by_date: dict = {}
    for r in rows:
        if r.amount:
            key = r.request_date.isoformat()
            by_date[key] = float(by_date.get(key, 0)) + float(r.amount)

    return {
        "period": period,
        "since": since.isoformat(),
        "total_indents": total_count,
        "total_expenditure": float(total_amount),
        "fulfilled_count": len(fulfilled),
        "fulfilled_amount": float(sum((r.amount or 0) for r in fulfilled)),
        "pending_count": len(pending),
        "approved_count": len(approved),
        "by_date": [{"date": k, "amount": v} for k, v in sorted(by_date.items())],
    }
