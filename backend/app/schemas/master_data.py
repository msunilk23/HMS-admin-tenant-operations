import uuid
from decimal import Decimal
from datetime import date
from typing import Literal, Optional
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


class GenericMedicineRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    therapeutic_class: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


class GenericMedicineCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    therapeutic_class: Optional[str] = Field(default=None, max_length=100)


class GenericMedicineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    therapeutic_class: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class GenericMedicineImportItem(GenericMedicineCreate):
    pass


class DosageFormRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    calculation_type: Literal["UNIT", "LIQUID", "PRN", "MANUAL"]
    description: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


class DosageFormCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    calculation_type: Literal["UNIT", "LIQUID", "PRN", "MANUAL"]
    description: Optional[str] = None


class DosageFormUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    calculation_type: Optional[Literal["UNIT", "LIQUID", "PRN", "MANUAL"]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DosageFormImportItem(DosageFormCreate):
    pass


class RouteRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


class RouteCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RouteImportItem(RouteCreate):
    pass


class ManufacturerRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    gstin: Optional[str] = None
    country: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


class ManufacturerCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    gstin: Optional[str] = Field(default=None, max_length=15)
    country: Optional[str] = Field(default=None, max_length=100)


class ManufacturerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    gstin: Optional[str] = Field(default=None, max_length=15)
    country: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class ManufacturerImportItem(ManufacturerCreate):
    pass


class MedicineProductRead(BaseModel):
    id: uuid.UUID
    code: str
    generic_medicine_id: uuid.UUID
    brand_name: Optional[str] = None
    strength: Optional[str] = None
    unit: Optional[str] = None
    dosage_form_id: uuid.UUID
    default_route_id: Optional[uuid.UUID] = None
    manufacturer_id: Optional[uuid.UUID] = None
    composition: Optional[str] = None
    hsn_code: Optional[str] = None
    gst_rate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    schedule_category: Optional[str] = None
    is_controlled_drug: bool
    requires_prescription: bool
    is_active: bool
    model_config = {"from_attributes": True}


class MedicineProductCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    generic_medicine_id: uuid.UUID
    brand_name: Optional[str] = Field(default=None, max_length=200)
    strength: Optional[str] = Field(default=None, max_length=100)
    unit: Optional[str] = Field(default=None, max_length=50)
    dosage_form_id: uuid.UUID
    default_route_id: Optional[uuid.UUID] = None
    manufacturer_id: Optional[uuid.UUID] = None
    composition: Optional[str] = None
    hsn_code: Optional[str] = Field(default=None, max_length=20)
    gst_rate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    schedule_category: Optional[str] = Field(default=None, max_length=50)
    is_controlled_drug: bool = False
    requires_prescription: bool = True


class MedicineProductUpdate(BaseModel):
    generic_medicine_id: Optional[uuid.UUID] = None
    brand_name: Optional[str] = Field(default=None, max_length=200)
    strength: Optional[str] = Field(default=None, max_length=100)
    unit: Optional[str] = Field(default=None, max_length=50)
    dosage_form_id: Optional[uuid.UUID] = None
    default_route_id: Optional[uuid.UUID] = None
    manufacturer_id: Optional[uuid.UUID] = None
    composition: Optional[str] = None
    hsn_code: Optional[str] = Field(default=None, max_length=20)
    gst_rate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    schedule_category: Optional[str] = Field(default=None, max_length=50)
    is_controlled_drug: Optional[bool] = None
    requires_prescription: Optional[bool] = None
    is_active: Optional[bool] = None


class MedicineProductImportItem(MedicineProductCreate):
    pass


class HospitalFormularyRead(BaseModel):
    id: uuid.UUID
    medicine_product_id: uuid.UUID
    department_id: uuid.UUID
    is_approved: bool
    is_preferred: bool
    is_prescribable: bool
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: bool
    model_config = {"from_attributes": True}


class HospitalFormularyCreate(BaseModel):
    medicine_product_id: uuid.UUID
    department_id: uuid.UUID
    is_approved: bool = False
    is_preferred: bool = False
    is_prescribable: bool = True
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None


class HospitalFormularyUpdate(BaseModel):
    is_approved: Optional[bool] = None
    is_preferred: Optional[bool] = None
    is_prescribable: Optional[bool] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: Optional[bool] = None


class HospitalFormularyImportItem(HospitalFormularyCreate):
    pass


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


class LabTestMasterRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: Optional[str] = None
    sample_type: Optional[str] = None
    description: Optional[str] = None
    price: float
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}


class LabTestMasterCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    sample_type: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    price: float = Field(ge=0.0)
    unit: Optional[str] = Field(default=None, max_length=50)
    reference_range: Optional[str] = Field(default=None, max_length=200)


class LabTestMasterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    sample_type: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0.0)
    unit: Optional[str] = Field(default=None, max_length=50)
    reference_range: Optional[str] = Field(default=None, max_length=200)
    is_active: Optional[bool] = None


class LabTestMasterImportItem(LabTestMasterCreate):
    pass
