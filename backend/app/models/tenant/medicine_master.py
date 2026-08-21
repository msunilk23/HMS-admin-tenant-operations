import uuid
from typing import Optional
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class MedicineMaster(Base, TimestampMixin):
    __tablename__ = "medicine_master"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    generic_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    brand_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    strength: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dosage_form: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
