import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


_CHANNELS = {"qr", "sms", "whatsapp", "kiosk", "staff"}


class FeedbackCreate(BaseModel):
    visit_id: uuid.UUID
    rating: int
    comments: Optional[str] = None
    channel: str = "staff"

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("rating must be between 1 and 5")
        return value

    @field_validator("channel")
    @classmethod
    def valid_channel(cls, value: str) -> str:
        if value not in _CHANNELS:
            raise ValueError("channel must be qr, sms, whatsapp, kiosk, or staff")
        return value


class FeedbackRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    rating: Optional[int] = None
    comments: Optional[str] = None
    channel: str
    submitted_at: Optional[datetime] = None
    link_sent_at: datetime

    model_config = {"from_attributes": True}
