from datetime import datetime
import os
import re
from urllib.parse import urlsplit
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.core.db import async_session
from app.mcp import dashboard_writer, incident_writer
from app.models.incident import IncidentEvidence
from app.schemas.dashboard import DashboardCreate, DashboardUpdate
from app.schemas.incident import EvidenceIn, IncidentCreate, IncidentUpdate
from app.services import dashboard_service, device_service, incident_service, telemetry_service

# Owner: Agent C. Register tools here, thin wrappers over app/services/*:
#   list_devices, get_device, query_telemetry, get_latest_readings,
#   list_incidents, get_incident, create_incident, update_incident, link_evidence,
#   list_dashboards, get_dashboard, create_dashboard, update_dashboard
# Expose via streamable-http/SSE transport so it can be mounted or run standalone.
mcp = MCPServer("safety-platform")


def transport_security_settings() -> TransportSecuritySettings:
    """Allow the deployed MCP host without disabling DNS rebinding protection.

    MCP_PUBLIC_HOSTS accepts comma-separated DNS names with optional ports;
    MCP_PUBLIC_HOST is the single-host equivalent. Loopback remains available.
    """
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"]
    origins = [f"{scheme}://{host}" for scheme in ("http", "https") for host in hosts]
    public_hosts = os.getenv("MCP_PUBLIC_HOSTS", os.getenv("MCP_PUBLIC_HOST", "platform.aitinkerers.space"))
    for value in public_hosts.split(","):
        host = value.strip().lower()
        if not host:
            continue
        parsed = urlsplit("//" + host)
        if (not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]+)?", host)
                or parsed.hostname is None or parsed.port == 0):
            raise ValueError("MCP_PUBLIC_HOSTS must contain DNS host names with optional ports")
        hosts.append(host)
        origins.append("https://" + host)
        if parsed.port is None:
            hosts.append(host + ":443")
            origins.append("https://" + host + ":443")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(hosts)),
        allowed_origins=list(dict.fromkeys(origins)),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _device_to_dict(device) -> dict:
    return {
        "id": str(device.id),
        "external_id": device.external_id,
        "type": device.type,
        "name": device.name,
        "location": device.location,
        "status": device.status,
        "metadata": device.metadata_,
        "first_seen_at": _iso(device.first_seen_at),
        "last_seen_at": _iso(device.last_seen_at),
    }


def _reading_to_dict(reading) -> dict:
    return {
        "id": reading.id,
        "device_id": str(reading.device_id),
        "ts": _iso(reading.ts),
        "end_ts": _iso(reading.end_ts),
        "metric_type": reading.metric_type,
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
        "ingested_at": _iso(reading.ingested_at),
    }


def _incident_to_dict(incident, evidence: list | None = None) -> dict:
    return {
        "id": str(incident.id),
        "type": incident.type,
        "status": incident.status,
        "severity": incident.severity,
        "location": incident.location,
        "summary": incident.summary,
        "metadata": incident.metadata_,
        "opened_at": _iso(incident.opened_at),
        "updated_at": _iso(incident.updated_at),
        "closed_at": _iso(incident.closed_at),
        "evidence": [_evidence_to_dict(e) for e in evidence] if evidence is not None else [],
    }


def _evidence_to_dict(evidence: IncidentEvidence) -> dict:
    return {
        "id": str(evidence.id),
        "incident_id": str(evidence.incident_id),
        "device_id": str(evidence.device_id) if evidence.device_id else None,
        "reading_id": evidence.reading_id,
        "note": evidence.note,
        "created_at": _iso(evidence.created_at),
    }


def _dashboard_to_dict(dashboard) -> dict:
    return {
        "id": str(dashboard.id),
        "title": dashboard.title,
        "created_by": dashboard.created_by,
        "spec": dashboard.spec,
        "version": dashboard.version,
        "created_at": _iso(dashboard.created_at),
        "updated_at": _iso(dashboard.updated_at),
    }


async def _get_incident_evidence(session, incident_id: UUID) -> list[IncidentEvidence]:
    from sqlalchemy import select

    result = await session.execute(
        select(IncidentEvidence).where(IncidentEvidence.incident_id == incident_id)
    )
    return list(result.scalars().all())


# --- Device tools -----------------------------------------------------------


@mcp.tool()
async def list_devices(type: str | None = None, status: str | None = None) -> list[dict]:
    """List devices, optionally filtered by type and/or status."""
    async with async_session() as session:
        devices = await device_service.list_devices(session, type=type, status=status)
        return [_device_to_dict(d) for d in devices]


@mcp.tool()
async def get_device(device_id: str) -> dict | None:
    """Get a single device by id."""
    async with async_session() as session:
        device = await device_service.get_device(session, device_id)
        return _device_to_dict(device) if device is not None else None


# --- Telemetry tools ---------------------------------------------------------


@mcp.tool()
async def query_telemetry(
    device_id: str | None = None,
    metric_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query telemetry readings, optionally filtered by device, metric type, and time range."""
    async with async_session() as session:
        parsed_device_id = UUID(device_id) if device_id else None
        parsed_since = datetime.fromisoformat(since) if since else None
        parsed_until = datetime.fromisoformat(until) if until else None
        readings = await telemetry_service.query_telemetry(
            session,
            device_id=parsed_device_id,
            metric_type=metric_type,
            since=parsed_since,
            until=parsed_until,
            limit=limit,
        )
        return [_reading_to_dict(r) for r in readings]


@mcp.tool()
async def get_latest_readings(
    device_ids: list[str] | None = None, type: str | None = None
) -> list[dict]:
    """Get the latest reading per device, optionally filtered by device ids or device type."""
    async with async_session() as session:
        parsed_ids = [UUID(d) for d in device_ids] if device_ids else None
        readings = await telemetry_service.get_latest_readings(
            session, device_ids=parsed_ids, type=type
        )
        return [_reading_to_dict(r) for r in readings]


# --- Incident tools -----------------------------------------------------------


@mcp.tool()
async def list_incidents(
    status: str | None = None, type: str | None = None, since: str | None = None
) -> list[dict]:
    """List incidents, optionally filtered by status, type, and opened-since timestamp."""
    async with async_session() as session:
        parsed_since = datetime.fromisoformat(since) if since else None
        incidents = await incident_service.list_incidents(
            session, status=status, type=type, since=parsed_since
        )
        return [_incident_to_dict(i) for i in incidents]


@mcp.tool()
async def get_incident(incident_id: str) -> dict | None:
    """Get a single incident by id, including its linked evidence."""
    async with async_session() as session:
        incident = await incident_service.get_incident(session, incident_id)
        if incident is None:
            return None
        evidence = await _get_incident_evidence(session, incident.id)
        return _incident_to_dict(incident, evidence)


@mcp.tool()
async def create_incident(
    type: str,
    severity: str,
    location: dict,
    summary: str,
    evidence: list[dict] | None = None,
) -> dict:
    """Create a new incident hypothesis, optionally with supporting evidence."""
    async with async_session() as session:
        incident_in = IncidentCreate(
            type=type,
            severity=severity,
            location=location,
            summary=summary,
            evidence=[EvidenceIn(**e) for e in (evidence or [])],
        )
        incident = await incident_writer.create_incident(session, incident_in)
        evidence_rows = await _get_incident_evidence(session, incident.id)
        return _incident_to_dict(incident, evidence_rows)


@mcp.tool()
async def update_incident(
    incident_id: str,
    status: str | None = None,
    severity: str | None = None,
    note: str | None = None,
) -> dict:
    """Update an incident's status/severity, or append a note."""
    async with async_session() as session:
        incident_update = IncidentUpdate(status=status, severity=severity, note=note)
        incident = await incident_writer.update_incident(
            session, UUID(incident_id), incident_update
        )
        evidence_rows = await _get_incident_evidence(session, incident.id)
        return _incident_to_dict(incident, evidence_rows)


@mcp.tool()
async def link_evidence(
    incident_id: str,
    device_id: str | None = None,
    reading_id: int | None = None,
    note: str | None = None,
) -> dict:
    """Link a piece of evidence (device reading and/or note) to an existing incident."""
    async with async_session() as session:
        evidence_in = EvidenceIn(device_id=device_id, reading_id=reading_id, note=note)
        await incident_writer.link_evidence(session, UUID(incident_id), evidence_in)
        incident = await incident_service.get_incident(session, incident_id)
        evidence_rows = await _get_incident_evidence(session, UUID(incident_id))
        return _incident_to_dict(incident, evidence_rows)


# --- Dashboard tools -----------------------------------------------------------


@mcp.tool()
async def create_dashboard(title: str, spec: dict, created_by: str = "agent") -> dict:
    """Create a new custom dashboard spec for the operator dashboard app to pick up."""
    async with async_session() as session:
        dashboard_in = DashboardCreate(title=title, spec=spec, created_by=created_by)
        dashboard = await dashboard_writer.create_dashboard(session, dashboard_in)
        return _dashboard_to_dict(dashboard)


@mcp.tool()
async def update_dashboard(
    dashboard_id: str, title: str | None = None, spec: dict | None = None
) -> dict:
    """Update an existing dashboard's title and/or spec, bumping its version."""
    async with async_session() as session:
        dashboard_update = DashboardUpdate(title=title, spec=spec)
        dashboard = await dashboard_writer.update_dashboard(
            session, UUID(dashboard_id), dashboard_update
        )
        return _dashboard_to_dict(dashboard)


@mcp.tool()
async def list_dashboards() -> list[dict]:
    """List all dashboard specs."""
    async with async_session() as session:
        dashboards = await dashboard_service.list_dashboards(session)
        return [_dashboard_to_dict(d) for d in dashboards]


@mcp.tool()
async def get_dashboard(dashboard_id: str) -> dict | None:
    """Get a single dashboard spec by id."""
    async with async_session() as session:
        dashboard = await dashboard_service.get_dashboard(session, dashboard_id)
        return _dashboard_to_dict(dashboard) if dashboard is not None else None


# --- Standalone entrypoint ----------------------------------------------------
#
# Run directly with stdio transport (e.g. for the MCP inspector):
#   .venv/bin/python -m app.mcp.server
#
# The installed mcp SDK (2.2.0, MCPServer) also exposes an ASGI app for
# streamable-http transport via `mcp.streamable_http_app()`. To serve it
# alongside the FastAPI app instead of running it standalone, mount it in
# app/main.py (NOT edited here — left for the orchestrator):
#
#   from app.mcp.server import mcp
#   app.mount("/mcp-server", mcp.streamable_http_app())
#
# Note: streamable_http_app() returns a Starlette app with its own lifespan
# (session manager) that FastAPI must run — when mounting, wrap FastAPI's
# lifespan to also enter `mcp.session_manager.run()`, per the mcp SDK docs.
if __name__ == "__main__":
    mcp.run(transport="stdio")
