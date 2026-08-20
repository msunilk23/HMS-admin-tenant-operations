import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NurseDepartmentAssign(BaseModel):
    user_id: uuid.UUID        # nurse's user_id (public.users.id)
    department_id: uuid.UUID


class NurseDepartmentRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    department_id: uuid.UUID
    assigned_at: datetime
    assigned_by: uuid.UUID
    # Joined
    nurse_name: Optional[str] = None
    department_name: Optional[str] = None

    model_config = {"from_attributes": True}
