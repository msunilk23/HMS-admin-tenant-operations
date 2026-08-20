"""Add per-tenant logo and color branding."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return
    op.add_column("tenants", sa.Column("logo_url", sa.String(500), nullable=True), schema="public")
    op.add_column("tenants", sa.Column("primary_color", sa.String(7), nullable=True), schema="public")
    op.add_column("tenants", sa.Column("secondary_color", sa.String(7), nullable=True), schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return
    op.drop_column("tenants", "secondary_color", schema="public")
    op.drop_column("tenants", "primary_color", schema="public")
    op.drop_column("tenants", "logo_url", schema="public")
