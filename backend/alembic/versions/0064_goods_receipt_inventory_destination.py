"""Add optional GRN inventory destination fields for P27 posting."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("goods_receipts"):
        return
    columns = {column["name"] for column in inspector.get_columns("goods_receipts")}
    if "facility_id" not in columns:
        op.add_column("goods_receipts", sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index("ix_goods_receipts_facility_id", "goods_receipts", ["facility_id"])
    if "pharmacy_location_id" not in columns:
        op.add_column("goods_receipts", sa.Column("pharmacy_location_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index("ix_goods_receipts_pharmacy_location_id", "goods_receipts", ["pharmacy_location_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("goods_receipts"):
        return
    columns = {column["name"] for column in inspector.get_columns("goods_receipts")}
    if "pharmacy_location_id" in columns:
        op.drop_index("ix_goods_receipts_pharmacy_location_id", table_name="goods_receipts")
        op.drop_column("goods_receipts", "pharmacy_location_id")
    if "facility_id" in columns:
        op.drop_index("ix_goods_receipts_facility_id", table_name="goods_receipts")
        op.drop_column("goods_receipts", "facility_id")