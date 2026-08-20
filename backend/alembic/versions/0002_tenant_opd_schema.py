"""Per-tenant OPD schema tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only run in tenant schemas — skip for public
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "doctors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("specialization", sa.String(255), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True)),
        sa.Column("consultation_fee", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("qualification", sa.String(500)),
        sa.Column("experience_years", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uhid", sa.String(20), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("dob", sa.Date()),
        sa.Column("gender", sa.String(10), nullable=False),
        sa.Column("phone", sa.String(15), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("address", sa.Text()),
        sa.Column("blood_group", sa.String(5)),
        sa.Column("insurance_provider", sa.String(255)),
        sa.Column("insurance_id", sa.String(100)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uhid"),
    )
    op.create_index("ix_patients_uhid", "patients", ["uhid"])
    op.create_index("ix_patients_phone", "patients", ["phone"])

    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("type", sa.String(20), nullable=False, server_default="walkin"),
        sa.Column("notes", sa.Text()),
        sa.Column("booked_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    op.create_index("ix_appointments_doctor_id", "appointments", ["doctor_id"])

    op.create_table(
        "queue_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("token_no", sa.Integer(), nullable=False),
        sa.Column("queue_type", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="waiting"),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queue_tokens_patient_id", "queue_tokens", ["patient_id"])

    op.create_table(
        "visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="registered"),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_visits_patient_id", "visits", ["patient_id"])

    op.create_table(
        "vitals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bp_systolic", sa.Integer()),
        sa.Column("bp_diastolic", sa.Integer()),
        sa.Column("temperature", sa.Float()),
        sa.Column("weight", sa.Float()),
        sa.Column("height", sa.Float()),
        sa.Column("spo2", sa.Integer()),
        sa.Column("pulse", sa.Integer()),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vitals_visit_id", "vitals", ["visit_id"])

    op.create_table(
        "consultations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chief_complaint", sa.Text()),
        sa.Column("history", sa.Text()),
        sa.Column("examination", sa.Text()),
        sa.Column("diagnosis_icd10", postgresql.JSONB()),
        sa.Column("notes", sa.Text()),
        sa.Column("follow_up_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("visit_id"),
    )

    op.create_table(
        "prescriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("medicines", postgresql.JSONB()),
        sa.Column("instructions", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prescriptions_visit_id", "prescriptions", ["visit_id"])

    op.create_table(
        "lab_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tests", postgresql.JSONB()),
        sa.Column("status", sa.String(20), nullable=False, server_default="ordered"),
        sa.Column("ordered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lab_orders_visit_id", "lab_orders", ["visit_id"])

    op.create_table(
        "lab_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lab_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("results", postgresql.JSONB()),
        sa.Column("reported_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lab_order_id"], ["lab_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pharmacy_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_items", postgresql.JSONB()),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("discount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("tax", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("payment_method", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_visit_id", "invoices", ["visit_id"])

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.Integer()),
        sa.Column("comments", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("link_sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("visit_id"),
    )

    op.create_table(
        "nurse_roster",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(20), nullable=False),
        sa.Column("room", sa.String(50)),
        sa.Column("assigned_doctor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("is_present", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_doctor_id"], ["doctors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("old_value", postgresql.JSONB()),
        sa.Column("new_value", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    tables = [
        "audit_logs", "nurse_roster", "feedback", "invoices",
        "pharmacy_queue", "lab_results", "lab_orders", "prescriptions",
        "consultations", "vitals", "visits", "queue_tokens",
        "appointments", "patients", "doctors", "departments",
    ]
    for table in tables:
        op.drop_table(table)
