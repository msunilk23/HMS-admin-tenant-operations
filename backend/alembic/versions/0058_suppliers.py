"""Create the tenant-scoped supplier master."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if sa.inspect(bind).has_table("suppliers"):
        return

    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_code", sa.String(100), nullable=False),
        sa.Column("supplier_name", sa.String(200), nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("drug_license_no", sa.String(100), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(100), nullable=True, server_default="India"),
        sa.Column("contact_person", sa.String(200), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("payment_terms", sa.String(200), nullable=True),
        sa.Column("credit_days", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_code", name="uq_suppliers_supplier_code"),
    )
    op.create_index("ix_suppliers_supplier_code", "suppliers", ["supplier_code"])
    op.create_index("ix_suppliers_supplier_name", "suppliers", ["supplier_name"])
    op.create_index("ix_suppliers_gstin", "suppliers", ["gstin"])
    op.create_index("ix_suppliers_email", "suppliers", ["email"])
    op.create_index("ix_suppliers_is_active", "suppliers", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("suppliers"):
        return

    op.drop_index("ix_suppliers_is_active", table_name="suppliers")
    op.drop_index("ix_suppliers_email", table_name="suppliers")
    op.drop_index("ix_suppliers_gstin", table_name="suppliers")
    op.drop_index("ix_suppliers_supplier_name", table_name="suppliers")
    op.drop_index("ix_suppliers_supplier_code", table_name="suppliers")
    op.drop_table("suppliers")
