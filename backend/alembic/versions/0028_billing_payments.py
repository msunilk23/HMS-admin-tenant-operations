"""Add invoice balances and payment records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.add_column("invoices", sa.Column("paid_amount", sa.Numeric(10, 2), nullable=False, server_default="0"))
    op.add_column("invoices", sa.Column("receipt_number", sa.String(40), nullable=True))
    op.execute("UPDATE invoices SET paid_amount = total WHERE status = 'paid'")
    op.create_unique_constraint("uq_invoices_receipt_number", "invoices", ["receipt_number"])
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="captured"),
        sa.Column("transaction_reference", sa.String(120), nullable=True),
        sa.Column("gateway", sa.String(30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_reference"),
    )
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_table(
        "refunds",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refunds_invoice_id", "refunds", ["invoice_id"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.drop_index("ix_refunds_invoice_id", table_name="refunds")
    op.drop_table("refunds")
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_table("payments")
    op.drop_constraint("uq_invoices_receipt_number", "invoices", type_="unique")
    op.drop_column("invoices", "receipt_number")
    op.drop_column("invoices", "paid_amount")