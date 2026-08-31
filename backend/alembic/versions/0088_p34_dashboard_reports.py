"""Add P34 Pharmacy dashboard, alerts, reports, exports, and permissions."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_DASHBOARD_VIEW", "View Pharmacy dashboard", ("pharmacist", "store_manager", "hospital_admin", "auditor")),
    ("PHARMACY_REPORT_VIEW", "View Pharmacy reports", ("pharmacist", "store_manager", "hospital_admin", "auditor")),
    ("PHARMACY_REPORT_EXPORT", "Export Pharmacy reports", ("store_manager", "hospital_admin", "auditor")),
    ("PHARMACY_ALERT_VIEW", "View Pharmacy alerts", ("pharmacist", "store_manager", "hospital_admin", "auditor")),
    ("PHARMACY_ALERT_ACKNOWLEDGE", "Acknowledge Pharmacy alerts", ("pharmacist", "store_manager")),
    ("PHARMACY_ALERT_CONFIGURE", "Configure Pharmacy alerts", ("store_manager", "hospital_admin")),
    ("PHARMACY_AUDIT_VIEW", "View Pharmacy audit events", ("store_manager", "hospital_admin", "auditor")),
)


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _add_permissions(bind) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("permissions", schema="public") or not inspector.has_table("role_permissions", schema="public"):
        return
    for code, name, roles in _PERMISSIONS:
        bind.execute(text("""
            INSERT INTO public.permissions (id, code, name, is_active)
            VALUES (:id, :code, :name, true)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
        """), {"id": str(uuid.uuid4()), "code": code, "name": name})
        for role in roles:
            bind.execute(text("""
                INSERT INTO public.role_permissions (role, permission_id)
                SELECT :role, id FROM public.permissions WHERE code = :code
                ON CONFLICT (role, permission_id) DO NOTHING
            """), {"role": role, "code": code})


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    inspector = sa.inspect(bind)
    if schema == "public":
        _add_permissions(bind)
        return

    for preliminary_table in (
        "pharmacy_dashboard_operations",
        "pharmacy_alert_configurations",
        "pharmacy_alert_acknowledgements",
        "pharmacy_audit_trail",
        "pharmacy_alerts",
    ):
        if inspector.has_table(preliminary_table):
            op.drop_table(preliminary_table)

    op.create_table(
        "pharmacy_alerts",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("pharmacy_location_id", _uuid()),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("subject_type", sa.String(50), nullable=False),
        sa.Column("subject_key", sa.String(250), nullable=False),
        sa.Column("active_subject_key", sa.String(350)),
        sa.Column("subject_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("condition_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("previous_alert_id", _uuid()),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.ForeignKeyConstraint(["previous_alert_id"], ["pharmacy_alerts.id"]),
        sa.UniqueConstraint("tenant_id", "facility_id", "active_subject_key", name="uq_pharmacy_alerts_active_subject"),
        sa.CheckConstraint("alert_type IN ('LOW_STOCK', 'OUT_OF_STOCK', 'EXPIRY', 'UNUSUAL_ADJUSTMENT', 'REPEATED_VARIANCE', 'UNUSUAL_RETURN')", name="ck_pharmacy_alerts_type"),
        sa.CheckConstraint("severity IN ('INFO', 'WARNING', 'CRITICAL')", name="ck_pharmacy_alerts_severity"),
        sa.CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')", name="ck_pharmacy_alerts_status"),
    )
    for column in ("tenant_id", "facility_id", "pharmacy_location_id", "alert_type", "status", "subject_key", "previous_alert_id"):
        op.create_index(f"ix_pharmacy_alerts_{column}", "pharmacy_alerts", [column])

    op.create_table(
        "pharmacy_alert_acknowledgements",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("alert_id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("acknowledged_by", _uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["alert_id"], ["pharmacy_alerts.id"], ondelete="CASCADE"),
    )
    for column in ("alert_id", "tenant_id", "facility_id", "acknowledged_by"):
        op.create_index(f"ix_pharmacy_alert_acknowledgements_{column}", "pharmacy_alert_acknowledgements", [column])

    op.create_table(
        "pharmacy_alert_configurations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid()),
        sa.Column("pharmacy_location_id", _uuid()),
        sa.Column("scope_key", sa.String(100), nullable=False),
        sa.Column("reorder_level", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("expiry_horizon_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("high_value_thresholds", postgresql.JSONB(), nullable=False, server_default='{"INR":"5000.00"}'),
        sa.Column("quantity_percentage_threshold", sa.Numeric(7, 3), nullable=False, server_default="10"),
        sa.Column("repeated_event_count", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", _uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.UniqueConstraint("tenant_id", "scope_key", name="uq_pharmacy_alert_config_scope"),
        sa.CheckConstraint("version > 0", name="ck_pharmacy_alert_config_version"),
        sa.CheckConstraint("expiry_horizon_days > 0", name="ck_pharmacy_alert_config_expiry"),
        sa.CheckConstraint("quantity_percentage_threshold >= 0", name="ck_pharmacy_alert_config_quantity_pct"),
        sa.CheckConstraint("repeated_event_count > 0", name="ck_pharmacy_alert_config_repeat_count"),
        sa.CheckConstraint("lookback_days > 0", name="ck_pharmacy_alert_config_lookback"),
    )
    for column in ("tenant_id", "facility_id", "pharmacy_location_id", "updated_by"):
        op.create_index(f"ix_pharmacy_alert_configurations_{column}", "pharmacy_alert_configurations", [column])

    op.create_table(
        "pharmacy_dashboard_operations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("scope_resource", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "user_id", "action", "scope_resource", "idempotency_key", name="uq_pharmacy_dashboard_operation_scope"),
    )
    for column in ("tenant_id", "facility_id", "user_id", "action"):
        op.create_index(f"ix_pharmacy_dashboard_operations_{column}", "pharmacy_dashboard_operations", [column])


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    if schema == "public":
        codes = [item[0] for item in _PERMISSIONS]
        bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"), {"codes": codes})
        bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})
        return
    inspector = sa.inspect(bind)
    for table in (
        "pharmacy_dashboard_operations",
        "pharmacy_alert_configurations",
        "pharmacy_alert_acknowledgements",
        "pharmacy_alerts",
    ):
        if inspector.has_table(table):
            op.drop_table(table)