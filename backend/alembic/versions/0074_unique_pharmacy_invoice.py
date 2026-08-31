"""Prevent duplicate invoices for one pharmacy dispense."""

from alembic import op
from sqlalchemy import inspect

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "invoices" not in inspector.get_table_names():
        return
    if "pharmacy_dispense_id" not in {
        column["name"] for column in inspector.get_columns("invoices")
    }:
        return
    existing = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("invoices")
    }
    if "uq_invoices_pharmacy_dispense" not in existing:
        op.create_unique_constraint(
            "uq_invoices_pharmacy_dispense",
            "invoices",
            ["pharmacy_dispense_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "invoices" not in inspector.get_table_names():
        return
    if "pharmacy_dispense_id" not in {
        column["name"] for column in inspector.get_columns("invoices")
    }:
        return
    existing = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("invoices")
    }
    if "uq_invoices_pharmacy_dispense" in existing:
        op.drop_constraint("uq_invoices_pharmacy_dispense", "invoices", type_="unique")
