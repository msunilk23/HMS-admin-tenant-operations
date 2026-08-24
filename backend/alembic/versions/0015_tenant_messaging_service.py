"""Add messaging_service column to public.tenants

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Only applies to the public schema — without this guard, replaying this
    # revision while migrating a TENANT schema's own version-history (every
    # tenant schema tracks the same shared revision chain independently) would
    # try to add this column to public.tenants a second time and crash the
    # very next tenant onboarded after this migration existed (Task G finding).
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    col_exists = bind.execute(text(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.columns"
        "  WHERE table_schema = 'public' AND table_name = 'tenants'"
        "  AND column_name = 'messaging_service'"
        ")"
    )).scalar()
    if col_exists:
        return

    op.add_column(
        "tenants",
        sa.Column(
            "messaging_service",
            sa.String(30),
            nullable=False,
            server_default="twilio",
        ),
        schema="public",
    )


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return
    op.drop_column("tenants", "messaging_service", schema="public")
