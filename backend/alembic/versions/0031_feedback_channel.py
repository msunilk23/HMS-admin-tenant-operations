"""Add feedback channel metadata."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    op.add_column("feedback", sa.Column("channel", sa.String(20), nullable=True, server_default="staff"))
    op.execute("UPDATE feedback SET channel = 'staff' WHERE channel IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    op.drop_column("feedback", "channel")
