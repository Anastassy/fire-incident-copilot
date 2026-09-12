from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident


async def list_incidents(
    session: AsyncSession,
    status: str | None = None,
    type: str | None = None,
    since: datetime | None = None,
) -> list[Incident]:
    """Owner: Agent B (REST, dashboard-facing read). Also backs MCP list_incidents."""
    stmt = select(Incident)
    if status is not None:
        stmt = stmt.where(Incident.status == status)
    if type is not None:
        stmt = stmt.where(Incident.type == type)
    if since is not None:
        stmt = stmt.where(Incident.opened_at >= since)
    stmt = stmt.order_by(Incident.opened_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_incident(session: AsyncSession, incident_id: UUID | str) -> Incident | None:
    """Owner: Agent B (REST, dashboard-facing read). Include evidence relationship. Also backs MCP get_incident.

    Note: there is no ORM relationship from Incident to IncidentEvidence (frozen shared
    model contract), so this returns only the bare Incident row. Callers that need evidence
    populated (e.g. GET /incidents/{id}) must separately query IncidentEvidence and assemble
    the response themselves.
    """
    try:
        parsed_id = incident_id if isinstance(incident_id, UUID) else UUID(str(incident_id))
    except (ValueError, AttributeError, TypeError):
        return None
    result = await session.execute(select(Incident).where(Incident.id == parsed_id))
    return result.scalar_one_or_none()
