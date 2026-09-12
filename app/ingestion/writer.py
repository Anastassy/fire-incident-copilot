from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.telemetry import TelemetryReading
from app.schemas.device import DeviceIn
from app.schemas.telemetry import TelemetryIn


async def upsert_device_from_telemetry(session: AsyncSession, device_in: DeviceIn) -> Device:
    """Owner: Agent A. Upsert by external_id, refresh last_seen_at/status=online, commit."""
    raise NotImplementedError


async def write_telemetry_reading(session: AsyncSession, device_id: UUID, telemetry_in: TelemetryIn) -> TelemetryReading:
    """Owner: Agent A. Persist reading, commit, publish to Redis TELEMETRY_CHANNEL (app.core.redis)."""
    raise NotImplementedError
