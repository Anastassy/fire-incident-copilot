from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident


async def list_incidents(
    session: AsyncSession,
    status: str | None = None,
    type: str | None = None,
    since: datetime | None = None,
) -> list[Incident]:
    """Owner: Agent B (REST, dashboard-facing read). Also backs MCP list_incidents."""
    raise NotImplementedError


async def get_incident(session: AsyncSession, incident_id: UUID) -> Incident | None:
    """Owner: Agent B (REST, dashboard-facing read). Include evidence relationship. Also backs MCP get_incident."""
    raise NotImplementedError
