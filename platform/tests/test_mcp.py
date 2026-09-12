from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.db import async_session
from app.mcp.server import (
    create_dashboard,
    create_incident,
    get_dashboard,
    get_incident,
    get_latest_readings,
    link_evidence,
    query_telemetry,
    update_dashboard,
    update_incident,
)
from app.models.device import Device
from app.models.telemetry import TelemetryReading


@pytest.mark.asyncio
async def test_create_and_get_incident_round_trip():
    created = await create_incident(
        type="fire",
        severity="high",
        location={"building": "A", "floor": 3},
        summary="Smoke detected near loading dock",
        evidence=[{"note": "initial hypothesis, no device yet"}],
    )

    assert created["type"] == "fire"
    assert created["severity"] == "high"
    assert created["status"] == "open"
    assert created["summary"] == "Smoke detected near loading dock"
    assert len(created["evidence"]) == 1
    assert created["evidence"][0]["note"] == "initial hypothesis, no device yet"

    fetched = await get_incident(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["summary"] == "Smoke detected near loading dock"
    assert len(fetched["evidence"]) == 1

    linked = await link_evidence(
        incident_id=created["id"], note="follow-up evidence from second camera"
    )
    assert len(linked["evidence"]) == 2

    updated = await update_incident(
        incident_id=created["id"], status="resolved", note="false alarm, confirmed clear"
    )
    assert updated["status"] == "resolved"
    assert updated["closed_at"] is not None
    assert "false alarm, confirmed clear" in updated["metadata"]["notes"]

    refetched = await get_incident(created["id"])
    assert refetched["status"] == "resolved"
    assert len(refetched["evidence"]) == 2


@pytest.mark.asyncio
async def test_missing_incident_raises_value_error():
    from uuid import uuid4

    with pytest.raises(ValueError):
        await update_incident(incident_id=str(uuid4()), status="acknowledged")


@pytest.mark.asyncio
async def test_create_and_get_dashboard_round_trip():
    created = await create_dashboard(
        title="Warehouse Overview",
        spec={"widgets": [{"type": "map"}]},
        created_by="agent",
    )

    assert created["title"] == "Warehouse Overview"
    assert created["version"] == 1
    assert created["spec"] == {"widgets": [{"type": "map"}]}

    fetched = await get_dashboard(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Warehouse Overview"

    updated = await update_dashboard(
        dashboard_id=created["id"],
        title="Warehouse Overview (updated)",
        spec={"widgets": [{"type": "map"}, {"type": "chart"}]},
    )
    assert updated["version"] == 2
    assert updated["title"] == "Warehouse Overview (updated)"
    assert len(updated["spec"]["widgets"]) == 2

    refetched = await get_dashboard(created["id"])
    assert refetched["version"] == 2
    assert refetched["title"] == "Warehouse Overview (updated)"


@pytest.mark.asyncio
async def test_query_telemetry_and_latest_readings_include_quality_and_provenance():
    async with async_session() as session:
        device = Device(
            external_id=f"test-mcp-{uuid4()}",
            type="iot",
            location={"building": "A"},
            status="online",
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)

        reading = TelemetryReading(
            device_id=device.id,
            ts=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            metric_type="co",
            value=3.2,
            unit="ppm",
            quality="valid",
            availability="fresh",
            provenance={"source_id": "sim-dataset-7", "origin": "synthetic"},
            external_event_id="evt-abc-123",
        )
        session.add(reading)
        await session.commit()
        await session.refresh(reading)

    results = await query_telemetry(device_id=str(device.id))
    assert len(results) == 1
    row = results[0]
    assert row["quality"] == "valid"
    assert row["availability"] == "fresh"
    assert row["provenance"] == {"source_id": "sim-dataset-7", "origin": "synthetic"}
    assert row["external_event_id"] == "evt-abc-123"

    latest = await get_latest_readings(device_ids=[str(device.id)])
    assert len(latest) == 1
    assert latest[0]["quality"] == "valid"
    assert latest[0]["external_event_id"] == "evt-abc-123"
