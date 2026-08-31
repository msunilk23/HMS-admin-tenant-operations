import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class LabTestItem(BaseModel):
    """Lab test item can reference master data or be free-text (deprecated)."""
    test_id: Optional[uuid.UUID] = None  # Reference to lab_test_master
    test: Optional[str] = None  # Free-text test name (deprecated, for backward compat)
    notes: Optional[str] = None
    
    @field_validator('test', mode='before')
    @classmethod
    def test_validator(cls, v, info):
        # Require at least test_id OR test
        if not v and not info.data.get('test_id'):
            raise ValueError('Either test_id or test must be provided')
        return v


class LabOrderCreate(BaseModel):
    visit_id: uuid.UUID
    tests: List[LabTestItem]


class LabOrderRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    tests: Optional[list] = None
    status: str
    ordered_at: datetime
    # Joined
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    result: Optional["LabResultRead"] = None

    model_config = {"from_attributes": True}


class LabResultCreate(BaseModel):
    results: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class LabResultRead(BaseModel):
    id: uuid.UUID
    lab_order_id: uuid.UUID
    results: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    report_url: Optional[str] = None
    reported_by_user_id: Optional[uuid.UUID] = None
    reported_at: datetime
    verified_by_user_id: Optional[uuid.UUID] = None
    verified_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
