"""Add source and pharmacy_queue_id to invoices table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("invoices", sa.Column("source", sa.String(20), nullable=True, server_default="consultation"))
    op.add_column("invoices", sa.Column("pharmacy_queue_id", sa.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("invoices", "pharmacy_queue_id")
    op.drop_column("invoices", "source")
