from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryReading
from app.services.device_service import list_devices


async def query_telemetry(
    session: AsyncSession,
    device_id: UUID | None = None,
    metric_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> list[TelemetryReading]:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP query_telemetry."""
    stmt = select(TelemetryReading)
    if device_id is not None:
        stmt = stmt.where(TelemetryReading.device_id == device_id)
    if metric_type is not None:
        stmt = stmt.where(TelemetryReading.metric_type == metric_type)
    if since is not None:
        stmt = stmt.where(TelemetryReading.ts >= since)
    if until is not None:
        stmt = stmt.where(TelemetryReading.ts <= until)
    stmt = stmt.order_by(TelemetryReading.ts.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_readings(
    session: AsyncSession,
    device_ids: list[UUID] | None = None,
    type: str | None = None,
    location: dict | None = None,
) -> list[TelemetryReading]:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP get_latest_readings."""
    if device_ids:
        target_ids = list(device_ids)
    else:
        devices = await list_devices(session, type=type, location=location)
        target_ids = [device.id for device in devices]

    latest: list[TelemetryReading] = []
    for target_id in target_ids:
        stmt = (
            select(TelemetryReading)
            .where(TelemetryReading.device_id == target_id)
            .order_by(TelemetryReading.ts.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        reading = result.scalar_one_or_none()
        if reading is not None:
            latest.append(reading)
    return latest
