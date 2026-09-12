from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import async_session
from app.main import app
from app.models.dashboard import DashboardSpec
from app.models.device import Device
from app.models.incident import Incident, IncidentEvidence
from app.models.telemetry import TelemetryReading
from tests.conftest import AUTH_HEADERS


async def _seed_device(**overrides) -> Device:
    defaults = dict(
        external_id=f"test-device-{uuid4()}",
        type="cctv",
        name="Test Camera",
        location={"building": "A", "floor": 2, "zone": "warehouse"},
        status="online",
        metadata_={"vendor": "acme"},
    )
    defaults.update(overrides)
    async with async_session() as session:
        device = Device(**defaults)
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device


async def _seed_reading(device_id, **overrides) -> TelemetryReading:
    defaults = dict(
        device_id=device_id,
        ts=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
        metric_type="video_event",
        value=1.0,
        unit=None,
        payload={"event": "smoke_detected"},
    )
    defaults.update(overrides)
    async with async_session() as session:
        reading = TelemetryReading(**defaults)
        session.add(reading)
        await session.commit()
        await session.refresh(reading)
        return reading


async def _seed_incident_with_evidence(device_id, reading_id) -> Incident:
    async with async_session() as session:
        incident = Incident(
            type="fire",
            status="open",
            severity="high",
            location={"building": "A", "floor": 2},
            summary="Smoke detected in warehouse",
            metadata_={"source": "test"},
        )
        session.add(incident)
        await session.flush()
        evidence = IncidentEvidence(
            incident_id=incident.id,
            device_id=device_id,
            reading_id=reading_id,
            note="Camera flagged smoke event",
        )
        session.add(evidence)
        await session.commit()
        await session.refresh(incident)
        return incident


async def _seed_dashboard(**overrides) -> DashboardSpec:
    defaults = dict(
        title=f"Test Dashboard {uuid4()}",
        created_by="agent",
        spec={"widgets": []},
        version=1,
    )
    defaults.update(overrides)
    async with async_session() as session:
        dashboard = DashboardSpec(**defaults)
        session.add(dashboard)
        await session.commit()
        await session.refresh(dashboard)
        return dashboard


@pytest.mark.asyncio
async def test_list_and_get_device():
    device = await _seed_device()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        list_resp = await client.get("/devices", params={"type": "cctv"})
        assert list_resp.status_code == 200
        ids = [row["id"] for row in list_resp.json()]
        assert str(device.id) in ids

        list_resp = await client.get("/devices", params={"building": "A"})
        assert list_resp.status_code == 200
        assert str(device.id) in [row["id"] for row in list_resp.json()]

        get_resp = await client.get(f"/devices/{device.id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["id"] == str(device.id)
        assert body["external_id"] == device.external_id
        assert body["metadata"] == {"vendor": "acme"}

        missing_resp = await client.get(f"/devices/{uuid4()}")
        assert missing_resp.status_code == 404

        invalid_resp = await client.get("/devices/not-a-uuid")
        assert invalid_resp.status_code == 404


@pytest.mark.asyncio
async def test_telemetry_query_and_latest():
    device = await _seed_device(type="iot")
    reading = await _seed_reading(device.id)
    later_reading = await _seed_reading(
        device.id,
        ts=datetime(2026, 9, 12, 11, 0, 0, tzinfo=timezone.utc),
        metric_type="temperature",
        value=22.5,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        resp = await client.get("/telemetry", params={"device_id": str(device.id)})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # ordered by ts desc
        assert body[0]["id"] == later_reading.id
        assert body[1]["id"] == reading.id

        resp = await client.get(
            "/telemetry", params={"device_id": str(device.id), "metric_type": "temperature"}
        )
        assert resp.status_code == 200
        assert [row["id"] for row in resp.json()] == [later_reading.id]

        resp = await client.get("/telemetry/latest", params={"device_id": str(device.id)})
        assert resp.status_code == 200
        latest_body = resp.json()
        assert len(latest_body) == 1
        assert latest_body[0]["id"] == later_reading.id

        resp = await client.get("/telemetry/latest", params={"type": "iot"})
        assert resp.status_code == 200
        assert any(row["id"] == later_reading.id for row in resp.json())


@pytest.mark.asyncio
async def test_telemetry_response_includes_quality_and_provenance_fields():
    device = await _seed_device(type="iot")
    reading = await _seed_reading(
        device.id,
        metric_type="co",
        value=3.2,
        quality="valid",
        availability="fresh",
        provenance={"source_id": "sim-dataset-7", "origin": "synthetic"},
        external_event_id="evt-abc-123",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        resp = await client.get("/telemetry", params={"device_id": str(device.id)})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        row = body[0]
        assert row["id"] == reading.id
        assert row["quality"] == "valid"
        assert row["availability"] == "fresh"
        assert row["provenance"] == {"source_id": "sim-dataset-7", "origin": "synthetic"}
        assert row["external_event_id"] == "evt-abc-123"


@pytest.mark.asyncio
async def test_incident_get_populates_evidence_and_list_returns_empty_evidence():
    device = await _seed_device(type="fire_panel")
    reading = await _seed_reading(device.id, metric_type="smoke", value=1.0)
    incident = await _seed_incident_with_evidence(device.id, reading.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        list_resp = await client.get("/incidents", params={"status": "open"})
        assert list_resp.status_code == 200
        matching = [row for row in list_resp.json() if row["id"] == str(incident.id)]
        assert len(matching) == 1
        assert matching[0]["evidence"] == []
        assert matching[0]["metadata"] == {"source": "test"}

        get_resp = await client.get(f"/incidents/{incident.id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["id"] == str(incident.id)
        assert body["summary"] == "Smoke detected in warehouse"
        assert len(body["evidence"]) == 1
        assert body["evidence"][0]["device_id"] == str(device.id)
        assert body["evidence"][0]["reading_id"] == reading.id
        assert body["evidence"][0]["note"] == "Camera flagged smoke event"

        missing_resp = await client.get(f"/incidents/{uuid4()}")
        assert missing_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_and_get_dashboard():
    dashboard = await _seed_dashboard()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        list_resp = await client.get("/dashboards")
        assert list_resp.status_code == 200
        assert str(dashboard.id) in [row["id"] for row in list_resp.json()]

        get_resp = await client.get(f"/dashboards/{dashboard.id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["title"] == dashboard.title
        assert body["spec"] == {"widgets": []}

        missing_resp = await client.get(f"/dashboards/{uuid4()}")
        assert missing_resp.status_code == 404
