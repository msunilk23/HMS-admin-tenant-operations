"""Add P32 batch recall and inter-location transfer workflows."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_RECALL_VIEW", "View medicine batch recalls", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_RECALL_CREATE", "Create medicine batch recalls", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_RECALL_APPROVE", "Approve medicine batch recalls", ("store_manager", "hospital_admin")),
    ("PHARMACY_RECALL_RESOLVE", "Resolve medicine batch recalls", ("store_manager", "hospital_admin")),
    ("PHARMACY_RECALL_NOTIFICATION", "Update recall notification status", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_TRANSFER_VIEW", "View inter-location stock transfers", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_TRANSFER_CREATE", "Create inter-location stock transfers", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_TRANSFER_APPROVE", "Approve inter-location stock transfers", ("store_manager", "hospital_admin")),
    ("PHARMACY_TRANSFER_DISPATCH", "Dispatch inter-location stock transfers", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_TRANSFER_RECEIVE", "Receive inter-location stock transfers", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_TRANSFER_RECONCILE", "Reconcile stock transfer discrepancies", ("store_manager", "hospital_admin")),
)


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    inspector = sa.inspect(bind)
    if schema == "public":
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
        return

    if inspector.has_table("product_recalls"):
        return

    op.drop_constraint("ck_stock_quarantine_status", "stock_quarantine", type_="check")
    op.drop_constraint("ck_stock_quarantine_reason", "stock_quarantine", type_="check")
    op.create_check_constraint("ck_stock_quarantine_status", "stock_quarantine", "status IN ('QUARANTINED', 'RELEASED', 'DISPOSED', 'RETURNED_TO_SUPPLIER')")
    op.create_check_constraint("ck_stock_quarantine_reason", "stock_quarantine", "reason IN ('EXPIRED', 'DAMAGED', 'INVESTIGATION', 'RECALL')")
    op.add_column("stock_transactions", sa.Column("correlation_reference", sa.String(100), nullable=True))
    op.create_index("ix_stock_transactions_correlation_reference", "stock_transactions", ["correlation_reference"])

    op.create_table(
        "product_recalls",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("facility_id", _uuid(), nullable=False), sa.Column("medicine_id", _uuid(), nullable=False),
        sa.Column("batch_number", sa.String(100), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("reference_key", sa.String(100), nullable=False), sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("recall_reason", sa.Text(), nullable=False),
        sa.Column("regulatory_reference", sa.String(200)), sa.Column("notification_status", sa.String(30), nullable=False, server_default="NOT_STARTED"),
        sa.Column("resolved_date", sa.DateTime(timezone=True)), sa.Column("initiated_by", _uuid(), nullable=False),
        sa.Column("approved_by", _uuid()), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_action", sa.String(30)), sa.Column("resolution_reason", sa.Text()), sa.Column("resolved_by", _uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "reference_key", name="uq_product_recalls_tenant_reference"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_product_recalls_tenant_idempotency"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RESOLVED')", name="ck_product_recalls_status"),
        sa.CheckConstraint("resolution_action IS NULL OR resolution_action IN ('SUPPLIER_RETURN', 'APPROVED_RELEASE', 'DISPOSAL')", name="ck_product_recalls_resolution"),
        sa.CheckConstraint("notification_status IN ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED')", name="ck_product_recalls_notification_status"),
    )
    for column in ("tenant_id", "facility_id", "medicine_id", "batch_number", "status", "reference_key", "initiated_by", "approved_by", "resolved_by"):
        op.create_index(f"ix_product_recalls_{column}", "product_recalls", [column])

    op.create_table(
        "recall_affected_stock",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("recall_id", _uuid(), nullable=False),
        sa.Column("inventory_batch_id", _uuid(), nullable=False), sa.Column("pharmacy_location_id", _uuid(), nullable=False),
        sa.Column("quarantine_id", _uuid(), unique=True), sa.Column("quantity_quarantined", sa.Numeric(12, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["recall_id"], ["product_recalls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.ForeignKeyConstraint(["quarantine_id"], ["stock_quarantine.id"]),
        sa.UniqueConstraint("recall_id", "inventory_batch_id", name="uq_recall_affected_batch"),
    )
    for column in ("recall_id", "inventory_batch_id", "pharmacy_location_id"):
        op.create_index(f"ix_recall_affected_stock_{column}", "recall_affected_stock", [column])

    op.create_table(
        "stock_transfers",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False), sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("from_location_id", _uuid(), nullable=False), sa.Column("to_location_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"), sa.Column("reference_key", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False), sa.Column("total_quantity", sa.Numeric(12, 3), nullable=False), sa.Column("notes", sa.Text()),
        sa.Column("requested_by", _uuid(), nullable=False), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_by", _uuid()), sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("dispatched_by", _uuid()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)), sa.Column("received_by", _uuid()), sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("received_quantity", sa.Numeric(12, 3)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["from_location_id"], ["pharmacy_locations.id"]), sa.ForeignKeyConstraint(["to_location_id"], ["pharmacy_locations.id"]),
        sa.UniqueConstraint("tenant_id", "reference_key", name="uq_stock_transfers_tenant_reference"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_stock_transfers_tenant_idempotency"),
        sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'IN_TRANSIT', 'RECEIVED', 'CANCELLED')", name="ck_stock_transfers_status"),
        sa.CheckConstraint("from_location_id <> to_location_id", name="ck_stock_transfers_distinct_locations"),
        sa.CheckConstraint("total_items > 0 AND total_quantity > 0", name="ck_stock_transfers_positive_totals"),
    )
    for column in ("tenant_id", "facility_id", "from_location_id", "to_location_id", "status", "reference_key", "requested_by", "approved_by", "dispatched_by", "received_by"):
        op.create_index(f"ix_stock_transfers_{column}", "stock_transfers", [column])

    op.create_table(
        "stock_transfer_items",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("transfer_id", _uuid(), nullable=False),
        sa.Column("inventory_batch_id", _uuid(), nullable=False), sa.Column("transfer_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(12, 3)), sa.Column("destination_batch_id", _uuid()),
        sa.Column("dispatch_ledger_id", _uuid(), unique=True), sa.Column("receive_ledger_id", _uuid(), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["transfer_id"], ["stock_transfers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]), sa.ForeignKeyConstraint(["destination_batch_id"], ["inventory_batches.id"]),
        sa.ForeignKeyConstraint(["dispatch_ledger_id"], ["stock_transactions.id"]), sa.ForeignKeyConstraint(["receive_ledger_id"], ["stock_transactions.id"]),
        sa.UniqueConstraint("transfer_id", "inventory_batch_id", name="uq_stock_transfer_item_batch"),
        sa.CheckConstraint("transfer_quantity > 0", name="ck_stock_transfer_item_positive_quantity"),
        sa.CheckConstraint("received_quantity IS NULL OR received_quantity >= 0", name="ck_stock_transfer_item_received_quantity"),
    )
    for column in ("transfer_id", "inventory_batch_id", "destination_batch_id"):
        op.create_index(f"ix_stock_transfer_items_{column}", "stock_transfer_items", [column])

    op.create_table(
        "stock_transfer_discrepancies",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("transfer_id", _uuid(), nullable=False), sa.Column("transfer_item_id", _uuid(), nullable=False),
        sa.Column("discrepancy_type", sa.String(30), nullable=False), sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="OPEN"),
        sa.Column("reported_by", _uuid(), nullable=False), sa.Column("reconciled_by", _uuid()), sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("reconciliation_action", sa.String(50)), sa.Column("reconciliation_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["transfer_id"], ["stock_transfers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transfer_item_id"], ["stock_transfer_items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("transfer_item_id", name="uq_stock_transfer_discrepancy_item"),
        sa.CheckConstraint("discrepancy_type IN ('SHORTAGE', 'EXCESS', 'DAMAGE', 'BATCH_MISMATCH')", name="ck_stock_transfer_discrepancy_type"),
        sa.CheckConstraint("status IN ('OPEN', 'RECONCILED')", name="ck_stock_transfer_discrepancy_status"),
        sa.CheckConstraint("quantity > 0", name="ck_stock_transfer_discrepancy_quantity"),
    )
    for column in ("transfer_id", "transfer_item_id", "discrepancy_type", "status", "reported_by", "reconciled_by"):
        op.create_index(f"ix_stock_transfer_discrepancies_{column}", "stock_transfer_discrepancies", [column])

    op.create_table(
        "pharmacy_workflow_operations",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False), sa.Column("facility_id", _uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("operation_type", sa.String(50), nullable=False), sa.Column("resource_id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_workflow_operation_key"),
    )
    for column in ("tenant_id", "facility_id", "operation_type", "resource_id"):
        op.create_index(f"ix_pharmacy_workflow_operations_{column}", "pharmacy_workflow_operations", [column])


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    if schema == "public":
        codes = [item[0] for item in _PERMISSIONS]
        bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"), {"codes": codes})
        bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})
        return
    for table in ("pharmacy_workflow_operations", "stock_transfer_discrepancies", "stock_transfer_items", "stock_transfers", "recall_affected_stock", "product_recalls"):
        if sa.inspect(bind).has_table(table):
            op.drop_table(table)
    op.drop_index("ix_stock_transactions_correlation_reference", table_name="stock_transactions")
    op.drop_column("stock_transactions", "correlation_reference")
    op.drop_constraint("ck_stock_quarantine_status", "stock_quarantine", type_="check")
    op.drop_constraint("ck_stock_quarantine_reason", "stock_quarantine", type_="check")
    op.create_check_constraint("ck_stock_quarantine_status", "stock_quarantine", "status IN ('QUARANTINED', 'RELEASED', 'DISPOSED')")
    op.create_check_constraint("ck_stock_quarantine_reason", "stock_quarantine", "reason IN ('EXPIRED', 'DAMAGED', 'INVESTIGATION')")