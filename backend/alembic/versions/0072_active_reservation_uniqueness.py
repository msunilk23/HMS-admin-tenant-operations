"""Prevent duplicate active reservations for one dispense item and batch."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("pharmacy_stock_reservations"):
        indexes = {index["name"] for index in inspector.get_indexes("pharmacy_stock_reservations")}
        if "uq_pharmacy_reservations_active_item_batch" not in indexes:
            op.create_index(
                "uq_pharmacy_reservations_active_item_batch",
                "pharmacy_stock_reservations",
                ["dispense_item_id", "inventory_batch_id"],
                unique=True,
                postgresql_where=text("status = 'ACTIVE'"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("pharmacy_stock_reservations"):
        indexes = {index["name"] for index in inspector.get_indexes("pharmacy_stock_reservations")}
        if "uq_pharmacy_reservations_active_item_batch" in indexes:
            op.drop_index("uq_pharmacy_reservations_active_item_batch", table_name="pharmacy_stock_reservations")