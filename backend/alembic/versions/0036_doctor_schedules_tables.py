"""Create doctor schedule tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    inspector = sa.inspect(bind)

    if not inspector.has_table("doctor_schedules"):
        op.create_table(
            "doctor_schedules",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.Column("slot_duration_minutes", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("room", sa.String(length=100), nullable=True),
            sa.Column("appointment_type", sa.String(length=30), nullable=True, server_default="consultation"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
            sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_doctor_schedules_doctor_id", "doctor_schedules", ["doctor_id"])
        op.create_index("ix_doctor_schedules_department_id", "doctor_schedules", ["department_id"])

    if not inspector.has_table("doctor_schedule_exceptions"):
        op.create_table(
            "doctor_schedule_exceptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("exception_type", sa.String(length=30), nullable=False),
            sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_doctor_schedule_exceptions_doctor_id",
            "doctor_schedule_exceptions",
            ["doctor_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    inspector = sa.inspect(bind)

    if inspector.has_table("doctor_schedule_exceptions"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("doctor_schedule_exceptions")}
        if "ix_doctor_schedule_exceptions_doctor_id" in existing_indexes:
            op.drop_index("ix_doctor_schedule_exceptions_doctor_id", table_name="doctor_schedule_exceptions")
        op.drop_table("doctor_schedule_exceptions")

    if inspector.has_table("doctor_schedules"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("doctor_schedules")}
        if "ix_doctor_schedules_department_id" in existing_indexes:
            op.drop_index("ix_doctor_schedules_department_id", table_name="doctor_schedules")
        if "ix_doctor_schedules_doctor_id" in existing_indexes:
            op.drop_index("ix_doctor_schedules_doctor_id", table_name="doctor_schedules")
        op.drop_table("doctor_schedules")
