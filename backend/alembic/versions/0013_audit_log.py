"""Create public.audit_log table for immutable request audit trail.

Records every mutating API call (POST/PUT/PATCH/DELETE) with tenant, user,
method, path, status code, and client IP. Used for compliance and debugging.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Only create in public schema. Guard avoids failure when running upgrade
    # for a new tenant schema (env.py runs migrations for all schemas).
    current_schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    table_exists = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'audit_log')"
    )).scalar()
    if table_exists:
        return

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_schema", sa.Text(), nullable=False, server_default="public"),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="public",
    )
    # Index for efficient per-tenant queries by time
    op.create_index(
        "ix_audit_log_tenant_created",
        "audit_log",
        ["tenant_schema", "created_at"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_tenant_created", table_name="audit_log", schema="public")
    op.drop_table("audit_log", schema="public")
