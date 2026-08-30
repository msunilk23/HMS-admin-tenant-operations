"""
Pydantic schemas for Patient and Supplier Returns - P30
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============ PATIENT RETURN SCHEMAS ============

class PatientReturnItemRead(BaseModel):
    """Patient return item response schema."""
    id: UUID
    return_id: UUID
    dispense_item_id: UUID
    medicine_product_id: Optional[UUID] = None
    inventory_batch_id: Optional[UUID] = None
    
    prescribed_quantity: Decimal
    returned_quantity: Decimal
    original_unit_price: Decimal
    return_amount: Decimal
    
    status: str
    restockable: bool
    non_restockable_reason: Optional[str] = None
    
    validated_by: Optional[UUID] = None
    validated_at: Optional[datetime] = None
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PatientReturnItemCreate(BaseModel):
    """Request schema for patient return item."""
    dispense_item_id: UUID = Field(..., description="Reference to dispensed item")
    returned_quantity: Decimal = Field(..., gt=0, description="Quantity being returned")
    restockable: Optional[bool] = Field(None, description="Whether item is restockable")
    non_restockable_reason: Optional[str] = Field(None, description="Reason if non-restockable")
    batch_allocations: Optional[list["PatientReturnBatchAllocationCreate"]] = None


class PatientReturnBatchAllocationCreate(BaseModel):
    inventory_batch_id: UUID
    returned_quantity: Decimal = Field(..., gt=0)


class PatientReturnCreate(BaseModel):
    """Create patient return request."""
    dispense_id: UUID = Field(..., description="Original dispense ID")
    return_reason: str = Field(..., min_length=10, description="Reason for return")
    package_condition: Optional[str] = Field(None, description="Condition of package")
    items: list[PatientReturnItemCreate] = Field(..., min_length=1, description="Items being returned")
    idempotency_key: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class PatientReturnValidateRequest(BaseModel):
    """Request to validate patient return."""
    items: list[dict] = Field(..., description="Items with validation status")
    # Each item should have: dispense_item_id, restockable, non_restockable_reason


class PatientReturnEligibilityAllocationRead(BaseModel):
    allocation_id: UUID
    inventory_batch_id: UUID
    batch_number: str
    expiry_date: Optional[datetime] = None
    originally_dispensed_quantity: Decimal
    previously_returned_quantity: Decimal
    remaining_returnable_quantity: Decimal


class PatientReturnEligibilityItemRead(BaseModel):
    dispense_item_id: UUID
    medicine_name: Optional[str] = None
    prescribed_quantity: Decimal
    originally_dispensed_quantity: Decimal
    previously_returned_quantity: Decimal
    remaining_returnable_quantity: Decimal
    allocations: list[PatientReturnEligibilityAllocationRead] = []


class PatientReturnEligibilityRead(BaseModel):
    dispense_id: UUID
    patient_id: UUID
    patient_name: Optional[str] = None
    visit_id: UUID
    invoice_id: Optional[UUID] = None
    prescription_id: Optional[UUID] = None
    dispense_reference: Optional[str] = None
    facility_id: UUID
    pharmacy_location_id: UUID
    items: list[PatientReturnEligibilityItemRead] = []


class PatientReturnEligibleDispenseRead(BaseModel):
    dispense_id: UUID
    patient_id: UUID
    patient_name: str
    patient_uhid: str
    visit_id: UUID
    prescription_id: UUID
    invoice_id: Optional[UUID] = None
    dispense_reference: str
    completed_at: Optional[datetime] = None


class PatientReturnListResponse(BaseModel):
    items: list[PatientReturnRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class PatientReturnRead(BaseModel):
    """Patient return response schema."""
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    pharmacy_location_id: UUID
    patient_id: UUID
    visit_id: UUID
    dispense_id: UUID
    invoice_id: Optional[UUID] = None
    
    status: str
    reference_key: str
    return_reason: str
    package_condition: Optional[str] = None
    
    total_return_quantity: Decimal
    total_return_amount: Decimal
    refunded_amount: Decimal
    
    restockable_count: int
    non_restockable_count: int
    
    requested_by: Optional[UUID] = None
    requested_at: datetime
    validated_by: Optional[UUID] = None
    validated_at: Optional[datetime] = None
    accepted_by: Optional[UUID] = None
    accepted_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    rejected_by: Optional[UUID] = None
    rejected_at: Optional[datetime] = None
    refunded_by: Optional[UUID] = None
    refunded_at: Optional[datetime] = None
    
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    items: list[PatientReturnItemRead] = []
    
    class Config:
        from_attributes = True


class PatientReturnAcceptRequest(BaseModel):
    """Request to accept validated patient return."""
    pass


class PatientReturnRejectRequest(BaseModel):
    """Request to reject patient return."""
    rejection_reason: str = Field(..., min_length=10)


# ============ SUPPLIER RETURN SCHEMAS ============

class SupplierReturnItemRead(BaseModel):
    """Supplier return item response schema."""
    id: UUID
    supplier_return_id: UUID
    inventory_batch_id: UUID
    goods_receipt_item_id: Optional[UUID] = None
    
    received_quantity: Decimal
    returned_quantity: Decimal
    unit_cost: Decimal
    return_value: Decimal
    
    stock_reduction_ledger_id: Optional[UUID] = None
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SupplierReturnItemCreate(BaseModel):
    """Request schema for supplier return item."""
    inventory_batch_id: UUID = Field(..., description="Batch being returned")
    returned_quantity: Decimal = Field(..., gt=0, description="Quantity being returned")
    unit_cost: Decimal = Field(..., ge=0, description="Cost per unit")


class SupplierReturnCreate(BaseModel):
    """Create supplier return request."""
    supplier_id: UUID = Field(..., description="Supplier ID")
    goods_receipt_id: Optional[UUID] = Field(None, description="Reference GRN")
    return_reason: str = Field(..., min_length=10, description="Reason for return")
    items: list[SupplierReturnItemCreate] = Field(..., min_length=1, description="Items being returned")
    idempotency_key: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class SupplierReturnEligibilityItemRead(BaseModel):
    inventory_batch_id: UUID
    batch_number: str
    medicine_name: Optional[str] = None
    expiry_date: Optional[datetime] = None
    available_quantity: Decimal
    original_received_quantity: Decimal
    eligible_return_quantity: Decimal
    unit_cost: Decimal
    supplier_id: UUID
    goods_receipt_id: Optional[UUID] = None
    purchase_order_id: Optional[UUID] = None


class SupplierReturnEligibilityRead(BaseModel):
    supplier_id: UUID
    supplier_name: Optional[str] = None
    goods_receipt_id: Optional[UUID] = None
    purchase_order_id: Optional[UUID] = None
    facility_id: UUID
    pharmacy_location_id: UUID
    items: list[SupplierReturnEligibilityItemRead] = []


class SupplierReturnListResponse(BaseModel):
    items: list[SupplierReturnRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class SupplierReturnRead(BaseModel):
    """Supplier return response schema."""
    id: UUID
    tenant_id: UUID
    facility_id: UUID
    pharmacy_location_id: UUID
    supplier_id: UUID
    
    purchase_order_id: Optional[UUID] = None
    goods_receipt_id: Optional[UUID] = None
    
    status: str
    reference_key: str
    return_reason: str
    
    total_return_quantity: Decimal
    total_return_value: Decimal
    
    requested_by: Optional[UUID] = None
    requested_at: datetime
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    dispatched_by: Optional[UUID] = None
    dispatched_at: Optional[datetime] = None
    received_by: Optional[UUID] = None
    received_at: Optional[datetime] = None
    
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    items: list[SupplierReturnItemRead] = []
    
    class Config:
        from_attributes = True


class SupplierReturnApproveRequest(BaseModel):
    """Request to approve supplier return."""
    pass


class SupplierReturnDispatchRequest(BaseModel):
    """Request to dispatch supplier return."""
    pass


class SupplierReturnReceiveRequest(BaseModel):
    """Request to receive supplier return."""
    received_quantity: Optional[Decimal] = Field(None, description="Actual received quantity (for partial receives)")
