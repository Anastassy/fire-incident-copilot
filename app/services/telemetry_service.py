from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryReading


async def query_telemetry(
    session: AsyncSession,
    device_id: UUID | None = None,
    metric_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> list[TelemetryReading]:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP query_telemetry."""
    raise NotImplementedError


async def get_latest_readings(
    session: AsyncSession,
    device_ids: list[UUID] | None = None,
    type: str | None = None,
    location: dict | None = None,
) -> list[TelemetryReading]:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP get_latest_readings."""
    raise NotImplementedError
