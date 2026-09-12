# Changelog

## 1.0.4 · 2026-09-12 · Fixed openapi.json version sync

**Fix**: OpenAPI schema version (`openapi.json` info.version) now matches the contract package
version (was stuck at FastAPI's default 0.1.0). Both are now synchronized at 1.0.4 via
`app/main.py`'s FastAPI constructor `version=` parameter.

**Maintenance note**: Going forward, keep this in sync manually — each time the contract version
bumps, also update the `version=` string in `app/main.py`'s FastAPI constructor and re-export
openapi.json by running:
```bash
.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" \
  > contracts/safety-telemetry-platform-v1/openapi.json
```

## 1.0.3 · 2026-09-12 · Documented rich radio_transcript payload convention

**Documentation**: Added convention for populating `provenance` and `payload` fields on rich
radio transcript events. No schema change — `payload` and `provenance` were already generic dicts;
this formalizes the convention for what should go inside them when sending machine-transcribed
radio traffic with word-level timing, confidence scores, and origin/trust metadata.

See [examples/radio-transcript-rich-response.json](examples/radio-transcript-rich-response.json)
and root `README.md` "Для команды симулятора" section for the complete mapping and examples.
Updated [CLIENT_FLOW.md](CLIENT_FLOW.md) to reference the convention.

## 1.0.2 · 2026-09-12 · Radio/comms transcription support

**Feature**: Added radio/comms transcription support. `DeviceType` now includes `"radio"`; simulators
can send transcribed radio traffic via `metric_type="radio_audio"` with the new optional fields:
- `transcript` — speech-to-text of one message/utterance
- `audio_url` — reference to original audio clip (reserved for future use, currently null)
- `audio_duration_ms` — duration in milliseconds (reserved for future use)

One `TelemetryReading` per utterance; use `ts`/`end_ts` for the message's time span. See
[CLIENT_FLOW.md](CLIENT_FLOW.md) "Notes" section for details, and
[examples/radio-telemetry-response.json](examples/radio-telemetry-response.json) for a sample
response shape.

## 1.0.1 · 2026-09-12 · SSE events now carry full object shape

**Fix**: Incident and dashboard SSE events (`/stream/incidents` and `/stream/dashboards/{id}`)
now publish the complete `IncidentOut` and `DashboardOut` object shapes (including `evidence`
for incidents) instead of narrow event subsets. This means clients can apply SSE events
directly as state updates (upsert by `id`) rather than treating them as "refetch via REST"
signals. See [CLIENT_FLOW.md](CLIENT_FLOW.md) "Wire format detail worth knowing" section
for details.

## 1.0.0 · 2026-09-12 · initial release

First published contract for the Safety Telemetry Platform, describing the implemented
and running service (not a draft):

- **Ingestion**: `POST /ingest/telemetry` and `WS /ingest/stream`, both accepting
  `TelemetryIn` (device envelope upserted by `external_id` + one reading). Includes the
  full current field set: `quality` (`valid`/`missing`/`invalid`), `availability`
  (`fresh`/`stale`/`missing`/`invalid`/`disconnected`), free-form `provenance`, and
  `external_event_id` for source-side idempotency/reconciliation — all optional, all
  already present in `app/models/telemetry.py` / `app/schemas/telemetry.py` at time of
  writing.
- **`metric_type` vocabulary**: `temperature`, `smoke`, `water_level`, `motion`,
  `video_event`, `heartbeat`, `other`, plus the expanded set `access`, `occupancy`,
  `radio_audio`, `system`, `obscuration`, `co`, `eco2`.
- **Dashboard-facing REST**: `GET /devices(/{id})`, `GET /telemetry`, `GET /telemetry/latest`,
  `GET /incidents(/{id})`, `GET /dashboards(/{id})`.
- **Dashboard-facing SSE**: `GET /stream/telemetry`, `GET /stream/incidents`,
  `GET /stream/dashboards/{id}` — fire-and-forget live events, no replay/cursor.
- **Agent-facing MCP** (`/mcp-server`, streamable-http): 13 tools covering devices,
  telemetry, incidents (including writes: `create_incident`, `update_incident`,
  `link_evidence`), and dashboards (including writes: `create_dashboard`,
  `update_dashboard`).
- **Auth**: single shared `X-API-Key` header for every interface (REST, WS, SSE, MCP) —
  one static key for the whole hackathon, not per-team keys.

No breaking changes anticipated before the hackathon deadline; this package will be
updated in place if the schema changes.
