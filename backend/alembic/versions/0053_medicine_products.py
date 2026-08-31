"""Create the tenant-scoped medicine product master."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if sa.inspect(bind).has_table("medicine_products"):
        return

    op.create_table(
        "medicine_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("generic_medicine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_name", sa.String(200), nullable=True),
        sa.Column("strength", sa.String(100), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("dosage_form_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("default_route_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("manufacturer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("composition", sa.Text(), nullable=True),
        sa.Column("hsn_code", sa.String(20), nullable=True),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("schedule_category", sa.String(50), nullable=True),
        sa.Column("is_controlled_drug", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_prescription", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generic_medicine_id"], ["generic_medicines.id"], name="fk_medicine_products_generic_medicine"),
        sa.ForeignKeyConstraint(["dosage_form_id"], ["dosage_forms.id"], name="fk_medicine_products_dosage_form"),
        sa.ForeignKeyConstraint(["default_route_id"], ["routes.id"], name="fk_medicine_products_default_route"),
        sa.ForeignKeyConstraint(["manufacturer_id"], ["manufacturers.id"], name="fk_medicine_products_manufacturer"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_medicine_products_code"),
    )
    op.create_index("ix_medicine_products_code", "medicine_products", ["code"])
    op.create_index("ix_medicine_products_brand_name", "medicine_products", ["brand_name"])
    op.create_index("ix_medicine_products_generic_medicine_id", "medicine_products", ["generic_medicine_id"])
    op.create_index("ix_medicine_products_dosage_form_id", "medicine_products", ["dosage_form_id"])
    op.create_index("ix_medicine_products_default_route_id", "medicine_products", ["default_route_id"])
    op.create_index("ix_medicine_products_manufacturer_id", "medicine_products", ["manufacturer_id"])
    op.create_index("ix_medicine_products_is_active", "medicine_products", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("medicine_products"):
        return

    op.drop_index("ix_medicine_products_is_active", table_name="medicine_products")
    op.drop_index("ix_medicine_products_manufacturer_id", table_name="medicine_products")
    op.drop_index("ix_medicine_products_default_route_id", table_name="medicine_products")
    op.drop_index("ix_medicine_products_dosage_form_id", table_name="medicine_products")
    op.drop_index("ix_medicine_products_generic_medicine_id", table_name="medicine_products")
    op.drop_index("ix_medicine_products_brand_name", table_name="medicine_products")
    op.drop_index("ix_medicine_products_code", table_name="medicine_products")
    op.drop_table("medicine_products")
