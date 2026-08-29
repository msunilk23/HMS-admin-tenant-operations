"""Create lab_test_master table for controlled lab test catalog."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    
    inspector = sa.inspect(bind)
    if inspector.has_table("lab_test_master"):
        # Table already exists, ensure indexes exist
        table_indexes = {idx.name for idx in inspector.get_indexes("lab_test_master")}
        
        if "ix_lab_test_master_code" not in table_indexes:
            op.create_index("ix_lab_test_master_code", "lab_test_master", ["code"])
        if "ix_lab_test_master_name" not in table_indexes:
            op.create_index("ix_lab_test_master_name", "lab_test_master", ["name"])
        if "ix_lab_test_master_category" not in table_indexes:
            op.create_index("ix_lab_test_master_category", "lab_test_master", ["category"])
        if "ix_lab_test_master_is_active" not in table_indexes:
            op.create_index("ix_lab_test_master_is_active", "lab_test_master", ["is_active"])
        return

    op.create_table(
        "lab_test_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False, index=True),
        sa.Column("category", sa.String(100), nullable=True, index=True),
        sa.Column("sample_type", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("reference_range", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lab_test_master_code", "lab_test_master", ["code"])
    op.create_index("ix_lab_test_master_name", "lab_test_master", ["name"])
    op.create_index("ix_lab_test_master_category", "lab_test_master", ["category"])
    op.create_index("ix_lab_test_master_is_active", "lab_test_master", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    if not sa.inspect(bind).has_table("lab_test_master"):
        return

    op.drop_index("ix_lab_test_master_is_active", table_name="lab_test_master")
    op.drop_index("ix_lab_test_master_category", table_name="lab_test_master")
    op.drop_index("ix_lab_test_master_name", table_name="lab_test_master")
    op.drop_index("ix_lab_test_master_code", table_name="lab_test_master")
    op.drop_table("lab_test_master")
