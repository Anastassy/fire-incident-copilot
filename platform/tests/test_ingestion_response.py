"""No database or Redis needed: run with pytest --noconftest for isolated checks."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telemetry import _to_out
from app.core.db import get_session
from app.ingestion import http
from app.models.device import Device
from app.models.telemetry import TelemetryReading


@pytest.fixture
def ingestion_client(monkeypatch):
    app = FastAPI()
    app.include_router(http.router)
    session = AsyncMock(spec=AsyncSession)

    async def isolated_session():
        yield session

    app.dependency_overrides[get_session] = isolated_session
    devices = []
    readings = []

    async def upsert(_session, device):
        result = Device(id=UUID(int=len(devices) + 1), external_id=device.external_id)
        devices.append(result)
        return result

    async def write(_session, device_id, item):
        values = item.model_dump(exclude={'device'})
        result = TelemetryReading(
            id=90210 + len(readings),
            device_id=device_id,
            ingested_at=datetime(2026, 9, 12, 10, 0, 1, tzinfo=timezone.utc),
            **values,
        )
        readings.append(result)
        return result

    upsert_mock = AsyncMock(side_effect=upsert)
    write_mock = AsyncMock(side_effect=write)
    monkeypatch.setattr(http, 'upsert_device_from_telemetry', upsert_mock)
    monkeypatch.setattr(http, 'write_telemetry_reading', write_mock)
    with TestClient(app) as client:
        yield client, session, readings, upsert_mock, write_mock


def telemetry(value, index=0):
    return {
        'device': {'external_id': f'state-run-g4:TMP-{index}', 'type': 'iot'},
        'metric_type': 'temperature',
        'ts': '2026-09-12T10:00:00Z',
        'value': value,
        'unit': 'degC',
        'quality': 'missing' if value is None else 'valid',
        'availability': 'missing' if value is None else 'fresh',
        'payload': {'raw_value': value},
        'external_event_id': f'state-run:g4:evidence-{index}',
        'provenance': {'state_machine': {
            'run_id': 'state-run',
            'generation': 4,
            'device_id': f'TMP-{index}',
            'evidence_id': f'evidence-{index}',
            'observed_sim_time_ms': 1234,
            'received_sim_time_ms': 1300,
        }},
    }


def test_single_ingestion_returns_persisted_identity_and_original_provenance(ingestion_client):
    client, session, persisted, upsert, write = ingestion_client
    body = telemetry(23.5)
    response = client.post('/ingest/telemetry', json=body)
    assert response.status_code == 200
    result = response.json()
    assert result['ingested'] == 1
    assert len(result['readings']) == 1
    row = result['readings'][0]
    assert row['id'] == persisted[0].id == 90210
    assert isinstance(row['id'], int)
    assert row['device_id'] == str(persisted[0].device_id)
    assert row['external_event_id'] == body['external_event_id']
    assert row['provenance'] == body['provenance']
    assert row == jsonable_encoder(_to_out(persisted[0]))
    upsert.assert_awaited_once()
    write.assert_awaited_once()
    assert write.await_args.args[0] is session
    session.execute.assert_not_awaited()


def test_batch_preserves_none_zero_and_order_without_followup_queries(ingestion_client):
    client, session, persisted, upsert, write = ingestion_client
    payload = [telemetry(None), telemetry(0, 1)]
    response = client.post('/ingest/telemetry', json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['ingested'] == 2
    rows = result['readings']
    assert [row['id'] for row in rows] == [90210, 90211]
    assert [row['device_id'] for row in rows] == [str(row.device_id) for row in persisted]
    assert rows[0]['value'] is None
    assert rows[0]['availability'] == 'missing'
    assert rows[1]['value'] == 0
    assert rows[1]['availability'] == 'fresh'
    for row, original in zip(rows, payload):
        assert row['provenance'] == original['provenance']
        assert row['external_event_id'] == original['external_event_id']
        assert row['payload'] == original['payload']
    assert upsert.await_count == write.await_count == 2
    session.execute.assert_not_awaited()


def test_radio_response_keeps_transcript_timing_and_audio_availability(ingestion_client):
    client, _, persisted, _, _ = ingestion_client
    body = {
        **telemetry(None),
        'device': {'external_id': 'state-run-g4:RADIO-1', 'type': 'radio'},
        'metric_type': 'radio_audio',
        'end_ts': '2026-09-12T10:00:02Z',
        'transcript': 'Copy V-Fire 25, thank you.',
        'audio_url': None,
        'audio_duration_ms': 2000,
    }
    response = client.post('/ingest/telemetry', json=body)
    assert response.status_code == 200
    row = response.json()['readings'][0]
    assert row['id'] == persisted[0].id
    assert row['transcript'] == body['transcript']
    assert row['ts'] == body['ts']
    assert row['end_ts'] == body['end_ts']
    assert row['audio_url'] is None
    assert row['audio_duration_ms'] == 2000
    assert row['provenance'] == body['provenance']


def test_empty_batch_returns_no_persisted_readings(ingestion_client):
    client, session, persisted, upsert, write = ingestion_client
    response = client.post('/ingest/telemetry', json=[])
    assert response.status_code == 200
    assert response.json() == {'ingested': 0, 'readings': []}
    assert persisted == []
    upsert.assert_not_awaited()
    write.assert_not_awaited()
    session.execute.assert_not_awaited()
