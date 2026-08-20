import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


AlertType = Literal["allergy", "clinical"]
AlertSeverity = Literal["critical", "high", "medium", "low"]


class ClinicalAlertCreate(BaseModel):
    patient_id: uuid.UUID
    alert_type: AlertType = "allergy"
    severity: AlertSeverity = "critical"
    description: str = Field(min_length=1, max_length=2000)


class ClinicalAlertRead(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    alert_type: str
    severity: str
    description: str
    is_active: bool
    created_by_user_id: uuid.UUID
    resolved_by_user_id: Optional[uuid.UUID] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
