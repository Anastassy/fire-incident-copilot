"""Tests for app.adapter.mapper against the vendor's own example fixtures for the
State Machine API (raw-source/fire-safety-state-api-v0.2.2/.../v0.2/examples/).

Pure mapping logic only -- no network, no live connection, no real bearer token needed.
`raw-source/` is gitignored vendor material; if it isn't present in this checkout the
fixture-based tests skip rather than fail.
"""

import json
from pathlib import Path

import pytest

from app.adapter.mapper import (
    apply_snapshot,
    map_event_to_telemetry_in,
)
from app.schemas.telemetry import TelemetryIn

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = (
    REPO_ROOT
    / "raw-source"
    / "fire-safety-state-api-v0.2.2"
    / "fire-safety-state-api-v0.2.2"
    / "v0.2"
    / "examples"
)

pytestmark = pytest.mark.skipif(
    not EXAMPLES_DIR.is_dir(),
    reason="vendor fixtures not present in this checkout (raw-source/ is gitignored)",
)


def _load(name: str):
    return json.loads((EXAMPLES_DIR / name).read_text())


def _events_by_kind_and_metric(events, kind, metric=None):
    for event in events:
        if event["kind"] != kind:
            continue
        if metric is not None and event["data"].get("kind") != metric:
            continue
        yield event


def test_measurement_observation_maps_to_valid_telemetry_in():
    events = _load("events.json")
    device_meta: dict = {}
    event = next(_events_by_kind_and_metric(events, "observation.created", "measurement"))

    mapped = map_event_to_telemetry_in(event, device_meta)

    assert mapped is not None
    telemetry = TelemetryIn(**mapped)  # raises on validation error
    assert telemetry.metric_type == "temperature"
    assert telemetry.value == 42.2
    assert telemetry.unit == "degC"
    assert telemetry.quality == "valid"
    assert telemetry.device.external_id == "sm-TMP-SRV"
    assert telemetry.device.type == "iot"
    assert telemetry.external_event_id == "ev-temp-1"


def test_smoke_measurement_maps_metric_type_and_fire_panel_device_type():
    events = _load("events.json")
    device_meta: dict = {}
    obscuration_event = next(
        e
        for e in _events_by_kind_and_metric(events, "observation.created", "measurement")
        if e["data"]["data"]["metric"] == "obscuration"
    )

    mapped = map_event_to_telemetry_in(obscuration_event, device_meta)

    assert mapped is not None
    telemetry = TelemetryIn(**mapped)
    assert telemetry.metric_type == "obscuration"
    assert telemetry.device.type == "fire_panel"
    assert telemetry.value == pytest.approx(11.017)


def test_camera_observation_maps_to_video_event():
    events = _load("events.json")
    device_meta: dict = {}
    event = next(_events_by_kind_and_metric(events, "observation.created", "camera"))

    mapped = map_event_to_telemetry_in(event, device_meta)

    assert mapped is not None
    telemetry = TelemetryIn(**mapped)
    assert telemetry.metric_type == "video_event"
    assert telemetry.device.type == "cctv"
    assert telemetry.device.external_id == "sm-CAM-SRV"
    assert telemetry.payload["media_id"] == "media-camera-001"


def test_access_observation_maps_to_access_metric():
    events = _load("events.json")
    device_meta: dict = {}
    event = next(_events_by_kind_and_metric(events, "observation.created", "access"))

    mapped = map_event_to_telemetry_in(event, device_meta)

    assert mapped is not None
    telemetry = TelemetryIn(**mapped)
    assert telemetry.metric_type == "access"
    assert telemetry.payload["action"] == "access_granted"
    assert telemetry.payload["direction"] == "enter"


def test_connectivity_observation_maps_to_disconnected_system_reading():
    events = _load("events.json")
    device_meta: dict = {}
    # SMK-SRV first appears as a device.updated (smoke_sensor) before it goes offline;
    # feed that through so connectivity mapping can resolve its device type.
    for event in events:
        if event["kind"] == "device.updated" and event["data"]["device_id"] == "SMK-SRV":
            map_event_to_telemetry_in(event, device_meta)
            break

    connectivity_event = next(
        e
        for e in _events_by_kind_and_metric(events, "observation.created", "connectivity")
    )
    mapped = map_event_to_telemetry_in(connectivity_event, device_meta)

    assert mapped is not None
    telemetry = TelemetryIn(**mapped)
    assert telemetry.metric_type == "system"
    assert telemetry.availability == "disconnected"
    assert telemetry.value == 0.0
    assert telemetry.device.type == "fire_panel"  # learned from the earlier device.updated
    assert telemetry.payload["reason"] == "synthetic_power_loss"


def test_device_updated_is_not_forwarded_but_updates_cache():
    events = _load("events.json")
    device_meta: dict = {}
    event = next(e for e in events if e["kind"] == "device.updated")

    mapped = map_event_to_telemetry_in(event, device_meta)

    assert mapped is None
    assert event["data"]["device_id"] in device_meta


def test_session_level_events_are_skipped():
    events = _load("events.json")
    device_meta: dict = {}
    for kind in ("run.updated", "room.updated", "occupancy.updated", "system.updated"):
        event = next(e for e in events if e["kind"] == kind)
        assert map_event_to_telemetry_in(event, device_meta) is None


def test_radio_transcript_observation_maps_transcript_and_duration():
    observation = _load("observation.radio-transcript.json")
    device_meta: dict = {}
    event = {"kind": "observation.created", "data": observation}

    mapped = map_event_to_telemetry_in(event, device_meta)

    assert mapped is not None
    telemetry = TelemetryIn(**mapped)
    assert telemetry.metric_type == "radio_audio"
    assert telemetry.transcript == "Test radio message."
    assert telemetry.audio_url is None
    assert telemetry.audio_duration_ms == 1300  # 1800 - 500
    assert telemetry.device.type == "radio"
    assert telemetry.device.external_id == "sm-RADIO-A"
    assert telemetry.external_event_id == "ev-radio-text-1"


def test_radio_audio_raw_chunk_is_skipped():
    events = _load("events.json")
    device_meta: dict = {}
    event = next(_events_by_kind_and_metric(events, "observation.created", "radio_audio"))

    assert map_event_to_telemetry_in(event, device_meta) is None


def test_apply_snapshot_seeds_device_meta_cache():
    snapshot = _load("snapshot.initial.json")
    device_meta: dict = {}

    apply_snapshot(device_meta, snapshot)

    assert "RADIO-A" in device_meta
    assert device_meta["RADIO-A"]["kind"] == "radio_channel"
