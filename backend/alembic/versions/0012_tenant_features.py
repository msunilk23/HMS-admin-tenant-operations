"""Add tenant_features table and plan column to tenants (SaaS feature entitlements).

Runs on public schema only. All existing tenants are seeded with every
feature enabled so zero existing functionality is affected.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Canonical list of all feature keys. Keep in sync with
# backend/app/core/features.py and tenant_super_admin.md.
ALL_FEATURES = [
    "opd_queue",
    "appointments",
    "vitals",
    "nurse_roster",
    "lab",
    "pharmacy",
    "billing",
    "razorpay",
    "whatsapp_sms",
    "cloudinary_reports",
]


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    # This migration only touches the public schema.
    if current_schema != "public":
        return

    # 1. Add plan column to tenants (default 'enterprise' for all existing rows)
    op.add_column(
        "tenants",
        sa.Column(
            "plan",
            sa.String(50),
            nullable=False,
            server_default="enterprise",
        ),
        schema="public",
    )

    # 2. Create tenant_features table
    op.create_table(
        "tenant_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "feature", name="uq_tenant_features_tenant_feature"),
        schema="public",
    )
    op.create_index(
        "ix_tenant_features_tenant_id",
        "tenant_features",
        ["tenant_id"],
        schema="public",
    )

    # 3. Seed all existing tenants with ALL features enabled.
    #    This is the backward-compatibility guarantee — no existing tenant loses access.
    bind.execute(
        text("""
            INSERT INTO public.tenant_features (id, tenant_id, feature, enabled)
            SELECT
                gen_random_uuid(),
                t.id,
                f.feature,
                true
            FROM public.tenants t
            CROSS JOIN (VALUES
                ('opd_queue'),
                ('appointments'),
                ('vitals'),
                ('nurse_roster'),
                ('lab'),
                ('pharmacy'),
                ('billing'),
                ('razorpay'),
                ('whatsapp_sms'),
                ('cloudinary_reports')
            ) AS f(feature)
            ON CONFLICT (tenant_id, feature) DO NOTHING
        """)
    )


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    op.drop_index("ix_tenant_features_tenant_id", table_name="tenant_features", schema="public")
    op.drop_table("tenant_features", schema="public")
    op.drop_column("tenants", "plan", schema="public")
