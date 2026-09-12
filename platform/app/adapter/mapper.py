"""Pure mapping logic: State Machine SSE ``Event``/``Observation`` JSON -> our own
``TelemetryIn``-shaped dict, ready to ``POST`` to ``/ingest/telemetry``.

No network, no I/O — this module only transforms dicts, so it's exercised directly by
``tests/test_adapter_mapper.py`` against the vendor's example fixtures.

Source contract: ``raw-source/fire-safety-state-api-v0.2.2/.../v0.2/README.md`` sections
5-8 and 11, ``PALISADES.md``, and ``openapi.json`` (schemas ``Observation*``, ``DeviceState``).

## Design notes / deliberate scope decisions

- We namespace every device from this source with the ``sm-`` prefix on ``external_id``
  (e.g. State Machine's ``RADIO-A`` becomes our ``sm-RADIO-A``), so it can never collide
  with a device created by curl-simulated or MCP-originated telemetry.
- ``device.updated`` events are **not** forwarded as telemetry readings. They are a
  derived "replace latest state" summary of readings we already ingested from the
  ``observation.created`` event that produced them; posting them again would create a
  duplicate `TelemetryReading` row for the same value. Instead we consume them (and the
  initial snapshot's device list) only to build a small local cache of each device's
  State-Machine `kind`/`name`/`room_id`/`building_id`, used to produce a better-informed
  `DeviceIn` envelope for the readings we DO forward.
- `radio_audio` observations (raw audio chunk metadata: channel/media_id/chunk timing,
  no transcript) are skipped. Per this pass's agreed scope we don't fetch/host the
  underlying audio, so there is nothing in that observation we can turn into a meaningful
  `TelemetryReading` beyond what `radio_transcript` already carries once the phrase is
  transcribed. `radio.channel.updated`, `run.updated`, `room.updated`, `camera.updated`,
  `access.updated`, `occupancy.updated`, `system.updated` and `stream.reset` are likewise
  session/summary-level state, not new raw observations, and are skipped here (the bridge
  handles `run.updated`/`stream.reset` separately for connection lifecycle).
- `ts` is taken from `Observation.received_at` (a real UTC RFC 3339 timestamp already on
  every observation) rather than converted from `observed_sim_time_ms`, which would
  require knowing the run's wall-clock anchor and speed history (including pauses) to
  convert correctly. `end_ts` is left null for observations mapped here: the *duration*
  of an interval (e.g. a radio phrase's `audio_end_sim_time_ms - audio_start_sim_time_ms`)
  is safe to compute directly since it's intrinsic to the recording, but converting the
  interval's start/end into two separate real-world instants is not, so we don't guess.
  The raw sim-time interval is preserved in `payload` instead so no information is lost.
- `Observation.evidence_id` (their immutable, opaque per-observation id) maps to our
  `external_event_id` — it is exactly the "opaque id for idempotency/reconciliation with
  the source system" field our own ingestion contract already defines that column for.
"""

from __future__ import annotations

from typing import Any, Optional

EXTERNAL_ID_PREFIX = "sm-"

# State Machine DeviceState.kind -> our DeviceType. Used to enrich the DeviceIn we send
# (better `type`/`name`), and as the sole source of device type for `connectivity`
# observations (which, unlike other observation kinds, don't imply a device type on
# their own -- a connectivity event can affect any already-known device).
DEVICE_KIND_TO_TYPE: dict[str, str] = {
    "temperature_sensor": "iot",
    "smoke_sensor": "fire_panel",
    "multisensor": "iot",
    "camera": "cctv",
    "access_reader": "other",
    "people_counter": "other",
    "radio_channel": "radio",
}

# ObservationMeasurement.data.metric -> our MetricType / DeviceType. Metrics not listed
# here (the vendor's README notes the metric vocabulary is open-ended) fall back to
# metric_type="other" (with the original metric name preserved in payload) and
# device type "iot".
MEASUREMENT_METRIC_TO_METRIC_TYPE: dict[str, str] = {
    "temperature": "temperature",
    "obscuration": "obscuration",
    "smoke_detected": "smoke",
    "co": "co",
    "eco2": "eco2",
}
MEASUREMENT_METRIC_TO_DEVICE_TYPE: dict[str, str] = {
    "temperature": "iot",
    "obscuration": "fire_panel",
    "smoke_detected": "fire_panel",
    "co": "fire_panel",
    "eco2": "fire_panel",
}

DeviceMeta = dict[str, dict[str, Any]]


def apply_device_state(device_meta: DeviceMeta, device_state: dict[str, Any]) -> None:
    """Record kind/name/room/building for a device from a `DeviceState` object -- either
    a `device.updated` event's `data`, or one entry of `Snapshot.devices`."""
    device_id = device_state.get("device_id")
    if not device_id:
        return
    device_meta[device_id] = {
        "kind": device_state.get("kind"),
        "name": device_state.get("name"),
        "room_id": device_state.get("room_id"),
        "building_id": device_state.get("building_id"),
    }


def apply_snapshot(device_meta: DeviceMeta, snapshot: dict[str, Any]) -> None:
    """Seed the device metadata cache from the initial SSE `snapshot` frame."""
    for device_state in snapshot.get("devices") or []:
        apply_device_state(device_meta, device_state)


def _device_envelope(
    device_id: str, device_type: str, room_id: Optional[str], device_meta: DeviceMeta
) -> dict[str, Any]:
    meta = device_meta.get(device_id, {})
    name = meta.get("name") or device_id
    location: dict[str, Any] = {}
    zone = room_id if room_id is not None else meta.get("room_id")
    if zone:
        location["zone"] = zone
    building = meta.get("building_id")
    if building:
        location["building"] = building
    return {
        "external_id": f"{EXTERNAL_ID_PREFIX}{device_id}",
        "type": device_type,
        "name": name,
        "location": location,
    }


def _provenance(observation: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(observation.get("provenance") or {})
    provenance["state_machine"] = {
        "run_id": observation.get("run_id"),
        "generation": observation.get("generation"),
        "evidence_id": observation.get("evidence_id"),
        "observed_sim_time_ms": observation.get("observed_sim_time_ms"),
        "received_sim_time_ms": observation.get("received_sim_time_ms"),
    }
    return provenance


def _base_fields(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": observation["received_at"],
        "provenance": _provenance(observation),
        "external_event_id": observation.get("evidence_id"),
    }


def _map_measurement(observation: dict[str, Any], device_meta: DeviceMeta) -> dict[str, Any]:
    data = observation["data"]
    metric = data.get("metric")
    metric_type = MEASUREMENT_METRIC_TO_METRIC_TYPE.get(metric, "other")
    device_type = MEASUREMENT_METRIC_TO_DEVICE_TYPE.get(metric, "iot")

    value = data.get("value")
    if isinstance(value, bool):
        value = 1.0 if value else 0.0
    elif value is not None and not isinstance(value, (int, float)):
        value = None

    payload: dict[str, Any] = {} if metric_type != "other" else {"metric": metric}

    return {
        "device": _device_envelope(
            observation["device_id"], device_type, observation.get("room_id"), device_meta
        ),
        "metric_type": metric_type,
        "value": value,
        "unit": data.get("unit"),
        "payload": payload,
        "quality": data.get("quality"),
        **_base_fields(observation),
    }


def _map_camera(observation: dict[str, Any], device_meta: DeviceMeta) -> dict[str, Any]:
    data = observation["data"]
    return {
        "device": _device_envelope(
            observation["device_id"], "cctv", observation.get("room_id"), device_meta
        ),
        "metric_type": "video_event",
        "payload": {
            "camera_id": data.get("camera_id"),
            "media_id": data.get("media_id"),
            "media_kind": data.get("media_kind"),
            "capture_start_sim_time_ms": data.get("capture_start_sim_time_ms"),
            "capture_end_sim_time_ms": data.get("capture_end_sim_time_ms"),
            "note": "media not fetched by this adapter version (audio/video streaming deferred)",
        },
        **_base_fields(observation),
    }


def _map_access(observation: dict[str, Any], device_meta: DeviceMeta) -> dict[str, Any]:
    data = observation["data"]
    return {
        "device": _device_envelope(
            observation["device_id"], "other", observation.get("room_id"), device_meta
        ),
        "metric_type": "access",
        "payload": {
            "reader_id": data.get("reader_id"),
            "door_id": data.get("door_id"),
            "action": data.get("action"),
            "direction": data.get("direction"),
            "subject_ref": data.get("subject_ref"),
            "passage_count": data.get("passage_count"),
            "from_room_id": data.get("from_room_id"),
            "to_room_id": data.get("to_room_id"),
        },
        **_base_fields(observation),
    }


def _map_radio_transcript(observation: dict[str, Any], device_meta: DeviceMeta) -> dict[str, Any]:
    data = observation["data"]
    start_ms = data.get("audio_start_sim_time_ms")
    end_ms = data.get("audio_end_sim_time_ms")
    duration_ms = end_ms - start_ms if start_ms is not None and end_ms is not None else None

    return {
        "device": _device_envelope(
            observation["device_id"], "radio", observation.get("room_id"), device_meta
        ),
        "metric_type": "radio_audio",
        "transcript": data.get("text"),
        "audio_url": None,  # audio hosting explicitly out of scope for this adapter version
        "audio_duration_ms": duration_ms,
        "payload": {
            "channel_id": data.get("channel_id"),
            "stream_id": data.get("stream_id"),
            "segment_id": data.get("segment_id"),
            "source_segment_id": data.get("source_segment_id"),
            "language": data.get("language"),
            "audio_start_sim_time_ms": start_ms,
            "audio_end_sim_time_ms": end_ms,
            "delivery": data.get("delivery"),
            "machine_generated": data.get("machine_generated"),
            "human_verified": data.get("human_verified"),
            "model": data.get("model"),
            "words": data.get("words", []),
            "timing_notes": data.get("timing_notes", []),
        },
        **_base_fields(observation),
    }


def _map_people_count(observation: dict[str, Any], device_meta: DeviceMeta) -> dict[str, Any]:
    data = observation["data"]
    count = data.get("count")
    return {
        "device": _device_envelope(
            observation["device_id"], "other", observation.get("room_id"), device_meta
        ),
        "metric_type": "occupancy",
        "value": float(count) if count is not None else None,
        "unit": data.get("unit"),
        "payload": {"scope_id": data.get("scope_id"), "scope_type": data.get("scope_type")},
        "quality": data.get("quality"),
        **_base_fields(observation),
    }


def _map_connectivity(observation: dict[str, Any], device_meta: DeviceMeta) -> dict[str, Any]:
    data = observation["data"]
    device_id = observation["device_id"]
    sm_kind = (device_meta.get(device_id) or {}).get("kind")
    device_type = DEVICE_KIND_TO_TYPE.get(sm_kind, "other")
    connected = data.get("connected")

    return {
        "device": _device_envelope(device_id, device_type, observation.get("room_id"), device_meta),
        "metric_type": "system",
        "value": (1.0 if connected else 0.0) if connected is not None else None,
        "availability": "fresh" if connected else "disconnected",
        "payload": {"connected": connected, "reason": data.get("reason")},
        **_base_fields(observation),
    }


# Observation.kind -> mapper. `radio_audio` is intentionally absent (see module docstring).
_OBSERVATION_MAPPERS = {
    "measurement": _map_measurement,
    "camera": _map_camera,
    "access": _map_access,
    "radio_transcript": _map_radio_transcript,
    "people_count": _map_people_count,
    "connectivity": _map_connectivity,
}


def map_observation_to_telemetry_in(
    observation: dict[str, Any], device_meta: DeviceMeta
) -> Optional[dict[str, Any]]:
    """Map one `Observation` (the `data` of an `observation.created` Event) to a
    `TelemetryIn`-shaped dict, or return None if this observation kind isn't mapped."""
    mapper = _OBSERVATION_MAPPERS.get(observation.get("kind", ""))
    if mapper is None:
        return None
    return mapper(observation, device_meta)


def map_event_to_telemetry_in(
    event: dict[str, Any], device_meta: DeviceMeta
) -> Optional[dict[str, Any]]:
    """Map one SSE `Event` (the JSON carried in an `event: event` SSE frame's `data`) to
    a `TelemetryIn`-shaped dict, or None if this event kind produces nothing to forward.

    `device.updated` updates `device_meta` as a side effect (see module docstring) and
    always returns None. Unmapped kinds (run.updated, room.updated, camera.updated,
    access.updated, occupancy.updated, radio.channel.updated, system.updated,
    stream.reset) also return None -- the bridge handles run.updated/stream.reset
    separately for connection lifecycle, not as telemetry.
    """
    kind = event.get("kind")
    data = event.get("data") or {}

    if kind == "observation.created":
        return map_observation_to_telemetry_in(data, device_meta)

    if kind == "device.updated":
        apply_device_state(device_meta, data)
        return None

    return None
