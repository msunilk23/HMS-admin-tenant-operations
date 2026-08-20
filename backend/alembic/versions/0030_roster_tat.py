"""Add nurse roster assignments and OPD TAT timestamps."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()" )).scalar()
    if current_schema == "public":
        return

    roster_columns = [
        ("department_id", sa.UUID(as_uuid=True)),
        ("substitute_user_id", sa.UUID(as_uuid=True)),
        ("substitution_reason", sa.Text()),
        ("is_active", sa.Boolean(), sa.text("true")),
    ]
    for item in roster_columns:
        name, column_type, *default = item
        kwargs = {"nullable": True}
        if default:
            kwargs["server_default"] = default[0]
        op.add_column("nurse_roster", sa.Column(name, column_type, **kwargs))

    visit_columns = [
        "arrived_at", "registered_at", "nurse_queue_at", "nurse_called_at",
        "pre_vital_started_at", "pre_vital_completed_at", "doctor_queue_at",
        "doctor_called_at", "consultation_started_at", "consultation_completed_at",
        "billing_started_at", "billing_completed_at",
    ]
    for name in visit_columns:
        op.add_column("visits", sa.Column(name, sa.DateTime(timezone=True), nullable=True))

    for table, names in {
        "lab_orders": ("sample_collected_at", "processing_started_at", "result_ready_at", "verified_at", "completed_at"),
        "pharmacy_queue": ("called_at", "dispensing_started_at", "dispensed_at"),
    }.items():
        for name in names:
            op.add_column(table, sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()" )).scalar()
    if current_schema == "public":
        return
    for name in (
        "billing_completed_at", "billing_started_at", "consultation_completed_at",
        "consultation_started_at", "doctor_called_at", "doctor_queue_at",
        "pre_vital_completed_at", "pre_vital_started_at", "nurse_called_at",
        "nurse_queue_at", "registered_at", "arrived_at",
    ):
        op.drop_column("visits", name)
    for table, names in {
        "lab_orders": ("completed_at", "verified_at", "result_ready_at", "processing_started_at", "sample_collected_at"),
        "pharmacy_queue": ("dispensed_at", "dispensing_started_at", "called_at"),
    }.items():
        for name in names:
            op.drop_column(table, name)
    for name in ("is_active", "substitution_reason", "substitute_user_id", "department_id"):
        op.drop_column("nurse_roster", name)
