"""Add report_url and critical_flags to lab_results; add rejected status support."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("lab_results", sa.Column("critical_flags", JSONB, nullable=True))
    op.add_column("lab_results", sa.Column("report_url", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("lab_results", "report_url")
    op.drop_column("lab_results", "critical_flags")
