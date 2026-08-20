"""Add department_id to queue_tokens and visits; add nurse_departments table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only run in tenant schemas — skip for public
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    # Add department_id to queue_tokens
    op.add_column(
        "queue_tokens",
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_queue_tokens_department",
        "queue_tokens", "departments",
        ["department_id"], ["id"],
    )
    op.create_index("ix_queue_tokens_department_id", "queue_tokens", ["department_id"])

    # Add department_id to visits
    op.add_column(
        "visits",
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_visits_department",
        "visits", "departments",
        ["department_id"], ["id"],
    )
    op.create_index("ix_visits_department_id", "visits", ["department_id"])

    # Create nurse_departments table
    op.create_table(
        "nurse_departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nurse_departments_user_id", "nurse_departments", ["user_id"])
    op.create_index("ix_nurse_departments_department_id", "nurse_departments", ["department_id"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.drop_table("nurse_departments")
    op.drop_constraint("fk_visits_department", "visits", type_="foreignkey")
    op.drop_index("ix_visits_department_id", "visits")
    op.drop_column("visits", "department_id")
    op.drop_constraint("fk_queue_tokens_department", "queue_tokens", type_="foreignkey")
    op.drop_index("ix_queue_tokens_department_id", "queue_tokens")
    op.drop_column("queue_tokens", "department_id")
