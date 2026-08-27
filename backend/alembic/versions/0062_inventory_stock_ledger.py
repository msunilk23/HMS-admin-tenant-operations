"""Create P27 pharmacy locations, inventory batches, and stock ledger tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()" )).scalar() == "public":
        return
    inspector = sa.inspect(bind)

    if not inspector.has_table("pharmacy_locations"):
        op.create_table(
            "pharmacy_locations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("location_code", sa.String(50), nullable=False),
            sa.Column("location_name", sa.String(200), nullable=False),
            sa.Column("location_type", sa.String(50), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "facility_id", "location_code", name="uq_pharmacy_locations_tenant_facility_code"),
        )
        op.create_index("ix_pharmacy_locations_tenant_id", "pharmacy_locations", ["tenant_id"])
        op.create_index("ix_pharmacy_locations_facility_id", "pharmacy_locations", ["facility_id"])
        op.create_index("ix_pharmacy_locations_location_code", "pharmacy_locations", ["location_code"])
        op.create_index("ix_pharmacy_locations_location_type", "pharmacy_locations", ["location_type"])
        op.create_index("ix_pharmacy_locations_active", "pharmacy_locations", ["active"])
        op.create_index("ix_pharmacy_locations_created_by", "pharmacy_locations", ["created_by"])
        op.create_index("ix_pharmacy_locations_updated_by", "pharmacy_locations", ["updated_by"])

    if not inspector.has_table("inventory_batches"):
        op.create_table(
            "inventory_batches",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("pharmacy_location_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("medicine_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("batch_number", sa.String(100), nullable=False),
            sa.Column("manufacturing_date", sa.Date(), nullable=True),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("purchase_rate", sa.Numeric(12, 2), nullable=False),
            sa.Column("mrp", sa.Numeric(12, 2), nullable=True),
            sa.Column("received_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("available_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("reserved_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("goods_receipt_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("goods_receipt_item_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "facility_id", "pharmacy_location_id", "medicine_id", "batch_number", name="uq_inventory_batches_tenant_location_medicine_batch"),
            sa.UniqueConstraint("goods_receipt_item_id", name="uq_inventory_batches_goods_receipt_item"),
        )
        for column in ("tenant_id", "facility_id", "pharmacy_location_id", "medicine_id", "batch_number", "manufacturing_date", "expiry_date", "supplier_id", "goods_receipt_id", "goods_receipt_item_id", "status", "created_by", "updated_by"):
            op.create_index(f"ix_inventory_batches_{column}", "inventory_batches", [column])

    if not inspector.has_table("stock_transactions"):
        op.create_table(
            "stock_transactions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("pharmacy_location_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("medicine_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("transaction_type", sa.String(50), nullable=False),
            sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("previous_balance", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("new_balance", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("reference_type", sa.String(50), nullable=False),
            sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("reason", sa.String(255), nullable=True),
            sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("tenant_id", "facility_id", "pharmacy_location_id", "medicine_id", "inventory_batch_id", "transaction_type", "reference_type", "reference_id", "performed_by"):
            op.create_index(f"ix_stock_transactions_{column}", "stock_transactions", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("stock_transactions"):
        for column in ("performed_by", "reference_id", "reference_type", "transaction_type", "inventory_batch_id", "medicine_id", "pharmacy_location_id", "facility_id", "tenant_id"):
            op.drop_index(f"ix_stock_transactions_{column}", table_name="stock_transactions")
        op.drop_table("stock_transactions")
    if inspector.has_table("inventory_batches"):
        for column in ("updated_by", "created_by", "status", "goods_receipt_item_id", "goods_receipt_id", "supplier_id", "expiry_date", "manufacturing_date", "batch_number", "medicine_id", "pharmacy_location_id", "facility_id", "tenant_id"):
            op.drop_index(f"ix_inventory_batches_{column}", table_name="inventory_batches")
        op.drop_table("inventory_batches")
    if inspector.has_table("pharmacy_locations"):
        for column in ("updated_by", "created_by", "active", "location_type", "location_code", "facility_id", "tenant_id"):
            op.drop_index(f"ix_pharmacy_locations_{column}", table_name="pharmacy_locations")
        op.drop_table("pharmacy_locations")