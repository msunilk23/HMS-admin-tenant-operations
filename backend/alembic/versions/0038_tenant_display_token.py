"""Revocable per-tenant display-board credential (replaces static token=display)."""
import secrets

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    op.add_column("tenants", sa.Column("display_token", sa.String(64), nullable=True), schema="public")

    rows = bind.execute(text("SELECT id FROM public.tenants")).fetchall()
    for (tenant_id,) in rows:
        bind.execute(
            text("UPDATE public.tenants SET display_token = :tok WHERE id = :id"),
            {"tok": secrets.token_urlsafe(24), "id": tenant_id},
        )

    op.alter_column("tenants", "display_token", nullable=False, schema="public")
    op.create_unique_constraint("uq_tenants_display_token", "tenants", ["display_token"], schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    op.drop_constraint("uq_tenants_display_token", "tenants", schema="public", type_="unique")
    op.drop_column("tenants", "display_token", schema="public")
