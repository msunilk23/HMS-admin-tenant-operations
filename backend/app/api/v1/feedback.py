"""Visit-linked patient feedback."""

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_role
from app.db.engine import get_session
from app.models.tenant.feedback import Feedback
from app.models.tenant.visit import Visit
from app.schemas.feedback import FeedbackCreate, FeedbackRead

router = APIRouter()
_STAFF_ROLES = ("receptionist", "nurse", "doctor", "hospital_admin", "super_admin")


@router.post("", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackCreate,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role(*_STAFF_ROLES)),
):
    if not await session.get(Visit, payload.visit_id):
        raise HTTPException(status_code=404, detail="Visit not found")
    existing = (await session.execute(
        select(Feedback).where(Feedback.visit_id == payload.visit_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Feedback already submitted for this visit")
    feedback = Feedback(
        id=uuid.uuid4(),
        visit_id=payload.visit_id,
        rating=payload.rating,
        comments=payload.comments,
        channel=payload.channel,
        submitted_at=datetime.now(timezone.utc),
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return feedback


@router.get("/visit/{visit_id}", response_model=FeedbackRead)
async def get_visit_feedback(
    visit_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("receptionist", "nurse", "doctor", "hospital_admin", "super_admin")),
):
    feedback = (await session.execute(
        select(Feedback).where(Feedback.visit_id == visit_id)
    )).scalar_one_or_none()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found for this visit")
    return feedback


@router.get("", response_model=List[FeedbackRead])
async def list_feedback(
    session: AsyncSession = Depends(get_session),
    _: dict = Depends(require_role("hospital_admin", "super_admin")),
):
    return (await session.execute(
        select(Feedback).order_by(Feedback.submitted_at.desc())
    )).scalars().all()
