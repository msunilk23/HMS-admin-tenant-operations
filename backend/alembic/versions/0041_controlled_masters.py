"""Add controlled ICD-10 and medicine master tables and prescription references."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("icd10_codes"):
        op.create_table(
            "icd10_codes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"),
        )
        op.create_index("ix_icd10_codes_code", "icd10_codes", ["code"])
        op.create_index("ix_icd10_codes_is_active", "icd10_codes", ["is_active"])
    if not sa.inspect(bind).has_table("medicine_master"):
        op.create_table(
            "medicine_master",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("generic_name", sa.String(200), nullable=False),
            sa.Column("brand_name", sa.String(200), nullable=True),
            sa.Column("strength", sa.String(100), nullable=True),
            sa.Column("dosage_form", sa.String(100), nullable=True),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_medicine_master_generic_name", "medicine_master", ["generic_name"])
        op.create_index("ix_medicine_master_brand_name", "medicine_master", ["brand_name"])
        op.create_index("ix_medicine_master_is_active", "medicine_master", ["is_active"])
    if not sa.inspect(bind).has_table("prescription_items"):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("prescription_items")}
    if "medicine_master_id" not in columns:
        op.add_column("prescription_items", sa.Column("medicine_master_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index("ix_prescription_items_medicine_master_id", "prescription_items", ["medicine_master_id"])
        op.create_foreign_key("fk_prescription_items_medicine_master", "prescription_items", "medicine_master", ["medicine_master_id"], ["id"])
    if "dosage_form" not in columns:
        op.add_column("prescription_items", sa.Column("dosage_form", sa.String(100), nullable=True))
    if "timing_relative_to_food" not in columns:
        op.add_column("prescription_items", sa.Column("timing_relative_to_food", sa.String(50), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if sa.inspect(bind).has_table("prescription_items"):
        op.drop_constraint("fk_prescription_items_medicine_master", "prescription_items", type_="foreignkey")
        op.drop_index("ix_prescription_items_medicine_master_id", table_name="prescription_items")
        op.drop_column("prescription_items", "timing_relative_to_food")
        op.drop_column("prescription_items", "dosage_form")
        op.drop_column("prescription_items", "medicine_master_id")
    op.drop_index("ix_medicine_master_is_active", table_name="medicine_master")
    op.drop_index("ix_medicine_master_brand_name", table_name="medicine_master")
    op.drop_index("ix_medicine_master_generic_name", table_name="medicine_master")
    op.drop_table("medicine_master")
    op.drop_index("ix_icd10_codes_is_active", table_name="icd10_codes")
    op.drop_index("ix_icd10_codes_code", table_name="icd10_codes")
    op.drop_table("icd10_codes")
