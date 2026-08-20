"""Add amount column to indents table

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-14 00:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("indents", sa.Column("amount", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("indents", "amount")
