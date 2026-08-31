"""Create tenant-scoped purchase order header and item tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("purchase_orders"):
        op.create_table(
            "purchase_orders",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("po_number", sa.String(40), nullable=False),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("po_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column("required_by_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
            sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_purchase_orders_supplier"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        )
        op.create_index("ix_purchase_orders_po_number", "purchase_orders", ["po_number"])
        op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
        op.create_index("ix_purchase_orders_po_date", "purchase_orders", ["po_date"])
        op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("purchase_order_items"):
        op.create_table(
            "purchase_order_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("medicine_product_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("ordered_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("free_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("unit_of_measure", sa.String(50), nullable=False),
            sa.Column("unit_purchase_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("mrp", sa.Numeric(12, 2), nullable=True),
            sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("gst_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("taxable_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("line_total", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("received_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE", name="fk_purchase_order_items_order"),
            sa.ForeignKeyConstraint(["medicine_product_id"], ["medicine_products.id"], name="fk_purchase_order_items_product"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_purchase_order_items_purchase_order_id", "purchase_order_items", ["purchase_order_id"])
        op.create_index("ix_purchase_order_items_medicine_product_id", "purchase_order_items", ["medicine_product_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("purchase_order_items"):
        op.drop_index("ix_purchase_order_items_medicine_product_id", table_name="purchase_order_items")
        op.drop_index("ix_purchase_order_items_purchase_order_id", table_name="purchase_order_items")
        op.drop_table("purchase_order_items")
    if inspector.has_table("purchase_orders"):
        op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
        op.drop_index("ix_purchase_orders_po_date", table_name="purchase_orders")
        op.drop_index("ix_purchase_orders_supplier_id", table_name="purchase_orders")
        op.drop_index("ix_purchase_orders_po_number", table_name="purchase_orders")
        op.drop_table("purchase_orders")
