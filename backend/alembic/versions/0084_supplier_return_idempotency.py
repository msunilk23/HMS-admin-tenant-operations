"""Add supplier return idempotency fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("supplier_returns"):
        return
    columns = {column["name"] for column in inspector.get_columns("supplier_returns")}
    if "idempotency_key" not in columns:
        op.add_column("supplier_returns", sa.Column("idempotency_key", sa.String(100), nullable=True))
    if "request_hash" not in columns:
        op.add_column("supplier_returns", sa.Column("request_hash", sa.String(64), nullable=True))
    names = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("supplier_returns")}
    if "uq_supplier_returns_tenant_idempotency" not in names:
        op.create_unique_constraint("uq_supplier_returns_tenant_idempotency", "supplier_returns", ["tenant_id", "idempotency_key"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public" or not sa.inspect(bind).has_table("supplier_returns"):
        return
    inspector = sa.inspect(bind)
    names = {item.get("name") for item in inspector.get_unique_constraints("supplier_returns")}
    if "uq_supplier_returns_tenant_idempotency" in names:
        op.drop_constraint("uq_supplier_returns_tenant_idempotency", "supplier_returns", type_="unique")
    columns = {column["name"] for column in inspector.get_columns("supplier_returns")}
    if "request_hash" in columns:
        op.drop_column("supplier_returns", "request_hash")
    if "idempotency_key" in columns:
        op.drop_column("supplier_returns", "idempotency_key")