"""Create the tenant-scoped generic medicine master."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0050"
down_revision = "0049_consultation_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if sa.inspect(bind).has_table("generic_medicines"):
        return

    op.create_table(
        "generic_medicines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("therapeutic_class", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_generic_medicines_code"),
    )
    op.create_index("ix_generic_medicines_code", "generic_medicines", ["code"])
    op.create_index("ix_generic_medicines_name", "generic_medicines", ["name"])
    op.create_index("ix_generic_medicines_is_active", "generic_medicines", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("generic_medicines"):
        return

    op.drop_index("ix_generic_medicines_is_active", table_name="generic_medicines")
    op.drop_index("ix_generic_medicines_name", table_name="generic_medicines")
    op.drop_index("ix_generic_medicines_code", table_name="generic_medicines")
    op.drop_table("generic_medicines")
