"""Create tenant-scoped goods receipt header and item tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("goods_receipts"):
        op.create_table(
            "goods_receipts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("grn_number", sa.String(40), nullable=False),
            sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_invoice_number", sa.String(100), nullable=True),
            sa.Column("supplier_invoice_date", sa.Date(), nullable=True),
            sa.Column("received_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column("received_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
            sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], name="fk_goods_receipts_purchase_order"),
            sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_goods_receipts_supplier"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("grn_number", name="uq_goods_receipts_grn_number"),
        )
        op.create_index("ix_goods_receipts_grn_number", "goods_receipts", ["grn_number"])
        op.create_index("ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"])
        op.create_index("ix_goods_receipts_supplier_id", "goods_receipts", ["supplier_id"])
        op.create_index("ix_goods_receipts_received_date", "goods_receipts", ["received_date"])
        op.create_index("ix_goods_receipts_status", "goods_receipts", ["status"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("goods_receipt_items"):
        op.create_table(
            "goods_receipt_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("goods_receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("purchase_order_item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("medicine_product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("batch_number", sa.String(100), nullable=True),
            sa.Column("manufacturing_date", sa.Date(), nullable=True),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("received_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("free_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("purchase_rate", sa.Numeric(12, 2), nullable=False),
            sa.Column("mrp", sa.Numeric(12, 2), nullable=True),
            sa.Column("gst_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("taxable_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("line_total", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("receiving_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE", name="fk_goods_receipt_items_receipt"),
            sa.ForeignKeyConstraint(["purchase_order_item_id"], ["purchase_order_items.id"], name="fk_goods_receipt_items_po_item"),
            sa.ForeignKeyConstraint(["medicine_product_id"], ["medicine_products.id"], name="fk_goods_receipt_items_product"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_goods_receipt_items_goods_receipt_id", "goods_receipt_items", ["goods_receipt_id"])
        op.create_index("ix_goods_receipt_items_purchase_order_item_id", "goods_receipt_items", ["purchase_order_item_id"])
        op.create_index("ix_goods_receipt_items_medicine_product_id", "goods_receipt_items", ["medicine_product_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("goods_receipt_items"):
        op.drop_index("ix_goods_receipt_items_medicine_product_id", table_name="goods_receipt_items")
        op.drop_index("ix_goods_receipt_items_purchase_order_item_id", table_name="goods_receipt_items")
        op.drop_index("ix_goods_receipt_items_goods_receipt_id", table_name="goods_receipt_items")
        op.drop_table("goods_receipt_items")
    if inspector.has_table("goods_receipts"):
        op.drop_index("ix_goods_receipts_status", table_name="goods_receipts")
        op.drop_index("ix_goods_receipts_received_date", table_name="goods_receipts")
        op.drop_index("ix_goods_receipts_supplier_id", table_name="goods_receipts")
        op.drop_index("ix_goods_receipts_purchase_order_id", table_name="goods_receipts")
        op.drop_index("ix_goods_receipts_grn_number", table_name="goods_receipts")
        op.drop_table("goods_receipts")
