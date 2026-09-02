import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PharmacyRetailConfiguration(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_pharmacy_retail_config_tenant"),
        CheckConstraint("non_controlled_validity_days BETWEEN 1 AND 30", name="ck_retail_config_noncontrolled_validity"),
        CheckConstraint("non_controlled_max_supply_days BETWEEN 1 AND 30", name="ck_retail_config_noncontrolled_supply"),
        CheckConstraint("controlled_validity_days BETWEEN 1 AND 7", name="ck_retail_config_controlled_validity"),
        CheckConstraint("controlled_max_supply_days BETWEEN 1 AND 7", name="ck_retail_config_controlled_supply"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    non_controlled_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    non_controlled_max_supply_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    controlled_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    controlled_max_supply_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)


class PharmacistLocationAuthorization(Base, TimestampMixin):
    __tablename__ = "pharmacist_location_authorizations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "facility_id", "pharmacy_location_id", "user_id", name="uq_pharmacist_location_authorization"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    authorized_by: Mapped[uuid.UUID] = mapped_column(nullable=False)


class PharmacyRetailSale(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_sales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_retail_sale_idempotency"),
        UniqueConstraint("tenant_id", "receipt_number", name="uq_pharmacy_retail_sale_receipt"),
        CheckConstraint("classification IN ('OTC', 'EXTERNAL_PRESCRIPTION')", name="ck_pharmacy_retail_sale_classification"),
        CheckConstraint("status IN ('DRAFT', 'PENDING_VERIFICATION', 'VERIFIED', 'FULLY_DISPENSED', 'REJECTED', 'CANCELLED', 'EXPIRED')", name="ck_pharmacy_retail_sale_status"),
        CheckConstraint("payment_status IN ('PENDING', 'PAID', 'FAILED', 'REFUNDED')", name="ck_pharmacy_retail_sale_payment_status"),
        CheckConstraint("verified_by IS NULL OR dispensed_by IS NULL OR controlled_sale = false OR verified_by <> dispensed_by", name="ck_pharmacy_retail_controlled_maker_checker"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    controlled_sale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    customer_reference: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    patient_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    patient_date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    patient_age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    patient_gender: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    patient_mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    patient_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    government_id_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    government_id_last_four: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    prescriber_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prescriber_registration_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prescription_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    issuing_facility: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prescription_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prescription_attachment_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_prescription_inspected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dispensed_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    dispensed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    payment_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    payment_reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)


class PharmacyRetailSaleItem(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_sale_items"
    __table_args__ = (
        UniqueConstraint("sale_id", "medicine_product_id", name="uq_pharmacy_retail_sale_item_product"),
        CheckConstraint("quantity > 0", name="ck_pharmacy_retail_sale_item_quantity"),
        CheckConstraint("prescribed_quantity IS NULL OR prescribed_quantity > 0", name="ck_pharmacy_retail_prescribed_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_sales.id", ondelete="CASCADE"), nullable=False, index=True)
    medicine_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medicine_products.id"), nullable=False, index=True)
    medicine_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    prescribed_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    prescribed_duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requires_prescription: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_controlled_drug: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class PharmacyRetailSaleAllocation(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_sale_allocations"
    __table_args__ = (
        UniqueConstraint("sale_item_id", "inventory_batch_id", name="uq_pharmacy_retail_allocation_batch"),
        CheckConstraint("quantity > 0", name="ck_pharmacy_retail_allocation_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sale_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_sale_items.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock_transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_transactions.id"), nullable=False, unique=True)


class PharmacyRetailInvoice(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_invoices"
    __table_args__ = (
        UniqueConstraint("sale_id", name="uq_pharmacy_retail_invoice_sale"),
        UniqueConstraint("tenant_id", "invoice_number", name="uq_pharmacy_retail_invoice_number"),
        CheckConstraint("classification IN ('OTC', 'EXTERNAL_PRESCRIPTION')", name="ck_pharmacy_retail_invoice_classification"),
        CheckConstraint("status IN ('PAID', 'PARTIALLY_REFUNDED', 'REFUNDED')", name="ck_pharmacy_retail_invoice_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_sales.id"), nullable=False, unique=True, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PAID", index=True)


class PharmacyRetailPayment(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_payments"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uq_pharmacy_retail_payment_invoice"),
        UniqueConstraint("tenant_id", "transaction_reference", name="uq_pharmacy_retail_payment_reference"),
        CheckConstraint("status IN ('CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED')", name="ck_pharmacy_retail_payment_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_invoices.id"), nullable=False, unique=True, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CAPTURED", index=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PharmacyRetailReturn(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_returns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_pharmacy_retail_return_idempotency"),
        UniqueConstraint("tenant_id", "return_number", name="uq_pharmacy_retail_return_number"),
        CheckConstraint("classification IN ('OTC', 'EXTERNAL_PRESCRIPTION')", name="ck_pharmacy_retail_return_classification"),
        CheckConstraint("status IN ('REFUNDED', 'NON_RESTOCKABLE')", name="ck_pharmacy_retail_return_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_sales.id"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_invoices.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pharmacy_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_locations.id"), nullable=False, index=True)
    return_number: Mapped[str] = mapped_column(String(50), nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="REFUNDED", index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PharmacyRetailReturnAllocation(Base, TimestampMixin):
    __tablename__ = "pharmacy_retail_return_allocations"
    __table_args__ = (
        UniqueConstraint("return_id", "sale_allocation_id", name="uq_pharmacy_retail_return_allocation_source"),
        CheckConstraint("quantity > 0", name="ck_pharmacy_retail_return_allocation_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    return_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    sale_allocation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pharmacy_retail_sale_allocations.id"), nullable=False, index=True)
    inventory_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock_transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_transactions.id"), nullable=False, unique=True)