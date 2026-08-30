"""Add patient return idempotency request hashes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("patient_returns") and "request_hash" not in {column["name"] for column in inspector.get_columns("patient_returns")}:
        op.add_column("patient_returns", sa.Column("request_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("patient_returns") and "request_hash" in {column["name"] for column in inspector.get_columns("patient_returns")}:
        op.drop_column("patient_returns", "request_hash")