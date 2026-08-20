"""Add visit_id to queue_tokens so Payment column can fetch invoice in reception grid."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column(
        "queue_tokens",
        sa.Column("visit_id", sa.UUID(), nullable=True),
    )
    op.create_index("ix_queue_tokens_visit_id", "queue_tokens", ["visit_id"])
    op.create_foreign_key(
        "fk_queue_tokens_visit_id",
        "queue_tokens", "visits",
        ["visit_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_constraint("fk_queue_tokens_visit_id", "queue_tokens", type_="foreignkey")
    op.drop_index("ix_queue_tokens_visit_id", table_name="queue_tokens")
    op.drop_column("queue_tokens", "visit_id")
