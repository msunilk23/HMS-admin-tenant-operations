from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CurrencyAmount(BaseModel):
    currency: str
    amount: Decimal


class PharmacyDashboardMetadata(BaseModel):
    business_date: date
    timezone: str
    facility_id: UUID
    pharmacy_location_id: UUID | None = None
    generated_at: datetime
    currencies: list[str]


class PharmacyDashboardCards(BaseModel):
    sales: dict[str, Any]
    prescriptions_pending: int
    dispensed_today: dict[str, Any]
    purchases_today: dict[str, Any]
    patient_returns_today: dict[str, Any]
    supplier_returns_today: dict[str, Any]
    stock_adjustments_today: dict[str, Any]
    low_stock_items: int
    out_of_stock_items: int
    expiring_stock: dict[str, int]
    inventory_valuation: dict[str, Any]
    outside_purchases: dict[str, Any]


class PharmacyDashboardRead(BaseModel):
    metadata: PharmacyDashboardMetadata
    cards: PharmacyDashboardCards
    financial_data_visible: bool


class PharmacyCapabilityRead(BaseModel):
    permissions: list[str]


class PharmacyAlertRead(BaseModel):
    id: UUID
    pharmacy_location_id: UUID | None
    alert_type: str
    severity: str
    status: str
    subject_type: str
    subject_key: str
    subject_data: dict[str, Any]
    title: str
    message: str
    condition_data: dict[str, Any]
    first_detected_at: datetime
    last_evaluated_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class PharmacyAlertList(BaseModel):
    items: list[PharmacyAlertRead]
    total: int
    page: int
    page_size: int


class AlertAcknowledgeRequest(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class AlertConfigurationWrite(BaseModel):
    pharmacy_location_id: UUID | None = None
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0)
    expiry_horizon_days: int = Field(default=90, ge=1, le=366)
    high_value_thresholds: dict[str, Decimal] = Field(default_factory=lambda: {"INR": Decimal("5000.00")})
    quantity_percentage_threshold: Decimal = Field(default=Decimal("10"), ge=0)
    repeated_event_count: int = Field(default=2, ge=1)
    lookback_days: int = Field(default=90, ge=1, le=3660)
    version: int = Field(default=1, ge=1)


class AlertConfigurationRead(AlertConfigurationWrite):
    id: UUID | None = None
    tenant_id: UUID
    facility_id: UUID | None
    scope: Literal["location", "facility", "tenant", "default"]
    effective_from: Literal["location", "facility", "tenant", "default"]
    updated_at: datetime | None = None


class PharmacyReportRead(BaseModel):
    report: str
    metadata: PharmacyDashboardMetadata
    filters: dict[str, Any]
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
