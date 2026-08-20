from typing import Optional
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PharmacyQueue(Base):
    __tablename__ = "pharmacy_queue"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prescriptions.id"), nullable=False, index=True)
    uhid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # status: pending | called | dispensing | dispensed | partially_dispensed | out_of_stock | cancelled
    notes: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispensing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispensed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
