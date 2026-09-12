# Agent service

Backend for the agent-owned portion of the firefighter interface. This directory is independent of the simulator, telemetry platform and dashboard projects.

## Quick start

From this directory (Python 3.12 and uv):

```sh
uv sync --frozen
uv run uvicorn fire_agents.api:create_app --factory --host 127.0.0.1 --port 8010
```

Open http://127.0.0.1:8010/docs. The default `FixtureEngine` is a clearly labelled deterministic test double, not a live LLM. It echoes input descriptions for questions and reads explicit fixture annotations for background extraction.

In a second terminal:

```sh
uv run python -m fire_agents.ui_demo --url http://127.0.0.1:8010 assign
```

This creates the local `ui-demo` session and one synthetic task. The UI context is:

```json
{"demo_context_id":"ui-demo","generation":0,"subject_id":"all"}
```

Run `complete` instead of `assign` to submit a synthetic completion report. It updates the same card. Run `reset` for a new generation; use the generation returned by the command. These are synthetic integration records, not verified Palisades data or real platform readings.

## UI v1 endpoints — implemented locally

| Method | Purpose |
|---|---|
| POST /agent/v1/questions | Durable asynchronous question, 202 queued |
| GET /agent/v1/questions/{request_id} | Current answer and actual retrieval trace |
| POST /agent/v1/questions/{request_id}/cancel | Idempotent cancellation |
| GET /agent/v1/state | Answers and cards for one context |
| GET /agent/v1/cards/{hypothesis_id} | Stable card ID, increasing revision |
| GET /agent/v1/evidence/{evidence_id} | Context-scoped reading and honest media status |
| GET /agent/v1/events | SSE change hints, reread the corresponding GET endpoint |

GET/cancel requests require `demo_context_id`, `generation`, `subject_id` query parameters. Create question accepts `context`, `client_request_id`, `question`, `language` (en/ru). Full schemas are available from the running `/openapi.json`.

Example:

```sh
curl -X POST http://127.0.0.1:8010/agent/v1/questions \
  -H 'Content-Type: application/json' \
  -d '{"context":{"demo_context_id":"ui-demo","generation":0,"subject_id":"all"},"client_request_id":"example-1","question":"What has been reported?","language":"en"}'
```

UI fetches `/state` initially and after reconnect. SSE is a hint with no replay promise; periodic state refresh is still required. Ignore stale revisions. Stop players and discard old fetch results when generation changes. `client_request_id` retries reuse the same request; a different body with that key returns 409.

## Scope and authentication

Session setup automatically binds the development subject `all`. More restricted subjects must be registered internally with `UIService.bind_context(..., device_ids=[...])`. Callers cannot change a subject's source scope through question parameters. Only records at or before the question's captured scenario clock are considered.

By default there is no authentication: bind only to loopback. For a shared demo, set `FIRE_UI_SESSION_TOKEN` and have a trusted same-origin proxy supply the HttpOnly `fire_ui_session` cookie. The same cookie then protects legacy setup routes too. This is a shared demo credential, not a multi-user authentication system; a login/session issuer, CSRF protection and production access policies are not implemented. The platform key stays server-side. Never expose an unauthenticated server publicly.

## Model execution

Set `FIRE_ENGINE=sdk`, `FIRE_MODEL` and `OPENAI_API_KEY` in the process environment to use OpenAI Agents SDK. `.env` is not loaded automatically. Real provider calls have not been exercised. `FIRE_ENGINE=fixture` is the default. Structured model output is checked for valid evidence IDs; an independent semantic verifier is still pending. OpenRouter fallback is not implemented.

## Platform adapter

`FIRE_PLATFORM_API_KEY` supplies access; the full MCP URL is explicit:

```sh
uv run python -m fire_agents.platform_cli --url http://localhost:8000/mcp-server/mcp pull \
  --session ui-demo --generation 0 --device DEVICE_UUID \
  --since 2026-09-12T10:00:00Z --until 2026-09-12T10:05:00Z --epoch 2026-09-12T10:00:00Z \
  --description-field description --media-field audio_url
```

Import does not advance the scenario clock. `POST /sessions/{sid}/{generation}/clock` controls it explicitly. `publish-one` sends one outbox publication to the real platform only when explicitly invoked. Network integrations are disabled by default. MCP and SSE helpers are tested with fake transports; a continuous live import loop is not wired into API lifespan yet.

Incidents remain in Data Platform. The UI card is a projection with `platform_incident_id`, separate assessment and publication state. The publisher preserves an existing operator status and adds a note. Unknown writes become `uncertain` and are not blindly retried. Only one publisher per database is supported. Platform status is null until an actual status has been obtained; the UI must not infer it from the agent assessment.

## Evidence and limitations

- Evidence requires a positive platform reading ID. Synthetic demo records are explicitly marked as synthetic. Claims without a reading ID are withheld.
- Original audio URLs, tickets and secrets are not exposed in raw JSON. No trusted media resolver is configured yet: audio is `pending` or `missing`, never falsely `available`.
- Questions search a local imported slice of up to 20 records / 24,000 characters. Completeness stays partial/unknown. Full history retrieval is not implemented.
- Claim text generated by the model is conservatively tagged `inference`. Source descriptions in cards are source reports, not proof of execution.
- Ordinary task linking requires an explicit task_ref. Radio-channel checks use the separate correlation rules below.
- SQLite stores events, tasks, questions, cards and publication intents. PostgreSQL migration remains future work.
- Persisted questions use leases and cancellation checks. SDK traces are not the durable state store. API and background tasks are intended to run in one process for this MVP.
- Two additional monitoring scenarios, automatic media playback, production auth and independent semantic checking are not complete.

## Tests

```sh
uv run python -m pytest -q
```

Tests cover API contracts against the handoff schemas, async processing, idempotency, cancellation, resets, subject boundaries, future-data exclusion, recovery, SSE, redaction and platform publication ambiguity. No live model, actual platform or real audio is involved.

The original handoff in `outputs/agent-ui-contract-v0.1/` is retained as a historical proposal. See `outputs/ui-v1-implementation.md` for the current delivery status. All service files live under `agent-service/`; do not modify other teams' directories.

## Radio-channel checks (Palisades)

The SDK extractor now distinguishes `channel_requested`, `channel_assigned` and
`channel_acknowledged`. It receives the current utterance plus at most 20 prior
records / 24,000 characters from the same source in the preceding 60 seconds.
This lets a request reference a group named in a preceding transcript fragment;
that fragment must also be cited. Future records are not processed before the
scenario clock reaches their publication time. Ingest transcript records with
`time_ms` set to the end of the published utterance.

A persisted reducer links an assignment only to one matching recent request on
the same source. An acknowledging reply must explicitly contain the same channel,
follow its assignment within 30 seconds, and have only one candidate exchange.
These windows are conservative demo configuration in code, not radio protocol
rules. Unknown speakers remain unknown. Ambiguous or unmatched facts are retained
for chronological rebuilding after late delivery, but do not support a card.

The existing `/agent/v1` card contract is unchanged. One card progresses from
assignment not found, to assignment found/reply not found, to reply found.
`statement` describes the phase; each original utterance remains a separate
source claim with evidence. `supported` means a matching reply was found in the
transcript, never that the group switched or completed a task. Without all reading
IDs it remains `insufficient_data`. Channel cards do not emit task-completion
publications; platform publication for this new hypothesis is still pending.

The fixture engine accepts the three new actions with `team` and `channel` in
`payload.fixture` for integration tests. SDK extraction uses source text, with no
Palisades answer fixtures or hardcoded group/channel names. Real model extraction
and platform mapping still need a live acceptance run. Tests exercise phased
replay, omitted/wrong/ambiguous replies, clock boundaries, late delivery, reset,
reading IDs and compatibility with the existing UI schema.

## Data Platform → agents → web integration

The adapter is aligned with `origin/feat/platform` at `c8aee50`. It reads canonical
`transcript` and `audio_url` fields, with legacy payload fallback, and imports in
chronological order. The platform branch was inspected without merging over local work.

To enable polling in the API process, export the following before starting it
(the `.env` file is not loaded automatically):

```sh
export FIRE_PLATFORM_URL=http://localhost:8000/mcp-server/mcp
# Supply FIRE_PLATFORM_API_KEY through your local environment.
export FIRE_PLATFORM_SCOPE='{"session_id":"platform-demo","generation":0,"device_ids":["DEVICE_UUID"],"since":"2026-09-12T10:00:00Z","until":"2026-09-12T10:05:00Z","epoch":"2026-09-12T10:00:00Z","poll_seconds":5}'
uv run uvicorn fire_agents.api:create_app --factory --host 127.0.0.1 --port 8010
```

The service creates the session if absent and binds a device-filtered web context
with `subject_id=platform`. Existing sessions retain their generation. A generation
mismatch stops the importer; restart with an explicitly updated scope after reset.
`GET /health` reports connection state, latest import counts and possible truncation.

Replay time remains operator-controlled: advance it through
`POST /sessions/platform-demo/0/clock` with `{"time_ms":300000}` to make that interval
available to workers and the UI. For model analysis configure `FIRE_ENGINE=sdk`,
`FIRE_MODEL` and `OPENAI_API_KEY`; FixtureEngine does not interpret platform transcripts.

The web client uses `/agent/v1/state` and `/agent/v1/events` with query parameters
`demo_context_id=platform-demo&generation=0&subject_id=platform`, and submits questions
to `/agent/v1/questions` with the same context. Existing cards, answers and evidence
continue through that contract. Platform credentials stay in the backend.

This importer re-reads the fixed interval to catch late arrivals and deduplicates
reading IDs. It does not advance the interval or assume complete history: the
platform caps results at 500 per device without stable pagination. Split large
replays into smaller scopes until pagination is available. Polling currently supplies
updates without the optional platform SSE wakeup listener. Publishing observations
back to the platform remains the separate explicit `publish-one` command.
Audio references are retained, but playable URLs still require a trusted media resolver.

Validation: mocked platform reads, duplicate imports, canonical transcript/audio,
web context and reset isolation are tested. A live platform connection and real
model calls have not been verified by these tests.
