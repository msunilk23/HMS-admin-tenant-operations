"""Create the tenant-scoped manufacturer master."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if sa.inspect(bind).has_table("manufacturers"):
        return

    op.create_table(
        "manufacturers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_manufacturers_code"),
    )
    op.create_index("ix_manufacturers_code", "manufacturers", ["code"])
    op.create_index("ix_manufacturers_name", "manufacturers", ["name"])
    op.create_index("ix_manufacturers_is_active", "manufacturers", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("manufacturers"):
        return

    op.drop_index("ix_manufacturers_is_active", table_name="manufacturers")
    op.drop_index("ix_manufacturers_name", table_name="manufacturers")
    op.drop_index("ix_manufacturers_code", table_name="manufacturers")
    op.drop_table("manufacturers")
