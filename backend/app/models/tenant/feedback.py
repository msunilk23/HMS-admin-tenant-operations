from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, unique=True, index=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer)  # 1–5
    comments: Mapped[Optional[str]] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="staff")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    link_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
