"""Add P33 stock count, recount, freeze, and variance workflows."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("INVENTORY_COUNT_VIEW", "View inventory counts", ("pharmacist", "store_manager", "hospital_admin", "auditor")),
    ("INVENTORY_COUNT_INITIATE", "Initiate inventory counts", ("pharmacist", "store_manager")),
    ("INVENTORY_COUNT_RECORD", "Record inventory count quantities", ("pharmacist", "store_manager")),
    ("INVENTORY_COUNT_COMPLETE", "Complete inventory counts", ("pharmacist", "store_manager")),
    ("INVENTORY_COUNT_RECOUNT", "Request or perform inventory recounts", ("pharmacist", "store_manager")),
    ("INVENTORY_COUNT_APPROVE", "Approve inventory counts", ("store_manager",)),
    ("INVENTORY_COUNT_APPLY", "Apply approved inventory count adjustments", ("store_manager",)),
    ("INVENTORY_COUNT_CANCEL", "Cancel inventory counts", ("pharmacist", "store_manager")),
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
    if inspector.has_table("stock_counts"):
        return

    op.create_table(
        "stock_count_settings",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("quantity_tolerance_percent", sa.Numeric(7, 3), nullable=False, server_default="0.5"),
        sa.Column("repeated_variance_lookback_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("repeated_variance_trigger", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("high_value_variance_threshold", sa.Numeric(14, 2), nullable=False, server_default="5000"),
        sa.Column("updated_by", _uuid()),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "facility_id", name="uq_stock_count_settings_scope"),
        sa.CheckConstraint("quantity_tolerance_percent >= 0", name="ck_stock_count_settings_tolerance"),
        sa.CheckConstraint("repeated_variance_lookback_days > 0", name="ck_stock_count_settings_lookback"),
        sa.CheckConstraint("repeated_variance_trigger > 0", name="ck_stock_count_settings_trigger"),
        sa.CheckConstraint("high_value_variance_threshold >= 0", name="ck_stock_count_settings_high_value"),
    )
    for column in ("tenant_id", "facility_id", "updated_by"):
        op.create_index(f"ix_stock_count_settings_{column}", "stock_count_settings", [column])

    op.create_table(
        "stock_counts",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("pharmacy_location_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="CREATED"),
        sa.Column("count_type", sa.String(20), nullable=False),
        sa.Column("reference_key", sa.String(100), nullable=False),
        sa.Column("selected_batch_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text()),
        sa.Column("quantity_tolerance_percent", sa.Numeric(7, 3), nullable=False, server_default="0.5"),
        sa.Column("repeated_variance_lookback_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("repeated_variance_trigger", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("high_value_variance_threshold", sa.Numeric(14, 2), nullable=False, server_default="5000"),
        sa.Column("expected_total_quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("physical_total_quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("variance_quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("total_items_counted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_variance_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recount_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("initiated_by", _uuid(), nullable=False),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_by", _uuid()), sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by", _uuid()), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", _uuid()), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("applied_by", _uuid()), sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", _uuid()), sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancellation_reason", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.UniqueConstraint("tenant_id", "reference_key", name="uq_stock_counts_tenant_reference"),
        sa.CheckConstraint("status IN ('CREATED', 'IN_PROGRESS', 'SUBMITTED', 'RECOUNT_REQUIRED', 'RECOUNT_IN_PROGRESS', 'RESUBMITTED', 'APPROVED', 'APPLIED', 'CANCELLED')", name="ck_stock_counts_status"),
        sa.CheckConstraint("count_type IN ('FULL', 'PARTIAL', 'SAMPLE')", name="ck_stock_counts_type"),
        sa.CheckConstraint("recount_count >= 0 AND recount_count <= 2", name="ck_stock_counts_recount_limit"),
    )
    for column in ("tenant_id", "facility_id", "pharmacy_location_id", "status", "count_type", "reference_key", "initiated_by", "started_by", "completed_by", "approved_by", "applied_by", "cancelled_by"):
        op.create_index(f"ix_stock_counts_{column}", "stock_counts", [column])

    op.add_column("inventory_batches", sa.Column("frozen_by_count_id", _uuid(), nullable=True))
    op.add_column("inventory_batches", sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_inventory_batches_frozen_by_count", "inventory_batches", "stock_counts", ["frozen_by_count_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_inventory_batches_frozen_by_count_id", "inventory_batches", ["frozen_by_count_id"])

    op.create_table(
        "count_details",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("count_id", _uuid(), nullable=False),
        sa.Column("inventory_batch_id", _uuid(), nullable=False), sa.Column("medicine_id", _uuid(), nullable=False),
        sa.Column("batch_number", sa.String(100), nullable=False), sa.Column("system_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("available_quantity", sa.Numeric(12, 3), nullable=False), sa.Column("reserved_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2)), sa.Column("physical_quantity", sa.Numeric(12, 3)),
        sa.Column("variance_quantity", sa.Numeric(12, 3)), sa.Column("variance_percent", sa.Numeric(12, 3)),
        sa.Column("variance_value", sa.Numeric(14, 2)), sa.Column("classifications", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("variance_reason", sa.Text()), sa.Column("is_unexpected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence", sa.Text()), sa.Column("counted_by", _uuid()), sa.Column("counted_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("adjustment_ledger_id", _uuid(), unique=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["count_id"], ["stock_counts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
        sa.ForeignKeyConstraint(["adjustment_ledger_id"], ["stock_transactions.id"]),
        sa.UniqueConstraint("count_id", "inventory_batch_id", name="uq_count_details_batch"),
        sa.CheckConstraint("system_quantity >= 0 AND available_quantity >= 0 AND reserved_quantity >= 0", name="ck_count_details_snapshot_nonnegative"),
        sa.CheckConstraint("physical_quantity IS NULL OR physical_quantity >= 0", name="ck_count_details_physical_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_count_details_version"),
    )
    for column in ("count_id", "inventory_batch_id", "medicine_id", "counted_by"):
        op.create_index(f"ix_count_details_{column}", "count_details", [column])

    op.create_table(
        "count_recounts",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("count_id", _uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="ASSIGNED"),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("assigned_to", _uuid(), nullable=False),
        sa.Column("requested_by", _uuid(), nullable=False), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("submitted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["count_id"], ["stock_counts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("count_id", "attempt_number", name="uq_count_recounts_attempt"),
        sa.CheckConstraint("attempt_number > 0 AND attempt_number <= 2", name="ck_count_recounts_attempt"),
        sa.CheckConstraint("status IN ('ASSIGNED', 'IN_PROGRESS', 'SUBMITTED')", name="ck_count_recounts_status"),
    )
    for column in ("count_id", "status", "assigned_to", "requested_by"):
        op.create_index(f"ix_count_recounts_{column}", "count_recounts", [column])

    op.create_table(
        "count_recount_details",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("recount_id", _uuid(), nullable=False),
        sa.Column("count_detail_id", _uuid(), nullable=False), sa.Column("physical_quantity", sa.Numeric(12, 3)),
        sa.Column("variance_quantity", sa.Numeric(12, 3)), sa.Column("variance_reason", sa.Text()),
        sa.Column("counted_by", _uuid()), sa.Column("counted_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"), *_timestamps(),
        sa.ForeignKeyConstraint(["recount_id"], ["count_recounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["count_detail_id"], ["count_details.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("recount_id", "count_detail_id", name="uq_count_recount_details_item"),
        sa.CheckConstraint("physical_quantity IS NULL OR physical_quantity >= 0", name="ck_count_recount_details_physical"),
        sa.CheckConstraint("version > 0", name="ck_count_recount_details_version"),
    )
    for column in ("recount_id", "count_detail_id", "counted_by"):
        op.create_index(f"ix_count_recount_details_{column}", "count_recount_details", [column])

    op.create_table(
        "stock_count_operations",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False), sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False), sa.Column("scope_resource", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("count_id", _uuid(), nullable=False), sa.Column("response_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["count_id"], ["stock_counts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "user_id", "action", "scope_resource", "idempotency_key", name="uq_stock_count_operation_scope"),
    )
    for column in ("tenant_id", "facility_id", "user_id", "action", "count_id"):
        op.create_index(f"ix_stock_count_operations_{column}", "stock_count_operations", [column])


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    if schema == "public":
        codes = [item[0] for item in _PERMISSIONS]
        bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"), {"codes": codes})
        bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})
        return
    inspector = sa.inspect(bind)
    for table in ("stock_count_operations", "count_recount_details", "count_recounts", "count_details"):
        if inspector.has_table(table):
            op.drop_table(table)
    if inspector.has_table("inventory_batches") and "frozen_by_count_id" in {column["name"] for column in inspector.get_columns("inventory_batches")}:
        op.drop_index("ix_inventory_batches_frozen_by_count_id", table_name="inventory_batches")
        op.drop_constraint("fk_inventory_batches_frozen_by_count", "inventory_batches", type_="foreignkey")
        op.drop_column("inventory_batches", "frozen_at")
        op.drop_column("inventory_batches", "frozen_by_count_id")
    for table in ("stock_counts", "stock_count_settings"):
        if inspector.has_table(table):
            op.drop_table(table)