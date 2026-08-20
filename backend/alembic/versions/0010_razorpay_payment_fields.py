"""Add razorpay_order_id / razorpay_payment_id to invoices;
set consultation_fee = 500 for existing doctors that still have the default 0.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.add_column("invoices", sa.Column("razorpay_order_id", sa.String(120), nullable=True))
    op.add_column("invoices", sa.Column("razorpay_payment_id", sa.String(120), nullable=True))

    # Back-fill: any doctor whose consultation_fee is still 0 → ₹500 default
    op.execute(text("UPDATE doctors SET consultation_fee = 500 WHERE consultation_fee = 0"))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_column("invoices", "razorpay_payment_id")
    op.drop_column("invoices", "razorpay_order_id")
