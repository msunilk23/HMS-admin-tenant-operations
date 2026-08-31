"""Add the P31 stock quarantine workflow and permissions."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_QUARANTINE_VIEW", "View quarantined pharmacy stock", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_QUARANTINE_CREATE", "Quarantine pharmacy stock", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_QUARANTINE_APPROVE", "Release or dispose quarantined pharmacy stock", ("store_manager", "hospital_admin")),
)


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    inspector = sa.inspect(bind)
    if schema == "public":
        if not inspector.has_table("permissions", schema="public") or not inspector.has_table("role_permissions", schema="public"):
            return
        for code, name, roles in _PERMISSIONS:
            bind.execute(
                text("""
                    INSERT INTO public.permissions (id, code, name, is_active)
                    VALUES (:id, :code, :name, true)
                    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
                """),
                {"id": str(uuid.uuid4()), "code": code, "name": name},
            )
            for role in roles:
                bind.execute(
                    text("""
                        INSERT INTO public.role_permissions (role, permission_id)
                        SELECT :role, id FROM public.permissions WHERE code = :code
                        ON CONFLICT (role, permission_id) DO NOTHING
                    """),
                    {"role": role, "code": code},
                )
        return

    if inspector.has_table("stock_quarantine"):
        return
    op.create_table(
        "stock_quarantine",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pharmacy_location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inventory_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUARANTINED"),
        sa.Column("reference_key", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("total_quantity_quarantined", sa.Numeric(12, 3), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("quarantined_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_action", sa.String(50), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.Column("released_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposal_reason", sa.Text(), nullable=True),
        sa.Column("disposal_method", sa.String(100), nullable=True),
        sa.Column("disposal_date", sa.Date(), nullable=True),
        sa.Column("witnessed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quarantine_ledger_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("release_ledger_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposal_ledger_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["pharmacy_location_id"], ["pharmacy_locations.id"]),
        sa.ForeignKeyConstraint(["inventory_batch_id"], ["inventory_batches.id"]),
        sa.ForeignKeyConstraint(["quarantine_ledger_transaction_id"], ["stock_transactions.id"]),
        sa.ForeignKeyConstraint(["release_ledger_transaction_id"], ["stock_transactions.id"]),
        sa.ForeignKeyConstraint(["disposal_ledger_transaction_id"], ["stock_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "reference_key", name="uq_stock_quarantine_tenant_reference"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_stock_quarantine_tenant_idempotency"),
        sa.UniqueConstraint("quarantine_ledger_transaction_id"),
        sa.UniqueConstraint("release_ledger_transaction_id"),
        sa.UniqueConstraint("disposal_ledger_transaction_id"),
        sa.CheckConstraint("status IN ('QUARANTINED', 'RELEASED', 'DISPOSED')", name="ck_stock_quarantine_status"),
        sa.CheckConstraint("reason IN ('EXPIRED', 'DAMAGED', 'INVESTIGATION')", name="ck_stock_quarantine_reason"),
        sa.CheckConstraint("total_quantity_quarantined > 0", name="ck_stock_quarantine_positive_quantity"),
        sa.CheckConstraint("remaining_quantity >= 0 AND remaining_quantity <= total_quantity_quarantined", name="ck_stock_quarantine_remaining_quantity"),
    )
    for column in ("tenant_id", "facility_id", "pharmacy_location_id", "inventory_batch_id", "status", "reference_key", "quarantined_by", "approved_by", "released_by", "witnessed_by", "disposed_by"):
        op.create_index(f"ix_stock_quarantine_{column}", "stock_quarantine", [column])


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar()
    if schema == "public":
        codes = [permission[0] for permission in _PERMISSIONS]
        bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"), {"codes": codes})
        bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})
        return
    if sa.inspect(bind).has_table("stock_quarantine"):
        op.drop_table("stock_quarantine")