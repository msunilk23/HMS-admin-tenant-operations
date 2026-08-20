from typing import Optional
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    uhid: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob: Mapped[Optional[date]] = mapped_column(Date)
    age: Mapped[Optional[int]] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)  # male | female | other
    phone: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(Text)
    blood_group: Mapped[Optional[str]] = mapped_column(String(5))
    insurance_provider: Mapped[Optional[str]] = mapped_column(String(255))
    insurance_id: Mapped[Optional[str]] = mapped_column(String(100))
    aadhar_number: Mapped[Optional[str]] = mapped_column(String(12))
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(200))
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(15))
    emergency_contact_relation: Mapped[Optional[str]] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
