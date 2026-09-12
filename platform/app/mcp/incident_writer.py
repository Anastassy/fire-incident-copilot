import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import INCIDENTS_CHANNEL, redis_client
from app.models.incident import Incident, IncidentEvidence
from app.schemas.incident import EvidenceIn, IncidentCreate, IncidentUpdate


def _evidence_event(evidence: IncidentEvidence) -> dict:
    return {
        "id": evidence.id,
        "incident_id": evidence.incident_id,
        "device_id": evidence.device_id,
        "reading_id": evidence.reading_id,
        "note": evidence.note,
        "created_at": evidence.created_at,
    }


def _incident_event(incident: Incident, evidence: list[IncidentEvidence] | None = None) -> str:
    """Full incident shape (matches IncidentOut / _incident_to_dict in app/mcp/server.py) so
    SSE consumers relaying this verbatim (see app/api/streams.py) get a complete object."""
    return json.dumps(
        {
            "id": incident.id,
            "type": incident.type,
            "status": incident.status,
            "severity": incident.severity,
            "location": incident.location,
            "summary": incident.summary,
            "metadata": incident.metadata_,
            "opened_at": incident.opened_at,
            "updated_at": incident.updated_at,
            "closed_at": incident.closed_at,
            "evidence": [_evidence_event(e) for e in evidence] if evidence is not None else [],
        },
        default=str,
    )


async def create_incident(session: AsyncSession, incident_in: IncidentCreate) -> Incident:
    """Owner: Agent C. Persist incident + evidence rows, commit, publish to Redis INCIDENTS_CHANNEL."""
    incident = Incident(
        type=incident_in.type,
        severity=incident_in.severity,
        location=incident_in.location,
        summary=incident_in.summary,
    )
    session.add(incident)
    await session.flush()

    evidence_rows: list[IncidentEvidence] = []
    for evidence_item in incident_in.evidence:
        device_id = UUID(evidence_item.device_id) if evidence_item.device_id else None
        evidence = IncidentEvidence(
            incident_id=incident.id,
            device_id=device_id,
            reading_id=evidence_item.reading_id,
            note=evidence_item.note,
        )
        session.add(evidence)
        evidence_rows.append(evidence)

    await session.commit()
    await session.refresh(incident)
    for evidence in evidence_rows:
        await session.refresh(evidence)

    await redis_client.publish(INCIDENTS_CHANNEL, _incident_event(incident, evidence_rows))

    return incident


async def update_incident(session: AsyncSession, incident_id: UUID, incident_update: IncidentUpdate) -> Incident:
    """Owner: Agent C. Apply partial update, commit, publish to Redis INCIDENTS_CHANNEL."""
    result = await session.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if incident is None:
        raise ValueError(f"Incident {incident_id} not found")

    if incident_update.status is not None:
        incident.status = incident_update.status
        if incident_update.status == "resolved":
            incident.closed_at = datetime.now(timezone.utc)

    if incident_update.severity is not None:
        incident.severity = incident_update.severity

    if incident_update.note is not None:
        metadata = dict(incident.metadata_ or {})
        notes = list(metadata.get("notes", []))
        notes.append(incident_update.note)
        metadata["notes"] = notes
        incident.metadata_ = metadata

    await session.commit()
    await session.refresh(incident)

    evidence_result = await session.execute(
        select(IncidentEvidence).where(IncidentEvidence.incident_id == incident.id)
    )
    evidence_rows = list(evidence_result.scalars().all())

    await redis_client.publish(INCIDENTS_CHANNEL, _incident_event(incident, evidence_rows))

    return incident


async def link_evidence(session: AsyncSession, incident_id: UUID, evidence_in: EvidenceIn) -> None:
    """Owner: Agent C. Append evidence row to an existing incident, commit."""
    device_id = UUID(evidence_in.device_id) if evidence_in.device_id else None
    evidence = IncidentEvidence(
        incident_id=incident_id,
        device_id=device_id,
        reading_id=evidence_in.reading_id,
        note=evidence_in.note,
    )
    session.add(evidence)
    await session.commit()
