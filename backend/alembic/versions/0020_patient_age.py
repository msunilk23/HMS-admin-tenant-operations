"""Add age column to patients table

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-14 00:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("patients", sa.Column("age", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("patients", "age")
