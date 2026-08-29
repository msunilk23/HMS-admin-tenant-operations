"""
P30 - Patient Return + Supplier Return tables

Adds tables for:
- patient_returns and patient_return_items
- supplier_returns and supplier_return_items
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def _is_tenant_schema(bind) -> bool:
    """Check if we're in a tenant schema (not public schema)."""
    return bind.execute(text("SELECT current_schema()")).scalar() != "public"


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return
    
    inspector = sa.inspect(bind)

    # Patient Returns table (with idempotent create)
    if not inspector.has_table("patient_returns"):
        op.create_table(
            "patient_returns",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("pharmacy_location_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dispense_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="REQUESTED"),
            sa.Column("reference_key", sa.String(100), nullable=False),
            sa.Column("return_reason", sa.Text(), nullable=False),
            sa.Column("package_condition", sa.String(100), nullable=True),
            sa.Column("total_return_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("total_return_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("restockable_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("non_restockable_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("validated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refunded_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
            sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
            sa.ForeignKeyConstraint(["dispense_id"], ["pharmacy_dispenses.id"]),
            sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "reference_key", name="uq_patient_returns_tenant_reference"),
            sa.CheckConstraint(
                "status IN ('REQUESTED', 'VALIDATED', 'ACCEPTED', 'REJECTED', 'REFUND_PENDING', 'REFUNDED', 'RESTOCKED', 'NON_RESTOCKABLE')",
                name="ck_patient_returns_status",
            ),
        )
        op.create_index("ix_patient_returns_tenant_id", "patient_returns", ["tenant_id"])
        op.create_index("ix_patient_returns_facility_id", "patient_returns", ["facility_id"])
        op.create_index("ix_patient_returns_patient_id", "patient_returns", ["patient_id"])
        op.create_index("ix_patient_returns_visit_id", "patient_returns", ["visit_id"])
        op.create_index("ix_patient_returns_dispense_id", "patient_returns", ["dispense_id"])
        op.create_index("ix_patient_returns_status", "patient_returns", ["status"])
        op.create_index("ix_patient_returns_reference_key", "patient_returns", ["reference_key"])

    # Patient Return Items table
    if not inspector.has_table("patient_return_items"):
        op.create_table(
            "patient_return_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("return_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dispense_item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("medicine_product_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("inventory_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("prescribed_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("returned_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("original_unit_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("return_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="PENDING_VALIDATION"),
            sa.Column("restockable", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("non_restockable_reason", sa.Text(), nullable=True),
            sa.Column("restock_ledger_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("validated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["return_id"], ["patient_returns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dispense_item_id"], ["pharmacy_dispense_items.id"]),
            sa.ForeignKeyConstraint(["medicine_product_id"], ["medicine_products.id"]),
            sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
            sa.ForeignKeyConstraint(["restock_ledger_transaction_id"], ["stock_transactions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("return_id", "dispense_item_id", name="uq_patient_return_items_return_dispense"),
            sa.CheckConstraint(
                "status IN ('PENDING_VALIDATION', 'ACCEPTED', 'REJECTED')",
                name="ck_patient_return_items_status",
            ),
        )
        op.create_index("ix_patient_return_items_return_id", "patient_return_items", ["return_id"])
        op.create_index("ix_patient_return_items_dispense_item_id", "patient_return_items", ["dispense_item_id"])

    # Supplier Returns table
    if not inspector.has_table("supplier_returns"):
        op.create_table(
            "supplier_returns",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("pharmacy_location_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("goods_receipt_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="REQUESTED"),
            sa.Column("reference_key", sa.String(100), nullable=False),
            sa.Column("return_reason", sa.Text(), nullable=False),
            sa.Column("total_return_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("total_return_value", sa.Numeric(12, 2), nullable=False),
            sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatched_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("received_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
            sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "reference_key", name="uq_supplier_returns_tenant_reference"),
            sa.CheckConstraint(
                "status IN ('REQUESTED', 'APPROVED', 'DISPATCHED', 'RECEIVED', 'REJECTED', 'CANCELLED')",
                name="ck_supplier_returns_status",
            ),
        )
        op.create_index("ix_supplier_returns_tenant_id", "supplier_returns", ["tenant_id"])
        op.create_index("ix_supplier_returns_facility_id", "supplier_returns", ["facility_id"])
        op.create_index("ix_supplier_returns_supplier_id", "supplier_returns", ["supplier_id"])
        op.create_index("ix_supplier_returns_status", "supplier_returns", ["status"])
        op.create_index("ix_supplier_returns_reference_key", "supplier_returns", ["reference_key"])

    # Supplier Return Items table
    if not inspector.has_table("supplier_return_items"):
        op.create_table(
            "supplier_return_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_return_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("goods_receipt_item_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("received_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("returned_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
            sa.Column("return_value", sa.Numeric(12, 2), nullable=False),
            sa.Column("stock_reduction_ledger_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["supplier_return_id"], ["supplier_returns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
            sa.ForeignKeyConstraint(["stock_reduction_ledger_id"], ["stock_transactions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("supplier_return_id", "inventory_batch_id", name="uq_supplier_return_items_return_batch"),
        )
        op.create_index("ix_supplier_return_items_supplier_return_id", "supplier_return_items", ["supplier_return_id"])
        op.create_index("ix_supplier_return_items_inventory_batch_id", "supplier_return_items", ["inventory_batch_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return
    
    inspector = sa.inspect(bind)

    # Drop supplier return items first (due to FKs)
    if inspector.has_table("supplier_return_items"):
        op.drop_index("ix_supplier_return_items_inventory_batch_id", table_name="supplier_return_items", if_exists=True)
        op.drop_index("ix_supplier_return_items_supplier_return_id", table_name="supplier_return_items", if_exists=True)
        op.drop_table("supplier_return_items")

    # Drop supplier returns
    if inspector.has_table("supplier_returns"):
        op.drop_index("ix_supplier_returns_reference_key", table_name="supplier_returns", if_exists=True)
        op.drop_index("ix_supplier_returns_status", table_name="supplier_returns", if_exists=True)
        op.drop_index("ix_supplier_returns_supplier_id", table_name="supplier_returns", if_exists=True)
        op.drop_index("ix_supplier_returns_facility_id", table_name="supplier_returns", if_exists=True)
        op.drop_index("ix_supplier_returns_tenant_id", table_name="supplier_returns", if_exists=True)
        op.drop_table("supplier_returns")

    # Drop patient return items first (due to FKs)
    if inspector.has_table("patient_return_items"):
        op.drop_index("ix_patient_return_items_dispense_item_id", table_name="patient_return_items", if_exists=True)
        op.drop_index("ix_patient_return_items_return_id", table_name="patient_return_items", if_exists=True)
        op.drop_table("patient_return_items")

    # Drop patient returns
    if inspector.has_table("patient_returns"):
        op.drop_index("ix_patient_returns_reference_key", table_name="patient_returns", if_exists=True)
        op.drop_index("ix_patient_returns_status", table_name="patient_returns", if_exists=True)
        op.drop_index("ix_patient_returns_dispense_id", table_name="patient_returns", if_exists=True)
        op.drop_index("ix_patient_returns_visit_id", table_name="patient_returns", if_exists=True)
        op.drop_index("ix_patient_returns_patient_id", table_name="patient_returns", if_exists=True)
        op.drop_index("ix_patient_returns_facility_id", table_name="patient_returns", if_exists=True)
        op.drop_index("ix_patient_returns_tenant_id", table_name="patient_returns", if_exists=True)
        op.drop_table("patient_returns")
