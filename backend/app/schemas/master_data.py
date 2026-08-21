import uuid
from typing import Optional
from pydantic import BaseModel, Field


class ICD10Read(BaseModel):
    id: uuid.UUID
    code: str
    description: str
    is_active: bool
    model_config = {"from_attributes": True}


class ICD10ImportItem(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1)


class MedicineRead(BaseModel):
    id: uuid.UUID
    generic_name: str
    brand_name: Optional[str] = None
    strength: Optional[str] = None
    dosage_form: Optional[str] = None
    instructions: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


class MedicineImportItem(BaseModel):
    generic_name: str = Field(min_length=1, max_length=200)
    brand_name: Optional[str] = None
    strength: Optional[str] = None
    dosage_form: Optional[str] = None
    instructions: Optional[str] = None
