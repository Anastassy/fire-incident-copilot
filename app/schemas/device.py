from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

DeviceType = Literal["cctv", "iot", "fire_panel", "alarm", "water_sensor", "other"]
DeviceStatus = Literal["online", "offline", "fault"]


class DeviceLocation(BaseModel):
    building: Optional[str] = None
    floor: Optional[int] = None
    zone: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class DeviceIn(BaseModel):
    """Device envelope sent alongside a telemetry event; upserted by external_id."""

    external_id: str
    type: DeviceType
    name: Optional[str] = None
    location: DeviceLocation = Field(default_factory=DeviceLocation)


class DeviceOut(BaseModel):
    id: str
    external_id: str
    type: str
    name: Optional[str] = None
    location: dict
    status: str
    metadata: dict = Field(alias="metadata_")
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
