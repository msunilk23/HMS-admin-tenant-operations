import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentVersionRead(BaseModel):
    id: uuid.UUID
    document_type: str
    parent_id: uuid.UUID
    version: int
    checksum_sha256: str
    file_size_bytes: int
    is_current: bool
    generated_by_user_id: Optional[uuid.UUID] = None
    generated_by_service: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
