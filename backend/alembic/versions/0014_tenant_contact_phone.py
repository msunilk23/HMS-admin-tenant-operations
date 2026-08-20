"""Add contact_phone to public.tenants table."""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Only applies to the public schema.
    current_schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema != "public":
        return

    col_exists = bind.execute(sa.text(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.columns"
        "  WHERE table_schema = 'public' AND table_name = 'tenants'"
        "  AND column_name = 'contact_phone'"
        ")"
    )).scalar()
    if col_exists:
        return

    op.add_column(
        "tenants",
        sa.Column("contact_phone", sa.String(20), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("tenants", "contact_phone", schema="public")
