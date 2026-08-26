"""Create tenant-scoped dosage form and route masters."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def _create_dosage_forms(bind) -> None:
    if sa.inspect(bind).has_table("dosage_forms"):
        return
    op.create_table(
        "dosage_forms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("calculation_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_dosage_forms_code"),
    )
    op.create_index("ix_dosage_forms_code", "dosage_forms", ["code"])
    op.create_index("ix_dosage_forms_name", "dosage_forms", ["name"])
    op.create_index("ix_dosage_forms_calculation_type", "dosage_forms", ["calculation_type"])
    op.create_index("ix_dosage_forms_is_active", "dosage_forms", ["is_active"])


def _create_routes(bind) -> None:
    if sa.inspect(bind).has_table("routes"):
        return
    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_routes_code"),
    )
    op.create_index("ix_routes_code", "routes", ["code"])
    op.create_index("ix_routes_name", "routes", ["name"])
    op.create_index("ix_routes_is_active", "routes", ["is_active"])


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    _create_dosage_forms(bind)
    _create_routes(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return

    if sa.inspect(bind).has_table("routes"):
        op.drop_index("ix_routes_is_active", table_name="routes")
        op.drop_index("ix_routes_name", table_name="routes")
        op.drop_index("ix_routes_code", table_name="routes")
        op.drop_table("routes")
    if sa.inspect(bind).has_table("dosage_forms"):
        op.drop_index("ix_dosage_forms_is_active", table_name="dosage_forms")
        op.drop_index("ix_dosage_forms_calculation_type", table_name="dosage_forms")
        op.drop_index("ix_dosage_forms_name", table_name="dosage_forms")
        op.drop_index("ix_dosage_forms_code", table_name="dosage_forms")
        op.drop_table("dosage_forms")
