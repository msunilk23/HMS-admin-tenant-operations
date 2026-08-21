"""Add database-backed session invalidation state for users and tenants."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"), schema="public")
    op.add_column("users", sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True), schema="public")
    op.add_column("tenants", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"), schema="public")
    op.add_column("tenants", sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True), schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    op.drop_column("tenants", "tokens_valid_after", schema="public")
    op.drop_column("tenants", "session_version", schema="public")
    op.drop_column("users", "tokens_valid_after", schema="public")
    op.drop_column("users", "session_version", schema="public")
