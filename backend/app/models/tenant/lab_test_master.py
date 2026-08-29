"""Lab Test Master — controlled catalog of lab tests with pricing and metadata."""
import uuid
from typing import Optional

from sqlalchemy import Boolean, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LabTestMaster(Base, TimestampMixin):
    """
    Lab Test Master catalog.
    
    Fields:
    - code: Unique test code (e.g., "CBC", "TSH", "GLUCOSE")
    - name: Display name for UI and reports
    - category: Department/category (e.g., "Hematology", "Biochemistry")
    - sample_type: Type of sample (e.g., "Blood", "Urine", "CSF")
    - price: Server-authoritative price in rupees (not submitted by frontend)
    - unit: Unit of measurement (e.g., "cells/µL", "mg/dL") - optional
    - reference_range: Basic reference range (e.g., "4.5-11.0") - optional, P2 advanced ranges
    - is_active: Can new orders use this test
    
    Indexes:
    - code (unique)
    - is_active (for filtering active tests)
    """
    __tablename__ = "lab_test_master"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    sample_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_range: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
