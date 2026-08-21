import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

# Clinically plausible ranges — reject obviously wrong/dangerous data entry.
# (min, max) inclusive.
_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (30.0, 45.0),        # Celsius
    "pulse": (20, 300),                 # bpm
    "respiratory_rate": (4, 80),        # breaths/min
    "bp_systolic": (40, 300),           # mmHg
    "bp_diastolic": (20, 200),          # mmHg
    "spo2": (1, 100),                   # %
    "pain_score": (0, 10),              # 0-10 scale
    "height": (20.0, 275.0),            # cm
    "weight": (0.5, 500.0),             # kg
    "blood_glucose": (10.0, 800.0),     # mg/dL
}


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

    @field_validator(
        "temperature", "pulse", "respiratory_rate", "bp_systolic", "bp_diastolic",
        "spo2", "pain_score", "height", "weight", "blood_glucose",
    )
    @classmethod
    def validate_clinical_range(cls, value, info):
        if value is None:
            return value
        lo, hi = _RANGES[info.field_name]
        if not (lo <= value <= hi):
            raise ValueError(f"{info.field_name} must be between {lo} and {hi}.")
        return value

    @model_validator(mode="after")
    def validate_known_no_allergies(self):
        allergy_text = (self.allergies or "").strip()
        has_real_allergy = bool(allergy_text) and allergy_text.lower() not in {"none", "nil", "no known allergies", "nka"}
        if self.known_no_allergies and has_real_allergy:
            raise ValueError(
                "Known No Allergies (KNA) cannot be selected together with a specific allergy. "
                "Clear the allergy text or uncheck KNA."
            )
        if has_real_allergy and self.known_no_allergies is True:
            raise ValueError("An entered allergy requires Known No Allergies to be unchecked.")
        # Normalize: KNA selected with no/placeholder text -> canonical "None".
        if self.known_no_allergies and not allergy_text:
            self.allergies = "None"
        return self

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
            self.general_condition,
            self.level_of_consciousness,
            self.nurse_notes,
        ]
        if any(value is None for value in required):
            raise ValueError("Completed pre-vitals require all clinical observations and notes.")
        if self.known_no_allergies is None and not (self.allergies or "").strip():
            raise ValueError("Allergies must be entered, or Known No Allergies must be selected.")
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
