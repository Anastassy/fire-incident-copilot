from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.incident import IncidentEvidence
from app.schemas.incident import IncidentOut
from app.services.incident_service import get_incident, list_incidents

# Owner: Agent B. GET /incidents, GET /incidents/{id} (dashboard-facing read-only).
# Writes (create/update/evidence) are MCP-only, implemented by Agent C in app/mcp/incident_writer.py.
router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentOut])
async def get_incidents(
    status: Optional[str] = None,
    type: Optional[str] = None,
    since: Optional[datetime] = None,
    session: AsyncSession = Depends(get_session),
) -> list[IncidentOut]:
    incidents = await list_incidents(session, status=status, type=type, since=since)
    # evidence intentionally left empty here to avoid an evidence query per row;
    # fully populated on the single-item GET /incidents/{id} below.
    return [
        IncidentOut.model_validate({**_incident_columns(incident), "evidence": []})
        for incident in incidents
    ]


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident_by_id(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
) -> IncidentOut:
    incident = await get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    result = await session.execute(
        select(IncidentEvidence).where(IncidentEvidence.incident_id == incident.id)
    )
    evidence_rows = result.scalars().all()
    evidence = [
        {
            "id": str(row.id),
            "device_id": str(row.device_id) if row.device_id else None,
            "reading_id": row.reading_id,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in evidence_rows
    ]

    return IncidentOut.model_validate({**_incident_columns(incident), "evidence": evidence})


def _incident_columns(incident) -> dict:
    return {
        c.key: (str(value) if isinstance(value := getattr(incident, c.key), UUID) else value)
        for c in inspect(incident).mapper.column_attrs
    }
