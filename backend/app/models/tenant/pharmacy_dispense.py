import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PharmacyDispense(Base, TimestampMixin):
    __tablename__ = "pharmacy_dispenses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_dispenses_tenant_idempotency"),
        CheckConstraint(
            "status IN ('DRAFT', 'VALIDATED', 'RESERVED', 'READY_FOR_BILLING', 'BILLING_FAILED', 'READY_TO_CONFIRM', 'CONFIRMED', 'PARTIALLY_FULFILLED', 'OUTSIDE_FULFILLED', 'CANCELLED', 'EXPIRED')",
            name="ck_pharmacy_dispenses_status",
        ),
        CheckConstraint("classification = 'OPD_PRESCRIPTION'", name="ck_pharmacy_dispenses_classification"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    prescription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prescriptions.id"), nullable=False, index=True)
    prescription_version: Mapped[int] = mapped_column(nullable=False, default=1)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    pharmacy_queue_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("pharmacy_queue.id"), nullable=True, index=True)
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    classification: Mapped[str] = mapped_column(String(30), nullable=False, default="OPD_PRESCRIPTION")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    fulfillment_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="FULL_INTERNAL")
    billing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="NOT_REQUIRED")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    request_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    ready_for_billing_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_for_billing_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)


class PharmacyDispenseItem(Base, TimestampMixin):
    __tablename__ = "pharmacy_dispense_items"
    __table_args__ = (
        UniqueConstraint("dispense_id", "prescription_item_id", name="uq_pharmacy_dispense_items_dispense_prescription"),
        CheckConstraint("prescribed_quantity > 0", name="ck_pharmacy_dispense_items_prescribed_positive"),
        CheckConstraint("internal_requested_quantity >= 0 AND internal_confirmed_quantity >= 0 AND outside_purchase_quantity >= 0", name="ck_pharmacy_dispense_items_quantities_nonnegative"),
        CheckConstraint("internal_confirmed_quantity + outside_purchase_quantity <= prescribed_quantity", name="ck_pharmacy_dispense_items_fulfillment_limit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dispense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_dispenses.id", ondelete="CASCADE"), nullable=False, index=True)
    prescription_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prescription_items.id"), nullable=False, index=True)
    prescribed_medicine_product_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("medicine_products.id"), nullable=True, index=True)
    dispensed_medicine_product_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("medicine_products.id"), nullable=True, index=True)
    prescribed_medicine_master_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("medicine_master.id"), nullable=True, index=True)
    prescribed_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    prescribed_strength_snapshot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prescribed_dosage_form_snapshot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prescribed_route_snapshot: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    prescribed_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    internal_requested_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    internal_confirmed_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    outside_purchase_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    substitution_flag: Mapped[bool] = mapped_column(nullable=False, default=False)
    substitution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    substitution_approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    substitution_approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    no_substitution_applied: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", index=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)


class PharmacyDispenseAllocation(Base, TimestampMixin):
    __tablename__ = "pharmacy_dispense_allocations"
    __table_args__ = (
        UniqueConstraint("dispense_item_id", "inventory_batch_id", name="uq_pharmacy_allocations_item_batch"),
        CheckConstraint("allocated_quantity > 0", name="ck_pharmacy_allocations_allocated_positive"),
        CheckConstraint("confirmed_dispensed_quantity >= 0 AND confirmed_dispensed_quantity <= allocated_quantity", name="ck_pharmacy_allocations_confirmed_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dispense_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_dispense_items.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    allocated_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    confirmed_dispensed_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    allocation_source: Mapped[str] = mapped_column(String(30), nullable=False, default="FEFO")
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    stock_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_transactions.id"), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROPOSED", index=True)


class PharmacyStockReservation(Base, TimestampMixin):
    __tablename__ = "pharmacy_stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_pharmacy_reservations_quantity_positive"),
        CheckConstraint("status IN ('ACTIVE', 'CONSUMED', 'RELEASED', 'EXPIRED', 'CANCELLED')", name="ck_pharmacy_reservations_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    dispense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_dispenses.id", ondelete="CASCADE"), nullable=False, index=True)
    dispense_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_dispense_items.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", index=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reserved_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    release_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
