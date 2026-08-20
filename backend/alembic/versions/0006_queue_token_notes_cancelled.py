"""Add notes and cancelled_at to queue_tokens; status becomes checked_in on issuance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("queue_tokens", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("queue_tokens", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("queue_tokens", "cancelled_at")
    op.drop_column("queue_tokens", "notes")
