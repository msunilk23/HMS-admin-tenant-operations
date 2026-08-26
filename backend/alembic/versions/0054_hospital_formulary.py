"""Create the tenant-scoped hospital formulary."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if sa.inspect(bind).has_table("hospital_formulary"):
        return

    op.create_table(
        "hospital_formulary",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("medicine_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_prescribable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["medicine_product_id"], ["medicine_products.id"], name="fk_hospital_formulary_medicine_product"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name="fk_hospital_formulary_department"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("medicine_product_id", "department_id", name="uq_hospital_formulary_product_department"),
    )
    op.create_index("ix_hospital_formulary_medicine_product_id", "hospital_formulary", ["medicine_product_id"])
    op.create_index("ix_hospital_formulary_department_id", "hospital_formulary", ["department_id"])
    op.create_index("ix_hospital_formulary_is_approved", "hospital_formulary", ["is_approved"])
    op.create_index("ix_hospital_formulary_is_prescribable", "hospital_formulary", ["is_prescribable"])
    op.create_index("ix_hospital_formulary_effective_date", "hospital_formulary", ["effective_date"])
    op.create_index("ix_hospital_formulary_is_active", "hospital_formulary", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("hospital_formulary"):
        return

    op.drop_index("ix_hospital_formulary_is_active", table_name="hospital_formulary")
    op.drop_index("ix_hospital_formulary_effective_date", table_name="hospital_formulary")
    op.drop_index("ix_hospital_formulary_is_prescribable", table_name="hospital_formulary")
    op.drop_index("ix_hospital_formulary_is_approved", table_name="hospital_formulary")
    op.drop_index("ix_hospital_formulary_department_id", table_name="hospital_formulary")
    op.drop_index("ix_hospital_formulary_medicine_product_id", table_name="hospital_formulary")
    op.drop_table("hospital_formulary")
