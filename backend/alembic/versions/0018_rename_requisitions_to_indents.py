"""Rename requisitions table → indents, requisition_number → indent_number

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-09 00:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    # Rename requisition_number → indent_number
    op.alter_column("requisitions", "requisition_number", new_column_name="indent_number")

    # Rename the unique index (old name from migration 0017)
    op.execute(
        text(
            f'ALTER INDEX IF EXISTS "{current_schema}".ix_requisitions_requisition_number '
            f'RENAME TO ix_indents_indent_number'
        )
    )

    # Rename the table itself
    op.rename_table("requisitions", "indents")


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.rename_table("indents", "requisitions")
    op.execute(
        text(
            f'ALTER INDEX IF EXISTS "{current_schema}".ix_indents_indent_number '
            f'RENAME TO ix_requisitions_requisition_number'
        )
    )
    op.alter_column("requisitions", "indent_number", new_column_name="requisition_number")
