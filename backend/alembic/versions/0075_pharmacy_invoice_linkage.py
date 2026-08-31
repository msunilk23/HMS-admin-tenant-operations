"""Make pharmacy invoice and dispense linkage authoritative."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def _is_tenant_schema(bind) -> bool:
    return bind.execute(text("SELECT current_schema()")).scalar() != "public"


def _table_columns(bind, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def _foreign_key_names(bind, table_name: str) -> set[str]:
    return {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_foreign_keys(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("invoices") or not inspector.has_table("pharmacy_dispenses"):
        return

    invoice_columns = _table_columns(bind, "invoices")
    if "pharmacy_dispense_id" not in invoice_columns:
        op.add_column(
            "invoices",
            sa.Column("pharmacy_dispense_id", sa.UUID(), nullable=True),
        )

    dispense_columns = _table_columns(bind, "pharmacy_dispenses")
    if "invoice_id" not in dispense_columns:
        op.add_column(
            "pharmacy_dispenses",
            sa.Column("invoice_id", sa.UUID(), nullable=True),
        )

    inspector = sa.inspect(bind)
    invoice_indexes = {index["name"] for index in inspector.get_indexes("invoices")}
    if "ix_invoices_pharmacy_dispense_id" not in invoice_indexes:
        op.create_index(
            "ix_invoices_pharmacy_dispense_id",
            "invoices",
            ["pharmacy_dispense_id"],
        )
    dispense_indexes = {index["name"] for index in inspector.get_indexes("pharmacy_dispenses")}
    if "ix_pharmacy_dispenses_invoice_id" not in dispense_indexes:
        op.create_index(
            "ix_pharmacy_dispenses_invoice_id",
            "pharmacy_dispenses",
            ["invoice_id"],
        )

    unique_constraints = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_unique_constraints("invoices")
    }
    if "uq_invoices_pharmacy_dispense" not in unique_constraints:
        op.create_unique_constraint(
            "uq_invoices_pharmacy_dispense",
            "invoices",
            ["pharmacy_dispense_id"],
        )

    invalid_invoice_links = bind.execute(text("""
        SELECT COUNT(*)
        FROM invoices i
        LEFT JOIN pharmacy_dispenses d ON d.id = i.pharmacy_dispense_id
        WHERE i.pharmacy_dispense_id IS NOT NULL AND d.id IS NULL
    """)).scalar()
    invalid_dispense_links = bind.execute(text("""
        SELECT COUNT(*)
        FROM pharmacy_dispenses d
        LEFT JOIN invoices i ON i.id = d.invoice_id
        WHERE d.invoice_id IS NOT NULL AND i.id IS NULL
    """)).scalar()
    if invalid_invoice_links or invalid_dispense_links:
        raise RuntimeError(
            "Cannot add pharmacy invoice linkage foreign keys: "
            f"invalid invoice links={invalid_invoice_links}, "
            f"invalid dispense links={invalid_dispense_links}"
        )

    foreign_keys = _foreign_key_names(bind, "invoices")
    if "fk_invoices_pharmacy_dispense_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_invoices_pharmacy_dispense_id",
            "invoices",
            "pharmacy_dispenses",
            ["pharmacy_dispense_id"],
            ["id"],
        )
    foreign_keys = _foreign_key_names(bind, "pharmacy_dispenses")
    if "fk_pharmacy_dispenses_invoice_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_pharmacy_dispenses_invoice_id",
            "pharmacy_dispenses",
            "invoices",
            ["invoice_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("invoices") or not inspector.has_table("pharmacy_dispenses"):
        return

    invoice_fks = _foreign_key_names(bind, "invoices")
    if "fk_invoices_pharmacy_dispense_id" in invoice_fks:
        op.drop_constraint("fk_invoices_pharmacy_dispense_id", "invoices", type_="foreignkey")
    dispense_fks = _foreign_key_names(bind, "pharmacy_dispenses")
    if "fk_pharmacy_dispenses_invoice_id" in dispense_fks:
        op.drop_constraint("fk_pharmacy_dispenses_invoice_id", "pharmacy_dispenses", type_="foreignkey")

    invoice_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("invoices")}
    if "ix_invoices_pharmacy_dispense_id" in invoice_indexes:
        op.drop_index("ix_invoices_pharmacy_dispense_id", table_name="invoices")
    dispense_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("pharmacy_dispenses")}
    if "ix_pharmacy_dispenses_invoice_id" in dispense_indexes:
        op.drop_index("ix_pharmacy_dispenses_invoice_id", table_name="pharmacy_dispenses")

    if "invoice_id" in _table_columns(bind, "pharmacy_dispenses"):
        op.drop_column("pharmacy_dispenses", "invoice_id")
    if "pharmacy_dispense_id" in _table_columns(bind, "invoices"):
        op.drop_column("invoices", "pharmacy_dispense_id")
