"""Add department_id to appointments."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("appointments")}

    if "department_id" not in existing_columns:
        op.add_column(
            "appointments",
            sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    existing_fk_names = {fk.get("name") for fk in inspector.get_foreign_keys("appointments")}
    if "fk_appointments_department" not in existing_fk_names:
        op.create_foreign_key(
            "fk_appointments_department",
            "appointments",
            "departments",
            ["department_id"],
            ["id"],
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("appointments")}
    if "ix_appointments_department_id" not in existing_indexes:
        op.create_index("ix_appointments_department_id", "appointments", ["department_id"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("appointments")}
    if "ix_appointments_department_id" in existing_indexes:
        op.drop_index("ix_appointments_department_id", table_name="appointments")

    existing_fk_names = {fk.get("name") for fk in inspector.get_foreign_keys("appointments")}
    if "fk_appointments_department" in existing_fk_names:
        op.drop_constraint("fk_appointments_department", "appointments", type_="foreignkey")

    existing_columns = {col["name"] for col in inspector.get_columns("appointments")}
    if "department_id" in existing_columns:
        op.drop_column("appointments", "department_id")
