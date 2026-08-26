import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator, validator


class DiagnosisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Optional[str] = Field(None, min_length=1)
    description: str = Field(..., min_length=1)
    master_id: Optional[uuid.UUID] = None
    free_text: bool = False

    @model_validator(mode="after")
    def validate_kind(self):
        if not self.description.strip():
            raise ValueError("Diagnosis description cannot be blank")
        if self.free_text:
            if self.code is not None or self.master_id is not None:
                raise ValueError("Free-text diagnoses must not include code or master_id")
        elif not self.code or not self.code.strip():
            raise ValueError("Controlled ICD-10 diagnosis requires a code")
        elif self.master_id is None:
            raise ValueError("Controlled ICD-10 diagnosis requires a master_id")
        return self


class ConsultationCreate(BaseModel):
    visit_id: uuid.UUID
    status: Literal["draft", "in_progress", "completed", "amended"] = "draft"
    chief_complaint: Optional[str] = None
    history: Optional[str] = None
    examination: Optional[str] = None
    # e.g. [{"code": "J06.9", "description": "Acute upper respiratory infection"}]
    diagnosis_icd10: Optional[List[DiagnosisInput]] = None
    free_text_diagnosis_reason: Optional[str] = None

    @validator("diagnosis_icd10", pre=True)
    def empty_icd_to_none(cls, v):
        if v in (None, "", "null"): return None
        if v == []: return None
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                if parsed == []:
                    return None
                return parsed
            except Exception:
                return None
        if isinstance(v, list) and all(
            (not d or (isinstance(d, dict) and not d.get("code") and not d.get("description"))) for d in v
        ):
            return None
        return v
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None

    @model_validator(mode="after")
    def require_free_text_reason(self):
        if any(item.free_text or (item.code or "").upper() == "FREE_TEXT" for item in (self.diagnosis_icd10 or [])) and not (self.free_text_diagnosis_reason or "").strip():
            raise ValueError("Free-text diagnosis requires a clinical reason")
        return self


class ConsultationUpdate(BaseModel):
    status: Optional[Literal["draft", "in_progress", "completed", "amended"]] = None
    chief_complaint: Optional[str] = None
    history: Optional[str] = None
    examination: Optional[str] = None
    diagnosis_icd10: Optional[List[DiagnosisInput]] = None
    free_text_diagnosis_reason: Optional[str] = None

    @validator("diagnosis_icd10", pre=True)
    def empty_icd_to_none(cls, v):
        if v in (None, "", "null"): return None
        if v == []: return None
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                if parsed == []:
                    return None
                return parsed
            except Exception:
                return None
        if isinstance(v, list) and all(
            (not d or (isinstance(d, dict) and not d.get("code") and not d.get("description"))) for d in v
        ):
            return None
        return v
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None

    @model_validator(mode="after")
    def require_free_text_reason(self):
        if any(item.free_text or (item.code or "").upper() == "FREE_TEXT" for item in (self.diagnosis_icd10 or [])) and not (self.free_text_diagnosis_reason or "").strip():
            raise ValueError("Free-text diagnosis requires a clinical reason")
        return self


class ConsultationRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    status: str = "draft"
    chief_complaint: Optional[str] = None
    history: Optional[str] = None
    examination: Optional[str] = None
    diagnosis_icd10: Optional[List[DiagnosisInput]] = None
    free_text_diagnosis_reason: Optional[str] = None
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    amended_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @validator("diagnosis_icd10", pre=True)
    def normalize_empty_icd(cls, v):
        """Convert empty arrays and string arrays to None for response."""
        if v in (None, "", "null"): 
            return None
        if v == [] or v == "[]": 
            return None
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                if parsed == []:
                    return None
                return parsed
            except Exception:
                return None
        if isinstance(v, list) and len(v) == 0:
            return None
        # Normalize legacy persisted free-text sentinel data on reads.
        if isinstance(v, list):
            return [
                {"description": item.get("description", ""), "free_text": True}
                if isinstance(item, dict) and str(item.get("code", "")).upper() == "FREE_TEXT"
                else item
                for item in v
            ]
        return v
