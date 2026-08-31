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
    CheckConstraint, func, Boolean, Integer
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
            "status IN ('QUARANTINED', 'RELEASED', 'DISPOSED')",
            name="ck_stock_quarantine_status",
        ),
        CheckConstraint(
            "reason IN ('EXPIRED', 'DAMAGED', 'INVESTIGATION')",
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
    """Track product recalls at product, manufacturer, or batch level."""
    __tablename__ = "product_recalls"
    __table_args__ = (
        CheckConstraint(
            "recall_level IN ('PRODUCT', 'MANUFACTURER', 'BATCH')",
            name="ck_product_recalls_level",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'RESOLVED', 'CANCELLED')",
            name="ck_product_recalls_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    
    recall_level: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE", index=True)
    
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("medicine_products.id"), nullable=True, index=True
    )
    manufacturer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("manufacturers.id"), nullable=True, index=True
    )
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=True, index=True
    )
    
    recall_reason: Mapped[str] = mapped_column(Text, nullable=False)
    issued_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    initiated_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)


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
        CheckConstraint(
            "status IN ('REQUESTED', 'APPROVED', 'ISSUED', 'IN_TRANSIT', 'RECEIVED', 'PARTIAL_RECEIVED', 'REJECTED', 'CANCELLED')",
            name="ck_stock_transfers_status",
        ),
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
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="REQUESTED", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    
    total_items: Mapped[int] = mapped_column(nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Workflow
    requested_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    issued_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    received_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    received_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)


class StockTransferItem(Base, TimestampMixin):
    """Individual batch items in a transfer."""
    __tablename__ = "stock_transfer_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=False, index=True
    )
    
    transfer_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    received_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    
    discrepancy_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    discrepancy_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ============ P33: CYCLE COUNT + PHYSICAL VERIFICATION ============

class StockCount(Base, TimestampMixin):
    """Physical inventory count sessions."""
    __tablename__ = "stock_counts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "reference_key",
            name="uq_stock_counts_tenant_reference",
        ),
        CheckConstraint(
            "status IN ('INITIATED', 'IN_PROGRESS', 'COMPLETED', 'APPROVED', 'ADJUSTED')",
            name="ck_stock_counts_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="INITIATED", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    count_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    total_items_counted: Mapped[int] = mapped_column(nullable=False, default=0)
    total_variance_items: Mapped[int] = mapped_column(nullable=False, default=0)
    
    initiated_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CountDetail(Base, TimestampMixin):
    """Individual batch count details."""
    __tablename__ = "count_details"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    count_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=False, index=True
    )
    
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    physical_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    variance_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    
    variance_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    counted_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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
