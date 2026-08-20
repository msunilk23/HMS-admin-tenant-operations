"""Add lab result verification fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.add_column("lab_results", sa.Column("verified_by_user_id", sa.UUID(), nullable=True))
    op.add_column("lab_results", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE lab_orders SET status = 'result_ready' WHERE status = 'resulted'")


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.drop_column("lab_results", "verified_at")
    op.drop_column("lab_results", "verified_by_user_id")