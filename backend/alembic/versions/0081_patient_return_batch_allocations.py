"""Add authoritative explicit patient return batch allocations.

Existing single-batch return items retain their legacy inventory_batch_id. When a
valid legacy batch is present, upgrade creates one authoritative allocation row
without rewriting the historic return item.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def _is_tenant_schema(bind) -> bool:
    return bind.execute(text("SELECT current_schema()")).scalar() != "public"


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind):
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("patient_return_batch_allocations"):
        op.create_table(
            "patient_return_batch_allocations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("patient_return_item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("dispense_allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inventory_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("returned_quantity", sa.Numeric(12, 3), nullable=False),
            sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
            sa.Column("stock_ledger_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["patient_return_item_id"], ["patient_return_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dispense_allocation_id"], ["pharmacy_dispense_allocations.id"]),
            sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
            sa.ForeignKeyConstraint(["stock_ledger_transaction_id"], ["stock_transactions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("patient_return_item_id", "dispense_allocation_id", name="uq_patient_return_batch_allocation_source"),
            sa.UniqueConstraint("stock_ledger_transaction_id", name="uq_patient_return_batch_allocation_ledger"),
            sa.CheckConstraint("returned_quantity > 0", name="ck_patient_return_batch_allocation_positive"),
        )
        op.create_index("ix_patient_return_batch_allocations_tenant_id", "patient_return_batch_allocations", ["tenant_id"])
        op.create_index("ix_patient_return_batch_allocations_return_item_id", "patient_return_batch_allocations", ["patient_return_item_id"])
        op.create_index("ix_patient_return_batch_allocations_dispense_allocation_id", "patient_return_batch_allocations", ["dispense_allocation_id"])
        op.create_index("ix_patient_return_batch_allocations_inventory_batch_id", "patient_return_batch_allocations", ["inventory_batch_id"])

    if not inspector.has_table("patient_return_items") or not inspector.has_table("pharmacy_dispense_allocations"):
        return

    # Preserve legacy history by backfilling only rows with an unambiguous
    # matching original allocation. Ambiguous rows stay legacy-only for review.
    bind.execute(text("""
        INSERT INTO patient_return_batch_allocations
            (id, tenant_id, patient_return_item_id, dispense_allocation_id,
             inventory_batch_id, returned_quantity, unit_cost, created_at, updated_at)
        SELECT gen_random_uuid(), pr.tenant_id, pri.id, pda.id,
               pri.inventory_batch_id, pri.returned_quantity, ib.purchase_rate, now(), now()
        FROM patient_return_items pri
        JOIN patient_returns pr ON pr.id = pri.return_id
        JOIN pharmacy_dispense_allocations pda
          ON pda.dispense_item_id = pri.dispense_item_id
         AND pda.inventory_batch_id = pri.inventory_batch_id
        JOIN inventory_batches ib ON ib.id = pri.inventory_batch_id
        LEFT JOIN patient_return_batch_allocations existing
          ON existing.patient_return_item_id = pri.id
         AND existing.dispense_allocation_id = pda.id
        WHERE pri.inventory_batch_id IS NOT NULL
          AND existing.id IS NULL
          AND pda.confirmed_dispensed_quantity >= pri.returned_quantity
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant_schema(bind) or not sa.inspect(bind).has_table("patient_return_batch_allocations"):
        return
    op.drop_table("patient_return_batch_allocations")
