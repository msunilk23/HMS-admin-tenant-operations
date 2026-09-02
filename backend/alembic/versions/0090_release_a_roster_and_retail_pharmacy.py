"""Release A roster facility scope and retail pharmacy sales.

Revision ID: 0090
Revises: 0089
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def _uuid(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar_one()
    if schema == "public":
        return

    inspector = sa.inspect(bind)
    roster_columns = {column["name"] for column in inspector.get_columns("nurse_roster")}
    if "facility_id" not in roster_columns:
        op.add_column("nurse_roster", _uuid("facility_id"))
        tenant_id = bind.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :schema"),
            {"schema": schema},
        ).scalar_one()
        bind.execute(text("UPDATE nurse_roster SET facility_id = :facility_id"), {"facility_id": tenant_id})
        op.alter_column("nurse_roster", "facility_id", nullable=False)
        op.create_index("ix_nurse_roster_facility_id", "nurse_roster", ["facility_id"])

    duplicates = bind.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT facility_id, user_id, date, shift
            FROM nurse_roster
            GROUP BY facility_id, user_id, date, shift
            HAVING COUNT(*) > 1
        ) duplicate_assignments
    """)).scalar_one()
    if duplicates:
        raise RuntimeError("Cannot enforce roster uniqueness while duplicate facility/user/date/shift assignments exist")
    roster_uniques = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("nurse_roster")}
    if "uq_nurse_roster_facility_user_date_shift" not in roster_uniques:
        op.create_unique_constraint(
            "uq_nurse_roster_facility_user_date_shift", "nurse_roster", ["facility_id", "user_id", "date", "shift"]
        )

    if inspector.has_table("pharmacy_retail_configurations"):
        return

    op.create_table(
        "pharmacy_retail_configurations",
        _uuid("id", False), _uuid("tenant_id", False),
        sa.Column("non_controlled_validity_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("non_controlled_max_supply_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("controlled_validity_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("controlled_max_supply_days", sa.Integer(), nullable=False, server_default="7"),
        _uuid("updated_by"), *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_pharmacy_retail_config_tenant"),
        sa.CheckConstraint("non_controlled_validity_days BETWEEN 1 AND 30", name="ck_retail_config_noncontrolled_validity"),
        sa.CheckConstraint("non_controlled_max_supply_days BETWEEN 1 AND 30", name="ck_retail_config_noncontrolled_supply"),
        sa.CheckConstraint("controlled_validity_days BETWEEN 1 AND 7", name="ck_retail_config_controlled_validity"),
        sa.CheckConstraint("controlled_max_supply_days BETWEEN 1 AND 7", name="ck_retail_config_controlled_supply"),
    )
    op.create_index("ix_pharmacy_retail_configurations_tenant_id", "pharmacy_retail_configurations", ["tenant_id"])

    op.create_table(
        "pharmacist_location_authorizations",
        _uuid("id", False), _uuid("tenant_id", False), _uuid("facility_id", False),
        _uuid("pharmacy_location_id", False), _uuid("user_id", False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _uuid("authorized_by", False), *_timestamps(),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "facility_id", "pharmacy_location_id", "user_id", name="uq_pharmacist_location_authorization"),
    )
    for column in ("tenant_id", "facility_id", "pharmacy_location_id", "user_id", "is_active"):
        op.create_index(f"ix_pharmacist_location_authorizations_{column}", "pharmacist_location_authorizations", [column])

    op.create_table(
        "pharmacy_retail_sales",
        _uuid("id", False), _uuid("tenant_id", False), _uuid("facility_id", False), _uuid("pharmacy_location_id", False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("controlled_sale", sa.Boolean(), nullable=False, server_default=sa.false()),
        _uuid("patient_id"), sa.Column("customer_reference", sa.String(50), nullable=False),
        sa.Column("patient_name", sa.String(200)), sa.Column("patient_date_of_birth", sa.Date()),
        sa.Column("patient_age", sa.Integer()), sa.Column("patient_gender", sa.String(30)),
        sa.Column("patient_mobile", sa.String(30)), sa.Column("patient_address", sa.Text()),
        sa.Column("government_id_type", sa.String(50)), sa.Column("government_id_last_four", sa.String(4)),
        sa.Column("prescriber_name", sa.String(200)), sa.Column("prescriber_registration_number", sa.String(100)),
        sa.Column("prescription_date", sa.Date()), sa.Column("issuing_facility", sa.String(200)),
        sa.Column("prescription_reference", sa.String(100)), sa.Column("prescription_attachment_reference", sa.Text()),
        sa.Column("original_prescription_inspected", sa.Boolean(), nullable=False, server_default=sa.false()),
        _uuid("verified_by"), sa.Column("verified_at", sa.DateTime(timezone=True)),
        _uuid("dispensed_by"), sa.Column("dispensed_at", sa.DateTime(timezone=True)),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("discount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("payment_method", sa.String(30)), sa.Column("payment_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("payment_reference", sa.String(120)), sa.Column("receipt_number", sa.String(50)),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("rejection_reason", sa.Text()), sa.Column("cancellation_reason", sa.Text()), _uuid("created_by", False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_retail_sale_idempotency"),
        sa.UniqueConstraint("tenant_id", "receipt_number", name="uq_pharmacy_retail_sale_receipt"),
        sa.CheckConstraint("classification IN ('OTC', 'EXTERNAL_PRESCRIPTION')", name="ck_pharmacy_retail_sale_classification"),
        sa.CheckConstraint("status IN ('DRAFT', 'PENDING_VERIFICATION', 'VERIFIED', 'FULLY_DISPENSED', 'REJECTED', 'CANCELLED', 'EXPIRED')", name="ck_pharmacy_retail_sale_status"),
        sa.CheckConstraint("payment_status IN ('PENDING', 'PAID', 'FAILED', 'REFUNDED')", name="ck_pharmacy_retail_sale_payment_status"),
        sa.CheckConstraint("verified_by IS NULL OR dispensed_by IS NULL OR controlled_sale = false OR verified_by <> dispensed_by", name="ck_pharmacy_retail_controlled_maker_checker"),
    )
    for column in ("tenant_id", "facility_id", "pharmacy_location_id", "status", "patient_id", "customer_reference", "verified_by", "dispensed_by"):
        op.create_index(f"ix_pharmacy_retail_sales_{column}", "pharmacy_retail_sales", [column])

    op.create_table(
        "pharmacy_retail_sale_items",
        _uuid("id", False), _uuid("sale_id", False), _uuid("medicine_product_id", False),
        sa.Column("medicine_name_snapshot", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False), sa.Column("prescribed_quantity", sa.Numeric(12, 3)),
        sa.Column("prescribed_duration_days", sa.Integer()),
        sa.Column("requires_prescription", sa.Boolean(), nullable=False), sa.Column("is_controlled_drug", sa.Boolean(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False), sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("line_subtotal", sa.Numeric(12, 2), nullable=False), sa.Column("line_tax", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["sale_id"], ["pharmacy_retail_sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["medicine_product_id"], ["medicine_products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_id", "medicine_product_id", name="uq_pharmacy_retail_sale_item_product"),
        sa.CheckConstraint("quantity > 0", name="ck_pharmacy_retail_sale_item_quantity"),
        sa.CheckConstraint("prescribed_quantity IS NULL OR prescribed_quantity > 0", name="ck_pharmacy_retail_prescribed_quantity"),
    )
    op.create_index("ix_pharmacy_retail_sale_items_sale_id", "pharmacy_retail_sale_items", ["sale_id"])
    op.create_index("ix_pharmacy_retail_sale_items_medicine_product_id", "pharmacy_retail_sale_items", ["medicine_product_id"])

    op.create_table(
        "pharmacy_retail_sale_allocations",
        _uuid("id", False), _uuid("sale_item_id", False), _uuid("inventory_batch_id", False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False), sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        _uuid("stock_transaction_id", False), *_timestamps(),
        sa.ForeignKeyConstraint(["sale_item_id"], ["pharmacy_retail_sale_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
        sa.ForeignKeyConstraint(["stock_transaction_id"], ["stock_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_item_id", "inventory_batch_id", name="uq_pharmacy_retail_allocation_batch"),
        sa.UniqueConstraint("stock_transaction_id", name="uq_pharmacy_retail_allocation_stock_transaction"),
        sa.CheckConstraint("quantity > 0", name="ck_pharmacy_retail_allocation_quantity"),
    )
    op.create_index("ix_pharmacy_retail_sale_allocations_sale_item_id", "pharmacy_retail_sale_allocations", ["sale_item_id"])
    op.create_index("ix_pharmacy_retail_sale_allocations_inventory_batch_id", "pharmacy_retail_sale_allocations", ["inventory_batch_id"])

    op.create_table(
        "pharmacy_retail_invoices",
        _uuid("id", False), _uuid("sale_id", False), _uuid("tenant_id", False), _uuid("facility_id", False),
        _uuid("pharmacy_location_id", False), sa.Column("invoice_number", sa.String(50), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False), sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax", sa.Numeric(12, 2), nullable=False), sa.Column("discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False), sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PAID"), *_timestamps(),
        sa.ForeignKeyConstraint(["sale_id"], ["pharmacy_retail_sales.id"]),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_id", name="uq_pharmacy_retail_invoice_sale"),
        sa.UniqueConstraint("tenant_id", "invoice_number", name="uq_pharmacy_retail_invoice_number"),
        sa.CheckConstraint("classification IN ('OTC', 'EXTERNAL_PRESCRIPTION')", name="ck_pharmacy_retail_invoice_classification"),
        sa.CheckConstraint("status IN ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED')", name="ck_pharmacy_retail_invoice_status"),
    )
    for column in ("sale_id", "tenant_id", "facility_id", "pharmacy_location_id", "status"):
        op.create_index(f"ix_pharmacy_retail_invoices_{column}", "pharmacy_retail_invoices", [column])

    op.create_table(
        "pharmacy_retail_payments", _uuid("id", False), _uuid("invoice_id", False), _uuid("tenant_id", False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False), sa.Column("payment_method", sa.String(30), nullable=False),
        sa.Column("transaction_reference", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="CAPTURED"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["invoice_id"], ["pharmacy_retail_invoices.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", name="uq_pharmacy_retail_payment_invoice"),
        sa.UniqueConstraint("tenant_id", "transaction_reference", name="uq_pharmacy_retail_payment_reference"),
        sa.CheckConstraint("status IN ('CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED')", name="ck_pharmacy_retail_payment_status"),
    )
    for column in ("invoice_id", "tenant_id", "status"):
        op.create_index(f"ix_pharmacy_retail_payments_{column}", "pharmacy_retail_payments", [column])

    op.create_table(
        "pharmacy_retail_returns", _uuid("id", False), _uuid("sale_id", False), _uuid("invoice_id", False),
        _uuid("tenant_id", False), _uuid("facility_id", False), _uuid("pharmacy_location_id", False),
        sa.Column("return_number", sa.String(50), nullable=False), sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="REFUNDED"), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("total_quantity", sa.Numeric(12, 3), nullable=False), sa.Column("refund_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        _uuid("processed_by", False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["sale_id"], ["pharmacy_retail_sales.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["pharmacy_retail_invoices.id"]),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_retail_return_idempotency"),
        sa.UniqueConstraint("tenant_id", "return_number", name="uq_pharmacy_retail_return_number"),
        sa.CheckConstraint("classification IN ('OTC', 'EXTERNAL_PRESCRIPTION')", name="ck_pharmacy_retail_return_classification"),
        sa.CheckConstraint("status IN ('REFUNDED', 'NON_RESTOCKABLE')", name="ck_pharmacy_retail_return_status"),
    )
    for column in ("sale_id", "invoice_id", "tenant_id", "facility_id", "pharmacy_location_id", "status", "processed_by"):
        op.create_index(f"ix_pharmacy_retail_returns_{column}", "pharmacy_retail_returns", [column])

    op.create_table(
        "pharmacy_retail_return_allocations", _uuid("id", False), _uuid("return_id", False),
        _uuid("sale_allocation_id", False), _uuid("inventory_batch_id", False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False), sa.Column("refund_amount", sa.Numeric(12, 2), nullable=False),
        _uuid("stock_transaction_id", False), *_timestamps(),
        sa.ForeignKeyConstraint(["return_id"], ["pharmacy_retail_returns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_allocation_id"], ["pharmacy_retail_sale_allocations.id"]),
        sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
        sa.ForeignKeyConstraint(["stock_transaction_id"], ["stock_transactions.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("return_id", "sale_allocation_id", name="uq_pharmacy_retail_return_allocation_source"),
        sa.UniqueConstraint("stock_transaction_id", name="uq_pharmacy_retail_return_allocation_ledger"),
        sa.CheckConstraint("quantity > 0", name="ck_pharmacy_retail_return_allocation_quantity"),
    )
    for column in ("return_id", "sale_allocation_id", "inventory_batch_id"):
        op.create_index(f"ix_pharmacy_retail_return_allocations_{column}", "pharmacy_retail_return_allocations", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()" )).scalar_one() == "public":
        return
    inspector = sa.inspect(bind)
    for table_name in (
        "pharmacy_retail_return_allocations",
        "pharmacy_retail_returns",
        "pharmacy_retail_payments",
        "pharmacy_retail_invoices",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
    op.drop_table("pharmacy_retail_sale_allocations")
    op.drop_table("pharmacy_retail_sale_items")
    op.drop_table("pharmacy_retail_sales")
    op.drop_table("pharmacist_location_authorizations")
    op.drop_table("pharmacy_retail_configurations")
    op.drop_constraint("uq_nurse_roster_facility_user_date_shift", "nurse_roster", type_="unique")
    op.drop_index("ix_nurse_roster_facility_id", table_name="nurse_roster")
    op.drop_column("nurse_roster", "facility_id")