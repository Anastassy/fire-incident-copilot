# Safety Telemetry Platform

Hackathon backend platform: ingestion of telemetry from sensors (CCTV/IoT/fire panels/alarm systems),
storage, and two independent data access interfaces:

- **REST + SSE** (`/devices`, `/telemetry`, `/incidents`, `/dashboards`, `/stream/*`) — for the
  autonomous dashboard application.
- **MCP** (`/mcp-server`, streamable-http transport) — for the agent system: read telemetry/incidents, write
  incident hypotheses and custom dashboard-specs on operator request.

### What was built during the hackathon, what was inherited

**Fully implemented during the hackathon:**
- FastAPI backend with asynchronous architecture (SQLAlchemy, Alembic migrations, Pydantic validation)
- Ingestion API (`POST /ingest/telemetry`, `WS /ingest/stream`) with device upsert by `external_id`
- REST API for reading devices, telemetry, incidents, dashboards
- SSE streams for live updates (Redis pub/sub)
- MCP server (13 tools) for the agent system
- Bridge adapter (`app/adapter/bridge.py`) to the simulator's State Machine API (relays real events to ingestion)

**External dependencies (not our code):**
- State Machine API (contract in `raw-source/fire-safety-state-api-v0.2.2/`) — created by another team, deployed at `https://api.aitinkerers.space`
- Simulator (team "Simulation") — provides scenarios and events via State Machine API

Full architecture and responsibility breakdown — see plan in `/Users/vitalynec/.claude/plans/swirling-meandering-aho.md`.

### Deployment addresses

- **Production** (planned): `https://platform.aitinkerers.space` — target address after Hetzner deployment and DNS/Caddy configuration (current status: infrastructure being prepared)
- **Local development**: `http://localhost:8000` — for local development and testing

All examples in this document use `http://localhost:8000`; in production simply replace with `https://platform.aitinkerers.space`.

---

## For the simulator team (ingestion)

### Note: synthetic vs. real data

All examples below and in files `contracts/safety-telemetry-platform-v1/examples/` are **synthetic/illustrative**
(for testing and development): they are generated manually via curl, contain fixed timestamps,
and `"origin": "synthetic"` in the provenance.

**Real data** appears only when the `bridge` service runs with a valid `STATE_MACHINE_BEARER_TOKEN` —
then events come from the simulator with `"origin": "recorded"` (provenance contains real source_id,
acquisition_id, audio_source_file, and SHA256). The rest of the platform does not change and does not know the difference —
all three interfaces (REST, SSE, MCP) work identically with synthetic and real data.

### Data ingestion contract

Two ways to send telemetry:

#### 1. HTTP (POST `/ingest/telemetry`)

Single object or list of objects:

```bash
curl -X POST http://localhost:8000/ingest/telemetry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-change-me" \
  -d '{
    "device": {
      "external_id": "cam-12",
      "type": "cctv",
      "name": "Camera warehouse A-2",
      "location": {"building": "A", "floor": 2, "zone": "warehouse"}
    },
    "metric_type": "video_event",
    "ts": "2026-09-12T10:00:00Z",
    "end_ts": null,
    "value": null,
    "unit": null,
    "payload": {"event": "smoke_detected", "confidence": 0.87},
    "quality": "valid",
    "availability": "fresh",
    "provenance": {"source_id": "sim-dataset-7", "origin": "synthetic"},
    "external_event_id": "evt-abc-123"
  }'
```

**Response:**
```json
{"ingested": 1}
```

Example for a radio channel (`type: "radio"`) — transcribed radio message. One
`TelemetryReading` record per transcribed message/utterance (not a continuous stream);
`ts`/`end_ts` — start/end of the utterance. Audio attachment (`audio_url`, `audio_duration_ms`) is not
yet sent by the simulator and is expected in the future.

Minimal example:

```bash
curl -X POST http://localhost:8000/ingest/telemetry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-change-me" \
  -d '{
    "device": {
      "external_id": "radio-ch-3",
      "type": "radio",
      "name": "Channel 3"
    },
    "metric_type": "radio_audio",
    "ts": "2026-09-12T10:05:00Z",
    "end_ts": "2026-09-12T10:05:12Z",
    "transcript": "Command, this is Engine 12, heavy smoke on the third floor.",
    "payload": {"speaker": "unit-12", "confidence": 0.94}
  }'
```

Extended example with full provenance (origin/trust data):

```bash
curl -X POST http://localhost:8000/ingest/telemetry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-change-me" \
  -d '{
    "device": {
      "external_id": "RADIO-A",
      "type": "radio",
      "name": "Radio Channel A (Main)"
    },
    "metric_type": "radio_audio",
    "ts": "2026-09-12T10:05:30Z",
    "end_ts": "2026-09-12T10:05:42Z",
    "transcript": "Engine 12 to command, we have heavy smoke on the third floor, east wing. Visibility is very low.",
    "external_event_id": "ev-radio-text-001",
    "quality": "valid",
    "availability": "fresh",
    "provenance": {
      "origin": "recorded",
      "model": "mlx-community/whisper-large-v3-turbo-q4",
      "delivery": "prerecorded",
      "machine_generated": true,
      "human_verified": false,
      "audio_source_file": "archive/2026-09-12-radio-a.wav",
      "audio_source_sha256": "a1b2c3d4e5f6...",
      "source_id": "broadcastify-archive-import",
      "acquisition_id": "session-2026-09-12-001"
    },
    "payload": {
      "language": "en",
      "channel_id": "RADIO-A",
      "stream_id": "RADIO-A-primary",
      "speaker": "engine-12",
      "confidence": 0.94,
      "words": [
        {"word": "Engine", "start_ms": 0, "end_ms": 250, "confidence": 0.99},
        {"word": "12", "start_ms": 280, "end_ms": 450, "confidence": 0.98},
        {"word": "command", "start_ms": 500, "end_ms": 750, "confidence": 0.97}
      ],
      "timing_notes": ["Early word detected 340ms before segment boundary"]
    }
  }'
```

#### 2. WebSocket (WS `/ingest/stream`)

Persistent connection, one JSON object per line:

```javascript
const ws = new WebSocket('ws://localhost:8000/ingest/stream', [], {
  headers: {'X-API-Key': 'dev-secret-change-me'}
});

ws.on('message', (msg) => {
  console.log(JSON.parse(msg));  // {"status": "ok"} or {"status": "error", "detail": "..."}
});

ws.send(JSON.stringify({
  device: {
    external_id: "iot-temp-01",
    type: "iot",
    name: "Temperature sensor zone B",
    location: {building: "B", floor: 1}
  },
  metric_type: "temperature",
  ts: "2026-09-12T10:05:30Z",
  end_ts: null,
  value: 23.5,
  unit: "°C",
  payload: {}
}));
```

### TelemetryIn Schema

| Field | Type | Optional | Description |
|-------|------|----------|-------------|
| `device` | DeviceIn | no | Device envelope |
| `device.external_id` | string | no | Unique ID in the source system |
| `device.type` | enum | no | `cctv`, `iot`, `fire_panel`, `alarm`, `water_sensor`, `radio`, `other` |
| `device.name` | string | yes | Human-readable name |
| `device.location` | DeviceLocation | yes | Building, floor, zone, coordinates |
| `metric_type` | enum | no | `temperature`, `smoke`, `water_level`, `motion`, `video_event`, `heartbeat`, `other`, `access`, `occupancy`, `radio_audio`, `system`, `obscuration`, `co`, `eco2` |
| `ts` | ISO 8601 datetime | no | Event start (or the only instant for point events) |
| `end_ts` | ISO 8601 datetime | yes | **Only for events with duration** (e.g., motion from ts to end_ts). For point events do not send or send `null`. |
| `value` | float | yes | For scalar metrics (temperature, water level) |
| `unit` | string | yes | Unit of measurement (°C, m, %, etc.) |
| `payload` | dict | yes | Arbitrary structured data (detections, statuses) |
| `quality` | enum | yes | Source value quality: `valid`, `missing`, `invalid` |
| `availability` | enum | yes | Device freshness/connectivity at observation time: `fresh`, `stale`, `missing`, `invalid`, `disconnected` |
| `provenance` | dict | yes | Arbitrary metadata about data origin (e.g., `source_id` of the source dataset, original recorded time, origin type — `recorded`/`synthetic`/`derived`/`human_report`) |
| `external_event_id` | string | yes | Opaque event/observation ID from the source system — for idempotency and reconciliation with source records |
| `transcript` | string | yes | Radio traffic transcription (speech-to-text) for a single message/utterance. Relevant for `metric_type: "radio_audio"` and `device.type: "radio"` |
| `audio_url` | string | yes | Reference to the original audio clip. Not yet filled by the simulator (transcript comes without audio); reserved for the future |
| `audio_duration_ms` | int | yes | Audio clip duration in milliseconds, if known |

### Authorization

**All requests require the header:**
```
X-API-Key: <value from .env API_KEY>
```

Default: `dev-secret-change-me` (see `app/core/config.py`).

---

## For the dashboard team (REST + SSE)

### REST API endpoints

#### Devices

**`GET /devices`** — list of devices with filtering

Parameters:
- `type` (query, optional): filter by type (cctv, iot, fire_panel, alarm, water_sensor, other)
- `status` (query, optional): filter by status (online, offline, fault)
- `building` (query, optional): building
- `floor` (query, optional): floor
- `zone` (query, optional): zone

```bash
curl -X GET "http://localhost:8000/devices?type=cctv&building=A" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `list[DeviceOut]`
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "external_id": "cam-12",
    "type": "cctv",
    "name": "Camera warehouse A-2",
    "location": {"building": "A", "floor": 2, "zone": "warehouse"},
    "status": "online",
    "metadata": {},
    "first_seen_at": "2026-09-12T09:30:00Z",
    "last_seen_at": "2026-09-12T10:15:00Z"
  }
]
```

**`GET /devices/{device_id}`** — single device

```bash
curl -X GET "http://localhost:8000/devices/550e8400-e29b-41d4-a716-446655440000" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `DeviceOut` (see above)

---

#### Telemetry

**`GET /telemetry`** — query readings with filtering

Parameters:
- `device_id` (query, optional, UUID): device ID
- `metric_type` (query, optional): metric type
- `since` (query, optional, ISO 8601): range start
- `until` (query, optional, ISO 8601): range end
- `limit` (query, default=100): maximum number of results

```bash
curl -X GET "http://localhost:8000/telemetry?device_id=550e8400-e29b-41d4-a716-446655440000&metric_type=video_event&since=2026-09-12T09:00:00Z&limit=50" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `list[TelemetryOut]`
```json
[
  {
    "id": 42,
    "device_id": "550e8400-e29b-41d4-a716-446655440000",
    "ts": "2026-09-12T10:00:00Z",
    "end_ts": null,
    "metric_type": "video_event",
    "value": null,
    "unit": null,
    "payload": {"event": "smoke_detected", "confidence": 0.87},
    "ingested_at": "2026-09-12T10:00:05Z"
  }
]
```

**`GET /telemetry/latest`** — latest readings per device

Parameters:
- `device_id` (query, optional, list[UUID]): list of device IDs (can be repeated)
- `type` (query, optional): device type
- `building` (query, optional): building
- `floor` (query, optional): floor
- `zone` (query, optional): zone

```bash
curl -X GET "http://localhost:8000/telemetry/latest?device_id=550e8400-e29b-41d4-a716-446655440000&device_id=660e8400-e29b-41d4-a716-446655440001&type=cctv" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `list[TelemetryOut]` (one per device, most recent)

---

#### Incidents

**`GET /incidents`** — list of incidents with filtering

Parameters:
- `status` (query, optional): filter by status (open, acknowledged, resolved, escalated)
- `type` (query, optional): incident type (fire, flood, intrusion, equipment_fault, other)
- `since` (query, optional, ISO 8601): opened since this date

```bash
curl -X GET "http://localhost:8000/incidents?status=open&type=fire" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `list[IncidentOut]` (without evidence, for performance)
```json
[
  {
    "id": "11111111-2222-3333-4444-555555555555",
    "type": "fire",
    "status": "open",
    "severity": "high",
    "location": {"building": "A", "zone": "warehouse"},
    "summary": "Smoke detected in warehouse A",
    "metadata": {},
    "opened_at": "2026-09-12T10:00:00Z",
    "updated_at": "2026-09-12T10:05:00Z",
    "closed_at": null,
    "evidence": []
  }
]
```

**`GET /incidents/{incident_id}`** — single incident with evidence

```bash
curl -X GET "http://localhost:8000/incidents/11111111-2222-3333-4444-555555555555" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `IncidentOut` (with full evidence array)
```json
{
  "id": "11111111-2222-3333-4444-555555555555",
  "type": "fire",
  "status": "open",
  "severity": "high",
  "location": {"building": "A", "zone": "warehouse"},
  "summary": "Smoke detected in warehouse A",
  "metadata": {},
  "opened_at": "2026-09-12T10:00:00Z",
  "updated_at": "2026-09-12T10:05:00Z",
  "closed_at": null,
  "evidence": [
    {
      "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "device_id": "550e8400-e29b-41d4-a716-446655440000",
      "reading_id": 42,
      "note": "smoke detected by CCTV model v2",
      "created_at": "2026-09-12T10:00:00Z"
    }
  ]
}
```

---

#### Dashboards

**`GET /dashboards`** — list of dashboard specs

```bash
curl -X GET "http://localhost:8000/dashboards" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `list[DashboardOut]`
```json
[
  {
    "id": "cccccccc-dddd-eeee-ffff-000000000000",
    "title": "Warehouse A Monitoring",
    "created_by": "agent",
    "spec": {"layout": "grid", "widgets": [...]},
    "version": 2,
    "created_at": "2026-09-12T09:00:00Z",
    "updated_at": "2026-09-12T10:15:00Z"
  }
]
```

**`GET /dashboards/{dashboard_id}`** — single dashboard

```bash
curl -X GET "http://localhost:8000/dashboards/cccccccc-dddd-eeee-ffff-000000000000" \
  -H "X-API-Key: dev-secret-change-me"
```

**Response:** `DashboardOut` (see above)

---

### SSE Streams

Three streams for real-time updates (Server-Sent Events). Subscribe without parameters, filter on client.

**`GET /stream/telemetry`** — telemetry events

```bash
curl -X GET "http://localhost:8000/stream/telemetry" \
  -H "X-API-Key: dev-secret-change-me"
```

Message on the channel (raw JSON):
```json
{
  "id": 42,
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "ts": "2026-09-12T10:00:00Z",
  "end_ts": null,
  "metric_type": "video_event",
  "value": null,
  "unit": null,
  "payload": {"event": "smoke_detected"},
  "ingested_at": "2026-09-12T10:00:05Z"
}
```

**`GET /stream/incidents`** — incident events

```bash
curl -X GET "http://localhost:8000/stream/incidents" \
  -H "X-API-Key: dev-secret-change-me"
```

Message on the channel:
```json
{
  "id": "11111111-2222-3333-4444-555555555555",
  "type": "fire",
  "status": "open",
  "severity": "high",
  "location": {...},
  "summary": "...",
  "metadata": {},
  "opened_at": "...",
  "updated_at": "...",
  "closed_at": null
}
```

**`GET /stream/dashboards/{dashboard_id}`** — dashboard events

```bash
curl -X GET "http://localhost:8000/stream/dashboards/cccccccc-dddd-eeee-ffff-000000000000" \
  -H "X-API-Key: dev-secret-change-me"
```

Message on the channel: DashboardOut updates (current implementation broadcasts all events to the shared channel; client-side filtering by dashboard_id).

---

### Swagger UI (for exploration)

**`GET /docs`** — interactive Swagger UI

- **Available without authorization** — static view
- **"Try it out" requires X-API-Key** in headers (entered in the interface)
- Full list of parameters and examples

---

## For the agent system (MCP)

### Transport and mounting

- **Path:** `/mcp-server`
- **Transport:** streamable-http (Starlette SSE)
- **Authorization:** X-API-Key header (like REST API)
- **Connection:** initiated by the agent; platform listens at `/mcp-server/mcp`

```bash
# Example curl subscribe to MCP tools (SSE)
curl -X POST "http://localhost:8000/mcp-server/mcp" \
  -H "X-API-Key: dev-secret-change-me" \
  -H "Content-Type: application/json"
```

### MCP Tools

#### Devices

**`list_devices(type: str | None, status: str | None) → list[dict]`**

List devices, optionally filtered by type and/or status.

Parameters:
- `type`: filter by type (cctv, iot, fire_panel, alarm, water_sensor, other)
- `status`: filter by status (online, offline, fault)

Returns:
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "external_id": "cam-12",
    "type": "cctv",
    "name": "Camera warehouse A-2",
    "location": {"building": "A", "floor": 2, "zone": "warehouse"},
    "status": "online",
    "metadata": {},
    "first_seen_at": "2026-09-12T09:30:00Z",
    "last_seen_at": "2026-09-12T10:15:00Z"
  }
]
```

**`get_device(device_id: str) → dict | None`**

Get a single device by ID.

Parameters:
- `device_id`: device UUID

Returns: Device object or None.

---

#### Telemetry

**`query_telemetry(device_id: str | None, metric_type: str | None, since: str | None, until: str | None, limit: int = 100) → list[dict]`**

Query readings with filtering.

Parameters:
- `device_id`: device UUID (optional)
- `metric_type`: metric type (optional)
- `since`: ISO 8601 range start (optional)
- `until`: ISO 8601 range end (optional)
- `limit`: maximum results (default 100)

Returns:
```json
[
  {
    "id": 42,
    "device_id": "550e8400-e29b-41d4-a716-446655440000",
    "ts": "2026-09-12T10:00:00Z",
    "end_ts": null,
    "metric_type": "video_event",
    "value": null,
    "unit": null,
    "payload": {"event": "smoke_detected", "confidence": 0.87},
    "ingested_at": "2026-09-12T10:00:05Z"
  }
]
```

**`get_latest_readings(device_ids: list[str] | None, type: str | None) → list[dict]`**

Latest readings per device.

Parameters:
- `device_ids`: list of UUIDs (optional)
- `type`: filter by device type (optional)

Returns: one TelemetryOut per device.

---

#### Incidents

**`list_incidents(status: str | None, type: str | None, since: str | None) → list[dict]`**

List incidents with filtering.

Parameters:
- `status`: filter by status (open, acknowledged, resolved, escalated)
- `type`: filter by type (fire, flood, intrusion, equipment_fault, other)
- `since`: ISO 8601, opened since this date (optional)

Returns: list of IncidentOut (without evidence).

**`get_incident(incident_id: str) → dict | None`**

Get a single incident with full evidence.

Parameters:
- `incident_id`: incident ID (UUID)

Returns: IncidentOut with evidence array or None.

**`create_incident(type: str, severity: str, location: dict, summary: str, evidence: list[dict] | None) → dict`**

Create a new incident hypothesis.

Parameters:
- `type`: incident type (fire, flood, intrusion, equipment_fault, other)
- `severity`: severity (low, medium, high, critical)
- `location`: dict with building/floor/zone/lat/lon
- `summary`: description
- `evidence`: optional list {device_id, reading_id, note} for initial linking

Returns: created IncidentOut.

**`update_incident(incident_id: str, status: str | None, severity: str | None, note: str | None) → dict`**

Update incident status/severity or add a note.

Parameters:
- `incident_id`: incident UUID
- `status`: new status (open, acknowledged, resolved, escalated), optional
- `severity`: new severity (low, medium, high, critical), optional
- `note`: note text to add to metadata, optional

Returns: updated IncidentOut.

**`link_evidence(incident_id: str, device_id: str | None, reading_id: int | None, note: str | None) → dict`**

Link evidence (device reading and/or note) to an existing incident.

Parameters:
- `incident_id`: incident UUID
- `device_id`: device UUID (optional)
- `reading_id`: reading ID (optional)
- `note`: text note (optional)

Returns: updated IncidentOut with added evidence.

---

#### Dashboards

**`list_dashboards() → list[dict]`**

List all dashboard specs.

No parameters.

Returns:
```json
[
  {
    "id": "cccccccc-dddd-eeee-ffff-000000000000",
    "title": "Warehouse A Monitoring",
    "created_by": "agent",
    "spec": {"layout": "grid", "widgets": [...]},
    "version": 2,
    "created_at": "2026-09-12T09:00:00Z",
    "updated_at": "2026-09-12T10:15:00Z"
  }
]
```

**`get_dashboard(dashboard_id: str) → dict | None`**

Get a single dashboard by ID.

Parameters:
- `dashboard_id`: dashboard UUID

Returns: DashboardOut or None.

**`create_dashboard(title: str, spec: dict, created_by: str = "agent") → dict`**

Create a new dashboard spec.

Parameters:
- `title`: title
- `spec`: arbitrary dict with layout/widgets/etc
- `created_by`: source (agent, operator, default); default is "agent"

Returns: created DashboardOut (version = 1).

**`update_dashboard(dashboard_id: str, title: str | None, spec: dict | None) → dict`**

Update dashboard (title and/or spec), incrementing version.

Parameters:
- `dashboard_id`: dashboard UUID
- `title`: new title (optional)
- `spec`: new spec (optional)

Returns: updated DashboardOut with incremented version.

---

### Environment configuration

Variables from `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/platform
REDIS_URL=redis://localhost:6379/0
API_KEY=dev-secret-change-me  # used as X-API-Key for all requests
```

Default values see in `app/core/config.py`.

**Tests use a separate database.** `pytest` never reads or writes to the database from
`DATABASE_URL` above — `tests/conftest.py` before session start creates (if it doesn't exist)
a separate database on the same Postgres (by default `<database_name>_test`, i.e.,
`platform_test`), runs `alembic upgrade head` into it, and directs the entire
application there during tests. Override the path via `TEST_DATABASE_URL` in
`.env` (see `.env.example`) — usually not needed.

---

## Running (locally, for development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db redis
alembic upgrade head
uvicorn app.main:app --reload
```

Full stack in containers: `docker compose up --build`.

Note: Postgres host port in `docker-compose.yml` is `5433` (still `db:5432` inside the docker network),
because `5432` on the machine is already occupied by another local project. `.env` for local development is already
configured for `localhost:5433`.

---

## Bridge to live State Machine (adapter)

`app/adapter/` — separate, independent from FastAPI process: connects via SSE to
the real, already deployed "State Machine API" of the simulator team
(`https://api.aitinkerers.space/api/v1`, contract — package
`raw-source/fire-safety-state-api-v0.2.2/` in the repo root) and relays events
to OUR `POST /ingest/telemetry` — the same way curl or any other ingestion API client does.
The rest of the platform (REST/SSE, MCP, all three consuming teams) does not
change and does not know the data is now real, not curl-simulated.

The bridge supports two modes of operation (see "Configuration" below, variable
`STATE_MACHINE_RUN_ID`):

- **Local run (default, for development/integration checks).** The bridge creates
  (or reuses after restart) its own State Machine `run` and
  manages only it — including `play`.
- **Shared production run.** The bridge subscribes to one pre-agreed,
  external `run_id` — the same one subscribed to by the UI team and other consumers —
  and does NOT create a run and does NOT send it any commands (including `play`). This is a requirement
  from the simulator team's deploy instructions
  (`raw-source/state-consumer-handoff/.../START_HERE.ru.md`, section 3): "не создавай
  run для каждого ... старта worker; не включай Play при подписке".

What the bridge does:

1. Determines the run: either creates/reuses its own local `run` for the chosen
   `scenario_id` (default mode), or subscribes to `STATE_MACHINE_RUN_ID`,
   if set (production mode — without creating/managing the run) — and opens its
   SSE stream.
2. In local mode sends the `play` command (once during process lifetime).
   In shared-run mode this command is not sent at all.
3. For each relevant SSE event constructs `TelemetryIn`-compatible JSON and posts it
   to `{OUR_API_BASE_URL}/ingest/telemetry` with our same `X-API-Key`.
4. Reconnects on disconnect (`Last-Event-ID`), handles `stream.reset` (new
   generation — reconnection without cursor, fresh snapshot) and `410 CURSOR_EXPIRED`
   (also without cursor), does backoff 1/2/4/8/15 sec + jitter on other errors,
   does not retry endlessly on `401`/`403`.
5. Stores `run_id`/`generation`/`cursor` in local JSON file
   `.state_machine_bridge_state.json` (in `.gitignore`) — process restart continues
   the same run from the same position, not creating a new run every time.

### What is mapped, what is skipped

| Kind (SSE `event.kind` / `Observation.kind`) | What we do |
|---|---|
| `observation.created` → `measurement` | → `TelemetryIn` (metric_type by table: temperature/obscuration/co/eco2 as-is, smoke_detected → `smoke`, other → `other`) |
| `observation.created` → `camera` | → `TelemetryIn` metric_type=`video_event`, clip metadata in `payload` (video itself is not downloaded) |
| `observation.created` → `access` | → `TelemetryIn` metric_type=`access` |
| `observation.created` → `people_count` | → `TelemetryIn` metric_type=`occupancy` |
| `observation.created` → `connectivity` | → `TelemetryIn` metric_type=`system`, `availability=fresh/disconnected` |
| `observation.created` → `radio_transcript` | → `TelemetryIn` metric_type=`radio_audio`, `transcript` filled, `audio_url=null` (see below) |
| `observation.created` → `radio_audio` | **Skipped** — this is metadata of raw audio chunk (media_id/timing) without text; without audio download nothing to save beyond what `radio_transcript` already carries |
| `device.updated` | **Not forwarded** as a separate record (this is a summary derivative of already-sent readings — resending would duplicate `TelemetryReading`); used only for enriching `DeviceIn` (type/name/room) of this device's next readings |
| `run.updated`, `room.updated`, `camera.updated`, `access.updated`, `occupancy.updated`, `radio.channel.updated`, `system.updated`, `stream.reset` | Skipped as session-level state, not raw observation (`stream.reset` the bridge handles separately — as a generation barrier) |

Devices from this source get `external_id` with prefix `sm-` (e.g.,
`RADIO-A` → `sm-RADIO-A`), to not collide with curl/MCP-simulated devices.

**Continuous audio/video (`/media-streams`) is not implemented in this version** —
this is deliberately deferred. `audio_url` remains `null` even for radio transcripts;
only `transcript` is filled (and `audio_duration_ms`, computed from utterance duration).

### Configuration

In `.env` (see `app/core/config.py` for current fields and default values):

**Local mode (default — for development and integration checks):**

```env
STATE_MACHINE_BASE_URL=https://api.aitinkerers.space/api/v1
STATE_MACHINE_BEARER_TOKEN=<from 1Password, vault aitinkerers-hack, item "State Machine API">
STATE_MACHINE_SCENARIO_ID=degraded
# or palisades-focus / palisades-full — for demo with radio transcription (see PALISADES.md)
OUR_API_BASE_URL=http://localhost:8000
```

Here `control_token` is allowed (needed for `POST /runs` and `play`) — this mode creates
and **itself** controls its own run, which the deploy instructions explicitly allow
"for integration checks".

**Production mode (shared run, without creating/managing):**

```env
STATE_MACHINE_RUN_ID=<agreed run_id, shared with UI team and other consumers>
STATE_MACHINE_BEARER_TOKEN=<read_token — NOT control_token>
OUR_API_BASE_URL=http://localhost:8000
```

When `STATE_MACHINE_RUN_ID` is set, the bridge ignores `STATE_MACHINE_SCENARIO_ID` (run
already exists and is not created by us), does not call `POST /runs`, does not send `play`/
`pause`/`reset` — only reads SSE. Therefore `read_token`
is enough here (read/SSE/media); `control_token` is not needed and should not be used in this
mode — a production consumer should not have the ability to control someone else's
shared run.

Token is **never** hardcoded and never appears in code/logs/commits — only via
environment variable; actual value is obtained from 1Password independently.

### Running

Our API should be up (`uvicorn app.main:app`), then in a separate terminal:

```bash
python -m app.adapter.bridge
```

This is a long-lived process (not part of FastAPI/request lifecycle) — keep it running
as long as you need the live data stream.

---

## Deployment

### For running the CORE platform (REST/SSE/MCP API, ingestion) — minimal required setup

**A new participant can run a fully working base platform from a clean clone:**

1. `cp .env.example .env` — done, no need to change anything else. By default:
   - `API_KEY=dev-secret-change-me` (can be any string, real one generated if needed)
   - `DATABASE_URL` and `REDIS_URL` point to internal docker containers (`db:5432` and `redis:6379`
     inside the docker network)
2. `docker compose up --build` brings up the CORE stack:
   - `db` (Postgres) and `redis` with healthchecks
   - `app` (FastAPI backend): waits for `db` and `redis`, applies migrations (`alembic upgrade head`),
     starts uvicorn at `http://localhost:8000`
3. Check: `curl http://localhost:8000/health` should return `{"status": "ok"}` (this path has no auth);
   any other path requires `X-API-Key` header.
4. `GET http://localhost:8000/docs` — Swagger UI for live testing of all endpoints.
5. Send test telemetry via `POST /ingest/telemetry` or use `curl` examples in the
   "For the simulator team" section above.

**No real secrets are required** for the CORE platform to work and for testing all three
interfaces (REST, SSE, MCP).

### For running the bridge to live State Machine (optional)

If you need real events from the simulator team:

1. Get `STATE_MACHINE_BEARER_TOKEN` (from vault aitinkerers-hack, item "State Machine API")
2. Fill in `.env`: `STATE_MACHINE_BEARER_TOKEN=<value>`
3. `docker compose up --build` will also bring up the `bridge` service (`app/adapter/bridge.py`), which
   will connect to `https://api.aitinkerers.space`, open the scenario SSE stream, and send
   real events to `POST /ingest/telemetry`. The rest of the platform does not change —
   the dashboard and MCP clients see real data through the same API.

**Without `STATE_MACHINE_BEARER_TOKEN` the `bridge` service does not start**, but the CORE platform works fully,
and you can test via curl/examples with synthetic data.

### Additional deployment details

- By default `docker compose up` also picks up `docker-compose.override.yml` (bind-mount repo +
  `uvicorn --reload`) — only for local development. On a server run
  `docker compose -f docker-compose.yml up --build -d` (without override).
- Outside this repo: choice of host, TLS/certificates, reverse proxy, domain, and distribution of
  real secrets in `.env` on the server — these are organizational/infrastructure decisions.
