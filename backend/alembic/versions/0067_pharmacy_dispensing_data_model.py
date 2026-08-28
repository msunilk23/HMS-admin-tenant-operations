"""Create P28 dispensing and reservation data model."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def _uuid(name, nullable=True):
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _timestamp(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=sa.func.now())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)

    if inspector.has_table("prescription_items"):
        columns = {column["name"] for column in inspector.get_columns("prescription_items")}
        if "no_substitution" not in columns:
            op.add_column("prescription_items", sa.Column("no_substitution", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "no_substitution_reason" not in columns:
            op.add_column("prescription_items", sa.Column("no_substitution_reason", sa.Text(), nullable=True))

    if inspector.has_table("prescriptions"):
        columns = {column["name"] for column in inspector.get_columns("prescriptions")}
        if "version" not in columns:
            op.add_column("prescriptions", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    if not inspector.has_table("pharmacy_dispenses"):
        op.create_table(
            "pharmacy_dispenses",
            _uuid("id", False), _uuid("tenant_id", False), _uuid("facility_id", False),
            _uuid("pharmacy_location_id", False), _uuid("prescription_id", False),
            sa.Column("prescription_version", sa.Integer(), nullable=False, server_default="1"),
            _uuid("visit_id", False), _uuid("patient_id", False), _uuid("pharmacy_queue_id"),
            sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
            sa.Column("fulfillment_mode", sa.String(40), nullable=False, server_default="FULL_INTERNAL"),
            sa.Column("billing_status", sa.String(30), nullable=False, server_default="NOT_REQUIRED"),
            sa.Column("idempotency_key", sa.String(100), nullable=True),
            sa.Column("request_hash", sa.String(128), nullable=True),
            _timestamp("started_at"), _uuid("started_by"), _timestamp("ready_for_billing_at"), _uuid("ready_for_billing_by"),
            _timestamp("completed_at"), _uuid("completed_by"), _timestamp("cancelled_at"), _uuid("cancelled_by"),
            sa.Column("cancellation_reason", sa.Text(), nullable=True), sa.Column("notes", sa.Text(), nullable=True),
            _timestamp("created_at", False), _uuid("created_by"), _timestamp("updated_at", False), _uuid("updated_by"),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"]),
            sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
            sa.ForeignKeyConstraint(["pharmacy_queue_id"], ["pharmacy_queue.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_dispenses_tenant_idempotency"),
            sa.CheckConstraint("status IN ('DRAFT','VALIDATED','RESERVED','READY_FOR_BILLING','BILLING_FAILED','READY_TO_CONFIRM','CONFIRMED','PARTIALLY_FULFILLED','OUTSIDE_FULFILLED','CANCELLED','EXPIRED')", name="ck_pharmacy_dispenses_status"),
        )
        for column in ("tenant_id", "facility_id", "pharmacy_location_id", "prescription_id", "visit_id", "patient_id", "pharmacy_queue_id", "status", "started_by", "ready_for_billing_by", "completed_by", "cancelled_by", "created_by", "updated_by"):
            op.create_index(f"ix_pharmacy_dispenses_{column}", "pharmacy_dispenses", [column])
        op.create_index("ix_pharmacy_dispenses_scope_status_created", "pharmacy_dispenses", ["tenant_id", "facility_id", "pharmacy_location_id", "status", "created_at"])

    if not inspector.has_table("pharmacy_dispense_items"):
        op.create_table(
            "pharmacy_dispense_items",
            _uuid("id", False), _uuid("dispense_id", False), _uuid("prescription_item_id", False),
            _uuid("prescribed_medicine_product_id"), _uuid("dispensed_medicine_product_id"), _uuid("prescribed_medicine_master_id"),
            sa.Column("prescribed_name_snapshot", sa.String(200), nullable=False), sa.Column("prescribed_strength_snapshot", sa.String(100)),
            sa.Column("prescribed_dosage_form_snapshot", sa.String(100)), sa.Column("prescribed_route_snapshot", sa.String(50)),
            sa.Column("prescribed_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("internal_requested_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("internal_confirmed_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("outside_purchase_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("substitution_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("substitution_reason", sa.Text()), _uuid("substitution_approved_by"), _timestamp("substitution_approved_at"),
            sa.Column("no_substitution_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
            _timestamp("created_at", False), _uuid("created_by"), _timestamp("updated_at", False), _uuid("updated_by"),
            sa.ForeignKeyConstraint(["dispense_id"], ["pharmacy_dispenses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["prescription_item_id"], ["prescription_items.id"]),
            sa.ForeignKeyConstraint(["prescribed_medicine_product_id"], ["medicine_products.id"]),
            sa.ForeignKeyConstraint(["dispensed_medicine_product_id"], ["medicine_products.id"]),
            sa.ForeignKeyConstraint(["prescribed_medicine_master_id"], ["medicine_master.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dispense_id", "prescription_item_id", name="uq_pharmacy_dispense_items_dispense_prescription"),
            sa.CheckConstraint("prescribed_quantity > 0", name="ck_pharmacy_dispense_items_prescribed_positive"),
            sa.CheckConstraint("internal_requested_quantity >= 0 AND internal_confirmed_quantity >= 0 AND outside_purchase_quantity >= 0", name="ck_pharmacy_dispense_items_quantities_nonnegative"),
            sa.CheckConstraint("internal_confirmed_quantity + outside_purchase_quantity <= prescribed_quantity", name="ck_pharmacy_dispense_items_fulfillment_limit"),
        )
        for column in ("dispense_id", "prescription_item_id", "prescribed_medicine_product_id", "dispensed_medicine_product_id", "prescribed_medicine_master_id", "status", "substitution_approved_by", "created_by", "updated_by"):
            op.create_index(f"ix_pharmacy_dispense_items_{column}", "pharmacy_dispense_items", [column])

    if not inspector.has_table("pharmacy_dispense_allocations"):
        op.create_table(
            "pharmacy_dispense_allocations",
            _uuid("id", False), _uuid("dispense_item_id", False), _uuid("tenant_id", False), _uuid("facility_id", False),
            _uuid("pharmacy_location_id", False), _uuid("inventory_batch_id", False),
            sa.Column("allocated_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("confirmed_dispensed_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("allocation_source", sa.String(30), nullable=False, server_default="FEFO"),
            sa.Column("override_reason", sa.Text()), _uuid("override_by"), _uuid("stock_transaction_id"),
            sa.Column("status", sa.String(30), nullable=False, server_default="PROPOSED"),
            _timestamp("created_at", False), _timestamp("updated_at", False),
            sa.ForeignKeyConstraint(["dispense_item_id"], ["pharmacy_dispense_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
            sa.ForeignKeyConstraint(["stock_transaction_id"], ["stock_transactions.id"]),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("dispense_item_id", "inventory_batch_id", name="uq_pharmacy_allocations_item_batch"),
            sa.UniqueConstraint("stock_transaction_id", name="uq_pharmacy_allocations_stock_transaction"),
            sa.CheckConstraint("allocated_quantity > 0", name="ck_pharmacy_allocations_allocated_positive"),
            sa.CheckConstraint("confirmed_dispensed_quantity >= 0 AND confirmed_dispensed_quantity <= allocated_quantity", name="ck_pharmacy_allocations_confirmed_range"),
        )
        for column in ("dispense_item_id", "tenant_id", "facility_id", "pharmacy_location_id", "inventory_batch_id", "override_by", "stock_transaction_id", "status"):
            op.create_index(f"ix_pharmacy_dispense_allocations_{column}", "pharmacy_dispense_allocations", [column])

    if not inspector.has_table("pharmacy_stock_reservations"):
        op.create_table(
            "pharmacy_stock_reservations",
            _uuid("id", False), _uuid("tenant_id", False), _uuid("facility_id", False), _uuid("pharmacy_location_id", False),
            _uuid("dispense_id", False), _uuid("dispense_item_id", False), _uuid("inventory_batch_id", False),
            sa.Column("quantity", sa.Numeric(12, 3), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            _timestamp("reserved_at", False), _uuid("reserved_by"), _timestamp("expires_at", False), _timestamp("consumed_at"), _uuid("consumed_by"),
            _timestamp("released_at"), _uuid("released_by"), sa.Column("release_reason", sa.Text()), _timestamp("created_at", False), _timestamp("updated_at", False),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.ForeignKeyConstraint(["dispense_id"], ["pharmacy_dispenses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dispense_item_id"], ["pharmacy_dispense_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint("quantity > 0", name="ck_pharmacy_reservations_quantity_positive"),
            sa.CheckConstraint("status IN ('ACTIVE','CONSUMED','RELEASED','EXPIRED','CANCELLED')", name="ck_pharmacy_reservations_status"),
        )
        for column in ("tenant_id", "facility_id", "pharmacy_location_id", "dispense_id", "dispense_item_id", "inventory_batch_id", "status", "reserved_by", "consumed_by", "released_by", "expires_at"):
            op.create_index(f"ix_pharmacy_stock_reservations_{column}", "pharmacy_stock_reservations", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    for table in ("pharmacy_stock_reservations", "pharmacy_dispense_allocations", "pharmacy_dispense_items", "pharmacy_dispenses"):
        if inspector.has_table(table):
            op.drop_table(table)
    if inspector.has_table("prescriptions") and "version" in {column["name"] for column in inspector.get_columns("prescriptions")}:
        op.drop_column("prescriptions", "version")
    if inspector.has_table("prescription_items"):
        columns = {column["name"] for column in inspector.get_columns("prescription_items")}
        if "no_substitution_reason" in columns:
            op.drop_column("prescription_items", "no_substitution_reason")
        if "no_substitution" in columns:
            op.drop_column("prescription_items", "no_substitution")
