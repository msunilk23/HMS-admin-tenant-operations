"""Public schema models — shared across all tenants."""
import secrets
import uuid
from datetime import datetime

from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    __table_args__ = {"schema": "public"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    schema_name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    hospital_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    secondary_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    plan: Mapped[str] = mapped_column(String(50), default="enterprise", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    # Revocable credential for unauthenticated public queue-display boards
    # (see /ws/{tenant_schema}/queue:update and app.api.v1.tenants). It grants
    # read-only WebSocket access to the PII-free public queue channel only —
    # never API access.
    display_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_valid_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")

    def __repr__(self) -> str:
        return f"<Tenant {self.hospital_name} schema={self.schema_name}>"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="SET NULL"), nullable=True
    )
    tenant_name: Mapped[Optional[str]] = mapped_column(String(63), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # see RBAC roles in PLAN.md
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_valid_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Optional["Tenant"]] = relationship("Tenant", back_populates="users")

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role}>"
