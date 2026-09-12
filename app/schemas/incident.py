from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

IncidentType = Literal["fire", "flood", "intrusion", "equipment_fault", "other"]
IncidentStatus = Literal["open", "acknowledged", "resolved", "escalated"]
IncidentSeverity = Literal["low", "medium", "high", "critical"]


class EvidenceIn(BaseModel):
    device_id: Optional[str] = None
    reading_id: Optional[int] = None
    note: Optional[str] = None


class EvidenceOut(BaseModel):
    id: str
    device_id: Optional[str] = None
    reading_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentCreate(BaseModel):
    """Agent hypothesis, written via MCP create_incident."""

    type: IncidentType
    severity: IncidentSeverity = "low"
    location: dict = Field(default_factory=dict)
    summary: str
    evidence: list[EvidenceIn] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    status: Optional[IncidentStatus] = None
    severity: Optional[IncidentSeverity] = None
    note: Optional[str] = None


class IncidentOut(BaseModel):
    id: str
    type: str
    status: str
    severity: str
    location: dict
    summary: str
    metadata: dict = Field(alias="metadata_")
    opened_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    evidence: list[EvidenceOut] = Field(default_factory=list)

    model_config = {"from_attributes": True, "populate_by_name": True}
