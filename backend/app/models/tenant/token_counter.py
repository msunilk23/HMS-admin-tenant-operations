"""Per-tenant atomic daily token counter — backs concurrency-safe token allocation."""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TokenCounter(Base):
    __tablename__ = "token_counters"
    __table_args__ = (
        UniqueConstraint("scope_key", "counter_date", name="uq_token_counters_scope_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
    counter_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
