"""Allow descriptive schedule audit action names."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0046_schedule_audit_action"
down_revision = "0045_platform_pw_reset_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        op.alter_column("audit_logs", "action", type_=sa.String(64), existing_type=sa.String(20), existing_nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        op.alter_column("audit_logs", "action", type_=sa.String(20), existing_type=sa.String(64), existing_nullable=False)
