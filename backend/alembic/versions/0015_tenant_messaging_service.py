"""Add messaging_service column to public.tenants

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.drop_column("tenants", "messaging_service", schema="public")
