"""
P31-P34 Pharmacy Module Models

P31: Expiry + Damage + Recall
P32: Stock Transfer + Multi-location
P33: Cycle Count + Physical Verification
P34: Dashboard + Reports + Audit
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint,
    CheckConstraint, func, Boolean, Integer, JSON
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


# ============ P31: EXPIRY + DAMAGE + RECALL ============

class StockQuarantine(Base, TimestampMixin):
    """Quarantine status for expired, damaged, or suspected stock."""
    __tablename__ = "stock_quarantine"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "reference_key",
            name="uq_stock_quarantine_tenant_reference",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_stock_quarantine_tenant_idempotency",
        ),
        CheckConstraint(
            "status IN ('QUARANTINED', 'RELEASED', 'DISPOSED', 'RETURNED_TO_SUPPLIER')",
            name="ck_stock_quarantine_status",
        ),
        CheckConstraint(
            "reason IN ('EXPIRED', 'DAMAGED', 'INVESTIGATION', 'RECALL')",
            name="ck_stock_quarantine_reason",
        ),
        CheckConstraint(
            "total_quantity_quarantined > 0",
            name="ck_stock_quarantine_positive_quantity",
        ),
        CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= total_quantity_quarantined",
            name="ck_stock_quarantine_remaining_quantity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=False, index=True
    )
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARANTINED", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    
    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # EXPIRED, DAMAGED, RECALLED, RECALLED_PRODUCT, RECALLED_MANUFACTURER
    total_quantity_quarantined: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Approval trail
    quarantined_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    release_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    released_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    disposal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disposal_method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    disposal_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    witnessed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    disposed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    
    disposed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    quarantine_ledger_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("stock_transactions.id"), nullable=True, unique=True
    )
    release_ledger_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("stock_transactions.id"), nullable=True, unique=True
    )
    disposal_ledger_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("stock_transactions.id"), nullable=True, unique=True
    )


class ProductRecall(Base, TimestampMixin):
    """Medicine-and-batch specific recall with maker-checker control."""
    __tablename__ = "product_recalls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference_key", name="uq_product_recalls_tenant_reference"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_product_recalls_tenant_idempotency"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RESOLVED')", name="ck_product_recalls_status"),
        CheckConstraint("resolution_action IS NULL OR resolution_action IN ('SUPPLIER_RETURN', 'APPROVED_RELEASE', 'DISPOSAL')", name="ck_product_recalls_resolution"),
        CheckConstraint("notification_status IN ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED')", name="ck_product_recalls_notification_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    medicine_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recall_reason: Mapped[str] = mapped_column(Text, nullable=False)
    regulatory_reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="NOT_STARTED")
    resolved_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    initiated_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    resolution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)


class RecallAffectedStock(Base, TimestampMixin):
    __tablename__ = "recall_affected_stock"
    __table_args__ = (UniqueConstraint("recall_id", "inventory_batch_id", name="uq_recall_affected_batch"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_recalls.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    quarantine_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_quarantine.id"), nullable=True, unique=True)
    quantity_quarantined: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)


# ============ P32: STOCK TRANSFER + MULTI-LOCATION ============

class StockTransfer(Base, TimestampMixin):
    """Inter-location stock transfers."""
    __tablename__ = "stock_transfers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "reference_key",
            name="uq_stock_transfers_tenant_reference",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_stock_transfers_tenant_idempotency"),
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'IN_TRANSIT', 'RECEIVED', 'CANCELLED')",
            name="ck_stock_transfers_status",
        ),
        CheckConstraint("from_location_id <> to_location_id", name="ck_stock_transfers_distinct_locations"),
        CheckConstraint("total_items > 0 AND total_quantity > 0", name="ck_stock_transfers_positive_totals"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    from_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    to_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    
    total_items: Mapped[int] = mapped_column(nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Workflow
    requested_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    dispatched_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    received_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    received_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)


class StockTransferItem(Base, TimestampMixin):
    """Individual batch items in a transfer."""
    __tablename__ = "stock_transfer_items"
    __table_args__ = (
        UniqueConstraint("transfer_id", "inventory_batch_id", name="uq_stock_transfer_item_batch"),
        CheckConstraint("transfer_quantity > 0", name="ck_stock_transfer_item_positive_quantity"),
        CheckConstraint("received_quantity IS NULL OR received_quantity >= 0", name="ck_stock_transfer_item_received_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=False, index=True
    )
    
    transfer_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    received_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    destination_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("inventory_batches.id"), nullable=True, index=True)
    dispatch_ledger_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_transactions.id"), nullable=True, unique=True)
    receive_ledger_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_transactions.id"), nullable=True, unique=True)


class StockTransferDiscrepancy(Base, TimestampMixin):
    __tablename__ = "stock_transfer_discrepancies"
    __table_args__ = (
        UniqueConstraint("transfer_item_id", name="uq_stock_transfer_discrepancy_item"),
        CheckConstraint("discrepancy_type IN ('SHORTAGE', 'EXCESS', 'DAMAGE', 'BATCH_MISMATCH')", name="ck_stock_transfer_discrepancy_type"),
        CheckConstraint("status IN ('OPEN', 'RECONCILED')", name="ck_stock_transfer_discrepancy_status"),
        CheckConstraint("quantity > 0", name="ck_stock_transfer_discrepancy_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    transfer_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_transfer_items.id", ondelete="CASCADE"), nullable=False, index=True)
    discrepancy_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN", index=True)
    reported_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    reconciled_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciliation_action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reconciliation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PharmacyWorkflowOperation(Base):
    __tablename__ = "pharmacy_workflow_operations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_workflow_operation_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ============ P33: CYCLE COUNT + PHYSICAL VERIFICATION ============

class StockCountSettings(Base, TimestampMixin):
    __tablename__ = "stock_count_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "facility_id", name="uq_stock_count_settings_scope"),
        CheckConstraint("quantity_tolerance_percent >= 0", name="ck_stock_count_settings_tolerance"),
        CheckConstraint("repeated_variance_lookback_days > 0", name="ck_stock_count_settings_lookback"),
        CheckConstraint("repeated_variance_trigger > 0", name="ck_stock_count_settings_trigger"),
        CheckConstraint("high_value_variance_threshold >= 0", name="ck_stock_count_settings_high_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    quantity_tolerance_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0.5"))
    repeated_variance_lookback_days: Mapped[int] = mapped_column(nullable=False, default=90)
    repeated_variance_trigger: Mapped[int] = mapped_column(nullable=False, default=2)
    high_value_variance_threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("5000"))
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)


class StockCount(Base, TimestampMixin):
    """Physical inventory count sessions."""
    __tablename__ = "stock_counts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference_key", name="uq_stock_counts_tenant_reference"),
        CheckConstraint(
            "status IN ('CREATED', 'IN_PROGRESS', 'SUBMITTED', 'RECOUNT_REQUIRED', 'RECOUNT_IN_PROGRESS', 'RESUBMITTED', 'APPROVED', 'APPLIED', 'CANCELLED')",
            name="ck_stock_counts_status",
        ),
        CheckConstraint("count_type IN ('FULL', 'PARTIAL', 'SAMPLE')", name="ck_stock_counts_type"),
        CheckConstraint("recount_count >= 0 AND recount_count <= 2", name="ck_stock_counts_recount_limit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CREATED", index=True)
    count_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    selected_batch_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity_tolerance_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0.5"))
    repeated_variance_lookback_days: Mapped[int] = mapped_column(nullable=False, default=90)
    repeated_variance_trigger: Mapped[int] = mapped_column(nullable=False, default=2)
    high_value_variance_threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("5000"))
    expected_total_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    physical_total_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    variance_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    total_items_counted: Mapped[int] = mapped_column(nullable=False, default=0)
    total_variance_items: Mapped[int] = mapped_column(nullable=False, default=0)
    recount_count: Mapped[int] = mapped_column(nullable=False, default=0)
    initiated_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CountDetail(Base, TimestampMixin):
    """Individual batch count details."""
    __tablename__ = "count_details"
    __table_args__ = (
        UniqueConstraint("count_id", "inventory_batch_id", name="uq_count_details_batch"),
        CheckConstraint("system_quantity >= 0 AND available_quantity >= 0 AND reserved_quantity >= 0", name="ck_count_details_snapshot_nonnegative"),
        CheckConstraint("physical_quantity IS NULL OR physical_quantity >= 0", name="ck_count_details_physical_nonnegative"),
        CheckConstraint("version > 0", name="ck_count_details_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    count_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=False, index=True
    )
    medicine_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(String(100), nullable=False)
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    available_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    physical_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    variance_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    variance_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    variance_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    classifications: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    variance_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_unexpected: Mapped[bool] = mapped_column(nullable=False, default=False)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    counted_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    counted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    adjustment_ledger_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_transactions.id"), nullable=True, unique=True)


class CountRecount(Base, TimestampMixin):
    __tablename__ = "count_recounts"
    __table_args__ = (
        UniqueConstraint("count_id", "attempt_number", name="uq_count_recounts_attempt"),
        CheckConstraint("attempt_number > 0 AND attempt_number <= 2", name="ck_count_recounts_attempt"),
        CheckConstraint("status IN ('ASSIGNED', 'IN_PROGRESS', 'SUBMITTED')", name="ck_count_recounts_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    count_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ASSIGNED", index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CountRecountDetail(Base, TimestampMixin):
    __tablename__ = "count_recount_details"
    __table_args__ = (
        UniqueConstraint("recount_id", "count_detail_id", name="uq_count_recount_details_item"),
        CheckConstraint("physical_quantity IS NULL OR physical_quantity >= 0", name="ck_count_recount_details_physical"),
        CheckConstraint("version > 0", name="ck_count_recount_details_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recount_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("count_recounts.id", ondelete="CASCADE"), nullable=False, index=True)
    count_detail_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("count_details.id", ondelete="CASCADE"), nullable=False, index=True)
    physical_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    variance_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    variance_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    counted_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    counted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)


class StockCountOperation(Base):
    __tablename__ = "stock_count_operations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "action", "scope_resource", "idempotency_key", name="uq_stock_count_operation_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_resource: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    count_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False, index=True)
    response_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ============ P34: DASHBOARD + REPORTS + AUDIT ============

class PharmacyAlert(Base, TimestampMixin):
    """Alerts for dashboard and monitoring."""
    __tablename__ = "pharmacy_alerts"
    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('LOW_STOCK', 'OUT_OF_STOCK', 'NEAR_EXPIRY', 'EXPIRED', 'REPEATED_ADJUSTMENT', 'HIGH_VALUE_VARIANCE', 'UNUSUAL_RETURN')",
            name="ck_pharmacy_alerts_type",
        ),
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'CRITICAL')",
            name="ck_pharmacy_alerts_severity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # BATCH, MEDICINE, LOCATION
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_acknowledged: Mapped[bool] = mapped_column(nullable=False, default=False)
    
    acknowledged_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PharmacyAuditTrail(Base):
    """Extended audit trail for P34 dashboard tracking."""
    __tablename__ = "pharmacy_audit_trail"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # PatientReturn, SupplierReturn, StockTransfer, CountDetail
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE, UPDATE, APPROVE, REJECT
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    old_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    new_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
