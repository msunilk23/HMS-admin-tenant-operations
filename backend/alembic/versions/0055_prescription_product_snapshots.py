"""Add medicine product references and prescription snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("medicine_product_id", postgresql.UUID(as_uuid=True), "ix_prescription_items_medicine_product_id"),
    ("generic_name_snapshot", sa.String(200), None),
    ("brand_name_snapshot", sa.String(200), None),
    ("strength_snapshot", sa.String(100), None),
    ("dosage_form_snapshot", sa.String(100), None),
    ("route_snapshot", sa.String(50), None),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("prescription_items"):
        return
    columns = {column["name"] for column in inspector.get_columns("prescription_items")}
    for name, column_type, index_name in _COLUMNS:
        if name in columns:
            continue
        op.add_column("prescription_items", sa.Column(name, column_type, nullable=True))
        if index_name:
            op.create_index(index_name, "prescription_items", [name])
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("prescription_items")}
    if "fk_prescription_items_medicine_product" not in foreign_keys:
        op.create_foreign_key(
            "fk_prescription_items_medicine_product",
            "prescription_items",
            "medicine_products",
            ["medicine_product_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("prescription_items"):
        return
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("prescription_items")}
    if "fk_prescription_items_medicine_product" in foreign_keys:
        op.drop_constraint("fk_prescription_items_medicine_product", "prescription_items", type_="foreignkey")
    columns = {column["name"] for column in inspector.get_columns("prescription_items")}
    for name, _, index_name in reversed(_COLUMNS):
        if name not in columns:
            continue
        if index_name:
            op.drop_index(index_name, table_name="prescription_items")
        op.drop_column("prescription_items", name)