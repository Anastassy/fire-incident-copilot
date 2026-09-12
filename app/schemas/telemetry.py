from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.device import DeviceIn

MetricType = Literal[
    "temperature",
    "smoke",
    "water_level",
    "motion",
    "video_event",
    "heartbeat",
    "other",
    "access",
    "occupancy",
    "radio_audio",
    "system",
    "obscuration",
    "co",
    "eco2",
]

DataQuality = Literal["valid", "missing", "invalid"]

Availability = Literal["fresh", "stale", "missing", "invalid", "disconnected"]


class TelemetryIn(BaseModel):
    """Ingestion contract: one sensor event. POST /ingest/telemetry accepts this or a list of these.

    `ts` is the event start (or the only instant, for point events). `end_ts` is optional and
    only set for events with a duration (e.g. motion detected from ts to end_ts).
    """

    device: DeviceIn
    metric_type: MetricType
    ts: datetime
    end_ts: Optional[datetime] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    quality: Optional[DataQuality] = None
    availability: Optional[Availability] = None
    provenance: dict = Field(default_factory=dict)
    external_event_id: Optional[str] = None


class TelemetryOut(BaseModel):
    id: int
    device_id: str
    ts: datetime
    end_ts: Optional[datetime] = None
    metric_type: str
    value: Optional[float] = None
    unit: Optional[str] = None
    payload: dict
    quality: Optional[DataQuality] = None
    availability: Optional[Availability] = None
    provenance: dict = Field(default_factory=dict)
    external_event_id: Optional[str] = None
    ingested_at: datetime

    model_config = {"from_attributes": True}
