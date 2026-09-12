import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import TELEMETRY_CHANNEL, redis_client
from app.models.device import Device
from app.models.telemetry import TelemetryReading
from app.schemas.device import DeviceIn
from app.schemas.telemetry import TelemetryIn


async def upsert_device_from_telemetry(session: AsyncSession, device_in: DeviceIn) -> Device:
    """Owner: Agent A. Upsert by external_id, refresh last_seen_at/status=online, commit."""
    result = await session.execute(select(Device).where(Device.external_id == device_in.external_id))
    device = result.scalar_one_or_none()

    if device is None:
        device = Device(
            external_id=device_in.external_id,
            type=device_in.type,
            name=device_in.name,
            location=device_in.location.model_dump(exclude_none=True),
            status="online",
        )
        session.add(device)
    else:
        device.type = device_in.type
        device.name = device_in.name
        device.location = device_in.location.model_dump(exclude_none=True)
        device.status = "online"
        device.last_seen_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(device)
    return device


async def write_telemetry_reading(session: AsyncSession, device_id: UUID, telemetry_in: TelemetryIn) -> TelemetryReading:
    """Owner: Agent A. Persist reading, commit, publish to Redis TELEMETRY_CHANNEL (app.core.redis)."""
    reading = TelemetryReading(
        device_id=device_id,
        ts=telemetry_in.ts,
        end_ts=telemetry_in.end_ts,
        metric_type=telemetry_in.metric_type,
        value=telemetry_in.value,
        unit=telemetry_in.unit,
        payload=telemetry_in.payload,
        quality=telemetry_in.quality,
        availability=telemetry_in.availability,
        provenance=telemetry_in.provenance,
        external_event_id=telemetry_in.external_event_id,
        transcript=telemetry_in.transcript,
        audio_url=telemetry_in.audio_url,
        audio_duration_ms=telemetry_in.audio_duration_ms,
    )
    session.add(reading)
    await session.commit()
    await session.refresh(reading)

    event = {
        "device_id": str(device_id),
        "metric_type": reading.metric_type,
        "ts": reading.ts.isoformat(),
        "end_ts": reading.end_ts.isoformat() if reading.end_ts else None,
        "value": reading.value,
        "unit": reading.unit,
        "payload": reading.payload,
        "quality": reading.quality,
        "availability": reading.availability,
        "provenance": reading.provenance,
        "external_event_id": reading.external_event_id,
        "transcript": reading.transcript,
        "audio_url": reading.audio_url,
        "audio_duration_ms": reading.audio_duration_ms,
    }
    await redis_client.publish(TELEMETRY_CHANNEL, json.dumps(event, default=str))

    return reading
