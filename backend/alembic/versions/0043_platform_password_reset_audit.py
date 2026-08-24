"""Add public audit records for platform password resets."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "0045_platform_pw_reset_audit"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().execute(text("SELECT current_schema()")).scalar() != "public":
        return
    op.create_table(
        "platform_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_role", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index(
        "ix_platform_audit_log_tenant_timestamp",
        "platform_audit_log",
        ["tenant_id", "timestamp"],
        schema="public",
    )
    op.create_index(
        "ix_platform_audit_log_target_timestamp",
        "platform_audit_log",
        ["target_user_id", "timestamp"],
        schema="public",
    )
    op.create_index(
        "ix_platform_audit_log_request_id",
        "platform_audit_log",
        ["request_id"],
        schema="public",
    )


def downgrade() -> None:
    if op.get_bind().execute(text("SELECT current_schema()")).scalar() != "public":
        return
    op.drop_index("ix_platform_audit_log_request_id", table_name="platform_audit_log", schema="public")
    op.drop_index("ix_platform_audit_log_target_timestamp", table_name="platform_audit_log", schema="public")
    op.drop_index("ix_platform_audit_log_tenant_timestamp", table_name="platform_audit_log", schema="public")
    op.drop_table("platform_audit_log", schema="public")
