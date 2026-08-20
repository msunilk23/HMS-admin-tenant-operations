"""Make users.email nullable (email is optional for staff accounts)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    # Allow NULL in the email column — Postgres unique constraints already permit
    # multiple NULLs (each NULL is considered distinct), so no constraint change needed.
    op.alter_column("users", "email", nullable=True, schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    op.alter_column("users", "email", nullable=False, schema="public")
