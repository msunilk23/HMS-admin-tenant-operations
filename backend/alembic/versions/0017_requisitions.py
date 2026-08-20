"""Add requisitions table to tenant schemas

Revision ID: 0017
Revises: 0016
Create Date: 2025-01-01 00:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    # Only run on tenant schemas (not public)
    if current_schema == "public":
        return

    op.create_table(
        "requisitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("requisition_number", sa.String(30), nullable=False, unique=True),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_name", sa.String(255), nullable=False),
        sa.Column("from_location", sa.String(255), nullable=False),
        sa.Column("to_location", sa.String(100), nullable=False),
        sa.Column("request_date", sa.Date(), nullable=False),
        sa.Column("need_by_date", sa.Date(), nullable=False),
        sa.Column("items", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_requisitions_requisition_number", "requisitions", ["requisition_number"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.drop_table("requisitions")
