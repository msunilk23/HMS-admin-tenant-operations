"""Add facility_id to lab_orders for multi-facility scoping."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def _is_tenant_schema(bind) -> bool:
    return bind.execute(text("SELECT current_schema()")).scalar() != "public"


def _table_columns(bind, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("lab_orders"):
        return

    lab_orders_columns = _table_columns(bind, "lab_orders")
    if "facility_id" not in lab_orders_columns:
        op.add_column(
            "lab_orders",
            sa.Column("facility_id", sa.UUID(), nullable=True),
        )

    # Create index for facility filtering
    lab_orders_indexes = {index["name"] for index in inspector.get_indexes("lab_orders")}
    if "ix_lab_orders_facility_id" not in lab_orders_indexes:
        op.create_index(
            "ix_lab_orders_facility_id",
            "lab_orders",
            ["facility_id"],
        )

    # Create FK constraint if facilities table exists
    if inspector.has_table("facilities"):
        foreign_keys = {
            constraint.get("name")
            for constraint in sa.inspect(bind).get_foreign_keys("lab_orders")
        }
        if "fk_lab_orders_facility_id" not in foreign_keys:
            op.create_foreign_key(
                "fk_lab_orders_facility_id",
                "lab_orders",
                "facilities",
                ["facility_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return
    
    inspector = sa.inspect(bind)
    if not inspector.has_table("lab_orders"):
        return

    # Drop FK first
    foreign_keys = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_foreign_keys("lab_orders")
    }
    if "fk_lab_orders_facility_id" in foreign_keys:
        op.drop_constraint("fk_lab_orders_facility_id", "lab_orders", type_="foreignkey")

    # Drop index
    lab_orders_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("lab_orders")}
    if "ix_lab_orders_facility_id" in lab_orders_indexes:
        op.drop_index("ix_lab_orders_facility_id", table_name="lab_orders")

    # Drop column
    if "facility_id" in _table_columns(bind, "lab_orders"):
        op.drop_column("lab_orders", "facility_id")
