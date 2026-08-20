"""Expand queue priority metadata for A7 and configure SLA fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.alter_column("queue_tokens", "priority", type_=sa.String(30), existing_type=sa.String(20), existing_nullable=False)
    op.add_column("queue_tokens", sa.Column("priority_reason", sa.Text(), nullable=True))
    op.add_column("queue_tokens", sa.Column("priority_assigned_by", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("queue_tokens", sa.Column("priority_assigned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.drop_column("queue_tokens", "priority_assigned_at")
    op.drop_column("queue_tokens", "priority_assigned_by")
    op.drop_column("queue_tokens", "priority_reason")
    op.alter_column("queue_tokens", "priority", type_=sa.String(20), existing_type=sa.String(30), existing_nullable=False)
