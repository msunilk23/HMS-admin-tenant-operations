"""
Patient and Supplier Return Models - P30

Manages product returns from patients and suppliers back to hospital stock.
Maintains referential integrity to original transactions and financial records.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PatientReturn(Base, TimestampMixin):
    """Patient return of dispensed medicines."""
    __tablename__ = "patient_returns"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "reference_key",
            name="uq_patient_returns_tenant_reference",
        ),
        CheckConstraint(
            "status IN ('REQUESTED', 'VALIDATED', 'ACCEPTED', 'REJECTED', 'REFUND_PENDING', 'REFUNDED', 'RESTOCKED', 'NON_RESTOCKABLE')",
            name="ck_patient_returns_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id"), nullable=False, index=True
    )
    dispense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_dispenses.id"), nullable=False, index=True
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("invoices.id"), nullable=True, index=True
    )
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="REQUESTED", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    return_reason: Mapped[str] = mapped_column(Text, nullable=False)
    package_condition: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Financial tracking
    total_return_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    total_return_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    
    # Restockability
    restockable_count: Mapped[int] = mapped_column(nullable=False, default=0)
    non_restockable_count: Mapped[int] = mapped_column(nullable=False, default=0)
    
    # Audit trail
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    validated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PatientReturnItem(Base, TimestampMixin):
    """Individual items in a patient return."""
    __tablename__ = "patient_return_items"
    __table_args__ = (
        UniqueConstraint(
            "return_id",
            "dispense_item_id",
            name="uq_patient_return_items_return_dispense",
        ),
        CheckConstraint(
            "status IN ('PENDING_VALIDATION', 'ACCEPTED', 'REJECTED')",
            name="ck_patient_return_items_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    return_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_returns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dispense_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_dispense_items.id"), nullable=False, index=True
    )
    medicine_product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("medicine_products.id"), nullable=True, index=True
    )
    inventory_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=True, index=True
    )
    
    # Return details
    prescribed_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    original_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    return_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    
    # Restockability assessment
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_VALIDATION")
    restockable: Mapped[bool] = mapped_column(nullable=False, default=False)
    non_restockable_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Restock reference if accepted
    restock_ledger_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("stock_transactions.id"), nullable=True
    )
    
    validated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SupplierReturn(Base, TimestampMixin):
    """Supplier return of received goods (from GRN)."""
    __tablename__ = "supplier_returns"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "reference_key",
            name="uq_supplier_returns_tenant_reference",
        ),
        CheckConstraint(
            "status IN ('REQUESTED', 'APPROVED', 'DISPATCHED', 'RECEIVED', 'REJECTED', 'CANCELLED')",
            name="ck_supplier_returns_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pharmacy_locations.id"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    
    # Reference to original procurement
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=True, index=True
    )
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("goods_receipts.id"), nullable=True, index=True
    )
    
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="REQUESTED", index=True)
    reference_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    return_reason: Mapped[str] = mapped_column(Text, nullable=False)
    total_return_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    total_return_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    
    # Audit trail
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SupplierReturnItem(Base, TimestampMixin):
    """Individual items in a supplier return."""
    __tablename__ = "supplier_return_items"
    __table_args__ = (
        UniqueConstraint(
            "supplier_return_id",
            "inventory_batch_id",
            name="uq_supplier_return_items_return_batch",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    supplier_return_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("supplier_returns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_batches.id"), nullable=False, index=True
    )
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        nullable=True, index=True
    )
    
    # Return details
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    return_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    
    # Stock reduction reference
    stock_reduction_ledger_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("stock_transactions.id"), nullable=True
    )
