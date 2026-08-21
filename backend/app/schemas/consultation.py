import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, validator


class ConsultationCreate(BaseModel):
    visit_id: uuid.UUID
    status: Literal["draft", "in_progress", "completed", "amended"] = "draft"
    chief_complaint: Optional[str] = None
    history: Optional[str] = None
    examination: Optional[str] = None
    # e.g. [{"code": "J06.9", "description": "Acute upper respiratory infection"}]
    diagnosis_icd10: Optional[List[Dict[str, Any]]] = None
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


class ConsultationUpdate(BaseModel):
    status: Optional[Literal["draft", "in_progress", "completed", "amended"]] = None
    chief_complaint: Optional[str] = None
    history: Optional[str] = None
    examination: Optional[str] = None
    diagnosis_icd10: Optional[List[Dict[str, Any]]] = None
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


class ConsultationRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    status: str = "draft"
    chief_complaint: Optional[str] = None
    history: Optional[str] = None
    examination: Optional[str] = None
    diagnosis_icd10: Optional[List[Dict[str, Any]]] = None
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
        return v
