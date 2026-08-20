"""Add emergency contact columns to patients table

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-12 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("patients", sa.Column("emergency_contact_name", sa.String(200), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_phone", sa.String(15), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_relation", sa.String(50), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("patients", "emergency_contact_relation")
    op.drop_column("patients", "emergency_contact_phone")
    op.drop_column("patients", "emergency_contact_name")
