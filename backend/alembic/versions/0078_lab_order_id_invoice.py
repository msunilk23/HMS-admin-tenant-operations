"""Add lab_order_id to invoices table for lab billing integration."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0078"
down_revision = "0077"
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
    if not inspector.has_table("invoices"):
        return

    invoice_columns = _table_columns(bind, "invoices")
    if "lab_order_id" not in invoice_columns:
        op.add_column(
            "invoices",
            sa.Column("lab_order_id", sa.UUID(), nullable=True),
        )

    # Create index
    invoice_indexes = {index["name"] for index in inspector.get_indexes("invoices")}
    if "ix_invoices_lab_order_id" not in invoice_indexes:
        op.create_index(
            "ix_invoices_lab_order_id",
            "invoices",
            ["lab_order_id"],
        )

    # Create unique constraint to ensure one invoice per lab order
    unique_constraints = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_unique_constraints("invoices")
    }
    if "uq_invoices_lab_order_id" not in unique_constraints:
        op.create_unique_constraint(
            "uq_invoices_lab_order_id",
            "invoices",
            ["lab_order_id"],
        )

    # Create FK constraint if lab_orders table exists
    if inspector.has_table("lab_orders"):
        foreign_keys = {
            constraint.get("name")
            for constraint in sa.inspect(bind).get_foreign_keys("invoices")
        }
        if "fk_invoices_lab_order_id" not in foreign_keys:
            op.create_foreign_key(
                "fk_invoices_lab_order_id",
                "invoices",
                "lab_orders",
                ["lab_order_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return
    
    inspector = sa.inspect(bind)
    if not inspector.has_table("invoices"):
        return

    # Drop FK first
    foreign_keys = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_foreign_keys("invoices")
    }
    if "fk_invoices_lab_order_id" in foreign_keys:
        op.drop_constraint("fk_invoices_lab_order_id", "invoices", type_="foreignkey")

    # Drop unique constraint
    unique_constraints = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_unique_constraints("invoices")
    }
    if "uq_invoices_lab_order_id" in unique_constraints:
        op.drop_constraint("uq_invoices_lab_order_id", "invoices", type_="unique")

    # Drop index
    invoice_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("invoices")}
    if "ix_invoices_lab_order_id" in invoice_indexes:
        op.drop_index("ix_invoices_lab_order_id", table_name="invoices")

    # Drop column
    if "lab_order_id" in _table_columns(bind, "invoices"):
        op.drop_column("invoices", "lab_order_id")
