from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.schemas.incident import EvidenceIn, IncidentCreate, IncidentUpdate


async def create_incident(session: AsyncSession, incident_in: IncidentCreate) -> Incident:
    """Owner: Agent C. Persist incident + evidence rows, commit, publish to Redis INCIDENTS_CHANNEL."""
    raise NotImplementedError


async def update_incident(session: AsyncSession, incident_id: UUID, incident_update: IncidentUpdate) -> Incident:
    """Owner: Agent C. Apply partial update, commit, publish to Redis INCIDENTS_CHANNEL."""
    raise NotImplementedError


async def link_evidence(session: AsyncSession, incident_id: UUID, evidence_in: EvidenceIn) -> None:
    """Owner: Agent C. Append evidence row to an existing incident, commit."""
    raise NotImplementedError
