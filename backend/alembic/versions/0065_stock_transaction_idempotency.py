"""Prevent duplicate stock movements for the same source reference."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("stock_transactions"):
        constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("stock_transactions")}
        if "uq_stock_transactions_source_type" not in constraints:
            op.create_unique_constraint(
                "uq_stock_transactions_source_type",
                "stock_transactions",
                ["reference_type", "reference_id", "transaction_type"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("stock_transactions"):
        constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("stock_transactions")}
        if "uq_stock_transactions_source_type" in constraints:
            op.drop_constraint("uq_stock_transactions_source_type", "stock_transactions", type_="unique")