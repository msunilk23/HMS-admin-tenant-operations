"""Add patient and request context fields to transactional domain audits."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("audit_logs", sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(100), nullable=True))
    op.add_column("audit_logs", sa.Column("source_ip", sa.String(45), nullable=True))
    op.create_index("ix_audit_logs_patient_id", "audit_logs", ["patient_id"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_patient_id", table_name="audit_logs")
    op.drop_column("audit_logs", "source_ip")
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "patient_id")
