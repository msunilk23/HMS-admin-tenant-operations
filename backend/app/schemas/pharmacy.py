import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PharmacyQueueRead(BaseModel):
    id: uuid.UUID
    prescription_id: uuid.UUID
    patient_id: Optional[uuid.UUID] = None
    visit_id: Optional[uuid.UUID] = None
    status: str
    notes: Optional[str] = None
    updated_at: datetime
    # Joined
    patient_name: Optional[str] = None
    medicines: Optional[list] = None      # from prescription

    model_config = {"from_attributes": True}


class PharmacyStatusUpdate(BaseModel):
    status: str   # pending | called | dispensing | dispensed | partially_dispensed | out_of_stock | cancelled
    notes: Optional[str] = None
