"""Extend audit records with domain and request metadata."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        op.add_column("audit_log", sa.Column("role", sa.String(50), nullable=True), schema="public")
        op.add_column("audit_log", sa.Column("request_id", sa.String(100), nullable=True), schema="public")
        op.add_column("audit_log", sa.Column("request_metadata", postgresql.JSONB(), nullable=True), schema="public")
        return

    op.add_column("audit_logs", sa.Column("tenant_schema", sa.String(100), nullable=True))
    op.add_column("audit_logs", sa.Column("role", sa.String(50), nullable=True))
    op.add_column("audit_logs", sa.Column("visit_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("audit_logs", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("request_metadata", postgresql.JSONB(), nullable=True))
    op.create_index("ix_audit_logs_visit_id", "audit_logs", ["visit_id"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        op.drop_column("audit_log", "request_metadata", schema="public")
        op.drop_column("audit_log", "request_id", schema="public")
        op.drop_column("audit_log", "role", schema="public")
        return
    op.drop_index("ix_audit_logs_visit_id", table_name="audit_logs")
    for column in ("request_metadata", "reason", "visit_id", "role", "tenant_schema"):
        op.drop_column("audit_logs", column)
