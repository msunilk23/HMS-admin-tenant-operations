import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class VitalsCreate(BaseModel):
    visit_id: uuid.UUID
    temperature: Optional[float] = None
    pulse: Optional[int] = None
    respiratory_rate: Optional[int] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    spo2: Optional[int] = None
    pain_score: Optional[int] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    blood_glucose: Optional[float] = None
    chief_complaint: Optional[str] = None
    allergies: Optional[str] = None
    known_no_allergies: Optional[bool] = None
    general_condition: Optional[str] = None
    level_of_consciousness: Optional[str] = None
    nurse_notes: Optional[str] = None
    status: Literal["draft", "completed"] = "draft"

    @model_validator(mode="after")
    def validate_required_for_completion(self):
        if self.status != "completed":
            return self
        required = [
            self.temperature,
            self.pulse,
            self.respiratory_rate,
            self.bp_systolic,
            self.bp_diastolic,
            self.spo2,
            self.pain_score,
            self.height,
            self.weight,
            self.blood_glucose,
            self.chief_complaint,
            self.allergies,
            self.general_condition,
            self.level_of_consciousness,
            self.nurse_notes,
        ]
        if any(value is None for value in required):
            raise ValueError("Completed pre-vitals require all clinical observations and notes.")
        return self


class VitalsRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    temperature: Optional[float] = None
    pulse: Optional[int] = None
    respiratory_rate: Optional[int] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    spo2: Optional[int] = None
    pain_score: Optional[int] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    bmi: Optional[float] = None
    blood_glucose: Optional[float] = None
    chief_complaint: Optional[str] = None
    allergies: Optional[str] = None
    known_no_allergies: Optional[bool] = None
    general_condition: Optional[str] = None
    level_of_consciousness: Optional[str] = None
    nurse_notes: Optional[str] = None
    status: str = "draft"
    recorded_by_user_id: uuid.UUID
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    recorded_at: datetime

    model_config = {"from_attributes": True}
