"""Add PF-1 post-consultation patient routing and document requests."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT current_schema()")).scalar() == "public":
        return

    op.create_table(
        "patient_route_configurations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid()),
        sa.Column("presentation_window_minutes", sa.Integer(), nullable=False, server_default="30"),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "facility_id", name="uq_patient_route_config_scope"),
    )
    op.create_index("ix_patient_route_configurations_tenant_id", "patient_route_configurations", ["tenant_id"])
    op.create_index("ix_patient_route_configurations_facility_id", "patient_route_configurations", ["facility_id"])

    op.create_table(
        "patient_routes",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("visit_id", _uuid(), sa.ForeignKey("visits.id"), nullable=False),
        sa.Column("consultation_id", _uuid(), sa.ForeignKey("consultations.id")),
        sa.Column("patient_id", _uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("uhid", sa.String(20), nullable=False),
        sa.Column("facility_id", _uuid()),
        sa.Column("status", sa.String(40), nullable=False, server_default="AWAITING_PATIENT"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("visit_id", name="uq_patient_routes_visit"),
    )
    for name, columns in (("ix_patient_routes_visit_id", ["visit_id"]), ("ix_patient_routes_patient_id", ["patient_id"]), ("ix_patient_routes_facility_id", ["facility_id"]), ("ix_patient_routes_patient_status", ["patient_id", "status"])):
        op.create_index(name, "patient_routes", columns)

    op.create_table(
        "patient_route_steps",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("route_id", _uuid(), sa.ForeignKey("patient_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visit_id", _uuid(), sa.ForeignKey("visits.id"), nullable=False),
        sa.Column("destination", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_record_id", _uuid()),
        sa.Column("status", sa.String(40), nullable=False, server_default="AWAITING_PATIENT"),
        sa.Column("presentation_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("presented_at", sa.DateTime(timezone=True)),
        sa.Column("service_started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("not_presented_at", sa.DateTime(timezone=True)),
        sa.Column("reopened_at", sa.DateTime(timezone=True)),
        sa.Column("presented_by_user_id", _uuid()),
        sa.Column("reopened_by_user_id", _uuid()),
        sa.Column("presentation_channel", sa.String(30)),
        sa.Column("outcome_reason", sa.Text()),
        sa.Column("late_presentation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("route_id", "destination", name="uq_patient_route_steps_destination"),
    )
    op.create_index("ix_patient_route_steps_route_id", "patient_route_steps", ["route_id"])
    op.create_index("ix_patient_route_steps_visit_id", "patient_route_steps", ["visit_id"])
    op.create_index("ix_patient_route_steps_lookup", "patient_route_steps", ["destination", "status", "presentation_deadline_at"])

    op.create_table(
        "patient_route_events",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("route_id", _uuid(), sa.ForeignKey("patient_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", _uuid(), sa.ForeignKey("patient_route_steps.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("previous_state", sa.String(40)),
        sa.Column("new_state", sa.String(40), nullable=False),
        sa.Column("actor_user_id", _uuid()),
        sa.Column("reason", sa.Text()),
        sa.Column("channel", sa.String(30)),
        sa.Column("request_id", sa.String(100)),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_patient_route_events_route_id", "patient_route_events", ["route_id"])
    op.create_index("ix_patient_route_events_step_time", "patient_route_events", ["step_id", "created_at"])
    op.create_index("ix_patient_route_events_request_id", "patient_route_events", ["request_id"])

    op.create_table(
        "prescription_document_requests",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("prescription_id", _uuid(), sa.ForeignKey("prescriptions.id"), nullable=False),
        sa.Column("visit_id", _uuid(), sa.ForeignKey("visits.id"), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING_GENERATION"),
        sa.Column("document_version_id", _uuid()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("prescription_id", name="uq_prescription_document_requests_prescription"),
    )
    op.create_index("ix_prescription_document_requests_prescription_id", "prescription_document_requests", ["prescription_id"])
    op.create_index("ix_prescription_document_requests_visit_id", "prescription_document_requests", ["visit_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT current_schema()")).scalar() == "public":
        return
    op.drop_table("prescription_document_requests")
    op.drop_table("patient_route_events")
    op.drop_table("patient_route_steps")
    op.drop_table("patient_routes")
    op.drop_table("patient_route_configurations")