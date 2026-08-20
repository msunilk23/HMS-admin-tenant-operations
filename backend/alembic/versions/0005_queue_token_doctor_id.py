"""Add doctor_id to queue_tokens so reception pre-assigns a doctor at token issuance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column(
        "queue_tokens",
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_queue_tokens_doctor",
        "queue_tokens", "doctors",
        ["doctor_id"], ["id"],
    )
    op.create_index("ix_queue_tokens_doctor_id", "queue_tokens", ["doctor_id"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_constraint("fk_queue_tokens_doctor", "queue_tokens", type_="foreignkey")
    op.drop_index("ix_queue_tokens_doctor_id", "queue_tokens")
    op.drop_column("queue_tokens", "doctor_id")
