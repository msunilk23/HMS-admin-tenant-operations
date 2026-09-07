import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PatientRouteStepRead(BaseModel):
    id: uuid.UUID
    route_id: uuid.UUID
    visit_id: uuid.UUID
    destination: str
    source_type: Optional[str] = None
    source_record_id: Optional[uuid.UUID] = None
    source_record_ids: Optional[list[uuid.UUID]] = None
    status: str
    presentation_deadline_at: Optional[datetime] = None
    presented_at: Optional[datetime] = None
    service_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    not_presented_at: Optional[datetime] = None
    reopened_at: Optional[datetime] = None
    presentation_channel: Optional[str] = None
    outcome_reason: Optional[str] = None
    late_presentation: bool = False

    model_config = {"from_attributes": True}


class PatientRouteRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    consultation_id: Optional[uuid.UUID] = None
    patient_id: uuid.UUID
    uhid: str
    facility_id: Optional[uuid.UUID] = None
    status: str
    completed_at: Optional[datetime] = None
    steps: list[PatientRouteStepRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RoutePresentationRequest(BaseModel):
    channel: str = Field(default="RECEPTION", min_length=1, max_length=30)


class RouteOutcomeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    channel: str = Field(default="RECEPTION", min_length=1, max_length=30)