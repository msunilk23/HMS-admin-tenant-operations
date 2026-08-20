"""Drop messaging_service column from public.tenants

Revision ID: 0016
Revises: 0015
Create Date: 2025-01-01 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return
    op.drop_column("tenants", "messaging_service", schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema != "public":
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
