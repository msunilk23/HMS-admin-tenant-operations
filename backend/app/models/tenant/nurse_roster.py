from typing import Optional
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class NurseRoster(Base, TimestampMixin):
    __tablename__ = "nurse_roster"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)  # public.users.id
    roster_date: Mapped[date] = mapped_column("date", Date, nullable=False)
    shift: Mapped[str] = mapped_column(String(20), nullable=False)  # morning | afternoon | night
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), nullable=False, index=True)
    room: Mapped[Optional[str]] = mapped_column(String(50))
    assigned_doctor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("doctors.id"))
    is_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    substitute_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    substitution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
