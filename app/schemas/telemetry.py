from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.device import DeviceIn

MetricType = Literal[
    "temperature", "smoke", "water_level", "motion", "video_event", "heartbeat", "other"
]


class TelemetryIn(BaseModel):
    """Ingestion contract: one sensor event. POST /ingest/telemetry accepts this or a list of these."""

    device: DeviceIn
    metric_type: MetricType
    ts: datetime
    value: Optional[float] = None
    unit: Optional[str] = None
    payload: dict = Field(default_factory=dict)


class TelemetryOut(BaseModel):
    id: int
    device_id: str
    ts: datetime
    metric_type: str
    value: Optional[float] = None
    unit: Optional[str] = None
    payload: dict
    ingested_at: datetime

    model_config = {"from_attributes": True}
