from typing import Optional

from pydantic import BaseModel


class QueueStageSummary(BaseModel):
    waiting_count: int
    breached_count: int
    longest_wait_seconds: Optional[float] = None
    sla_threshold_seconds: int


class QueueSummaryRead(BaseModel):
    as_of: str
    waiting_for_nurse: QueueStageSummary
    waiting_for_doctor: QueueStageSummary
