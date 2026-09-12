from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import async_session
from app.main import app
from app.models.device import Device
from app.models.telemetry import TelemetryReading
from tests.conftest import AUTH_HEADERS


@pytest.mark.asyncio
async def test_ingest_telemetry_persists_device_and_reading():
    external_id = f"test-{uuid4()}"
    payload = {
        "device": {
            "external_id": external_id,
            "type": "cctv",
            "location": {"building": "A", "floor": 2, "zone": "warehouse"},
        },
        "metric_type": "video_event",
        "ts": "2026-09-12T10:00:00Z",
        "payload": {"event": "smoke_detected", "confidence": 0.87},
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.post("/ingest/telemetry", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ingested": 1}

    async with async_session() as session:
        result = await session.execute(select(Device).where(Device.external_id == external_id))
        device = result.scalar_one_or_none()
        assert device is not None
        assert device.type == "cctv"
        assert device.status == "online"
        assert device.location["building"] == "A"

        result = await session.execute(
            select(TelemetryReading).where(TelemetryReading.device_id == device.id)
        )
        readings = result.scalars().all()
        assert len(readings) == 1
        reading = readings[0]
        assert reading.metric_type == "video_event"
        assert reading.payload["event"] == "smoke_detected"


@pytest.mark.asyncio
async def test_ingest_telemetry_accepts_list_and_upserts_device():
    external_id = f"test-{uuid4()}"
    base = {
        "device": {"external_id": external_id, "type": "iot"},
        "metric_type": "temperature",
        "value": 21.5,
    }
    payload = [
        {**base, "ts": "2026-09-12T10:00:00Z"},
        {**base, "ts": "2026-09-12T10:05:00Z", "value": 22.0},
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.post("/ingest/telemetry", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ingested": 2}

    async with async_session() as session:
        result = await session.execute(select(Device).where(Device.external_id == external_id))
        devices = result.scalars().all()
        assert len(devices) == 1  # upserted, not duplicated

        result = await session.execute(
            select(TelemetryReading).where(TelemetryReading.device_id == devices[0].id)
        )
        readings = result.scalars().all()
        assert len(readings) == 2


@pytest.mark.asyncio
async def test_ingest_telemetry_persists_quality_and_provenance_fields():
    external_id = f"test-{uuid4()}"
    payload = {
        "device": {
            "external_id": external_id,
            "type": "iot",
            "location": {"building": "A", "floor": 1},
        },
        "metric_type": "co",
        "ts": "2026-09-12T10:00:00Z",
        "value": 3.2,
        "unit": "ppm",
        "quality": "valid",
        "availability": "fresh",
        "provenance": {"source_id": "sim-dataset-7", "origin": "synthetic"},
        "external_event_id": "evt-abc-123",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.post("/ingest/telemetry", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ingested": 1}

    async with async_session() as session:
        result = await session.execute(select(Device).where(Device.external_id == external_id))
        device = result.scalar_one_or_none()
        assert device is not None

        result = await session.execute(
            select(TelemetryReading).where(TelemetryReading.device_id == device.id)
        )
        reading = result.scalars().one()
        assert reading.metric_type == "co"
        assert reading.quality == "valid"
        assert reading.availability == "fresh"
        assert reading.provenance == {"source_id": "sim-dataset-7", "origin": "synthetic"}
        assert reading.external_event_id == "evt-abc-123"


@pytest.mark.asyncio
async def test_ingest_radio_transcript_without_audio():
    external_id = f"radio-ch-{uuid4()}"
    payload = {
        "device": {"external_id": external_id, "type": "radio", "name": "Channel 3"},
        "metric_type": "radio_audio",
        "ts": "2026-09-12T10:05:00Z",
        "end_ts": "2026-09-12T10:05:12Z",
        "transcript": "Command, this is Engine 12, heavy smoke on the third floor.",
        "payload": {"speaker": "unit-12", "confidence": 0.94},
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.post("/ingest/telemetry", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ingested": 1}

    async with async_session() as session:
        result = await session.execute(select(Device).where(Device.external_id == external_id))
        device = result.scalar_one_or_none()
        assert device is not None
        assert device.type == "radio"
        assert device.name == "Channel 3"

        result = await session.execute(
            select(TelemetryReading).where(TelemetryReading.device_id == device.id)
        )
        reading = result.scalars().one()
        assert reading.metric_type == "radio_audio"
        assert reading.transcript == "Command, this is Engine 12, heavy smoke on the third floor."
        assert reading.audio_url is None
        assert reading.audio_duration_ms is None
        assert reading.payload["speaker"] == "unit-12"
