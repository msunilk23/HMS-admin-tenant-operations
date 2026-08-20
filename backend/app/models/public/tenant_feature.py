"""TenantFeature model — per-tenant feature entitlements (public schema)."""
import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TenantFeature(Base, TimestampMixin):
    """
    One row per (tenant, feature) pair.
    enabled=True  → the tenant can use this feature.
    enabled=False → the feature is blocked for this tenant.

    Rows are seeded for all tenants on migration. Absence of a row
    is treated the same as enabled=False by require_feature().
    """

    __tablename__ = "tenant_features"
    __table_args__ = (
        UniqueConstraint("tenant_id", "feature", name="uq_tenant_features_tenant_feature"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<TenantFeature tenant={self.tenant_id} feature={self.feature} enabled={self.enabled}>"
