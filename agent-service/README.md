# Agent service

This folder owns the agent backend for Fire Incident Copilot. Its main job is to
maintain evidence-backed state that the web dashboard reads: the current channel
check, answers to operator questions, source references and explicit unknowns.
The web renders this state. Creating Data Platform incidents is optional and is
not required for the Palisades flow.

This README describes the current implementation as of September 12, 2026. Earlier
plans in `outputs/agent-system-plan.md` and status notes describe previous stages;
where they disagree, use the executable code and the current integration records.
The live State → Platform → local SDK agent → browser path is now implemented and
was exercised on September 12. Start with the [project quickstart](../docs/QUICKSTART.md)
and [live validation](../dashboard/live/VALIDATION.md). This is still a prototype;
the local fixture and optional standalone platform poller are separate modes.

## Ownership and data flow

```text
Replay / source producer → Data Platform → scoped importer → SQLite events
                                                            │
                                      background extraction ─┤
                                      channel correlation    │
                                                            ↓
Web ← /agent/v1/state + GET endpoints ← state projections and evidence
Web → /agent/v1/questions → question queue → bounded retrieval → answer
```

- The source producer supplies recordings, machine transcripts, IDs and times.
- Data Platform owns source readings. The agent database is an imported working
  slice plus derived state, not a competing source of truth.
- This service owns ingestion, model calls, correlation, durable work, context
  boundaries, questions and the agent-to-web API.
- The dashboard owns presentation, operator interaction and the evidence viewer.
- Speech recognition, video analysis, tactical commands and radio transmission
  are outside this service's scope.

## The two agent roles

| Role | Input | Output | Execution |
|---|---|---|---|
| Radio fact extractor | Current event and bounded preceding context | Typed `Extraction`, with source IDs | Background event worker |
| Incident fact assistant | Operator question and bounded imported events | Typed claims and limitations | Durable question worker |

`SDKEngine` defines these two agents with OpenAI Agents SDK. There are no agent
handoffs, autonomous planning agents or model-controlled platform writes. The
application retrieves data and passes it to the model; the agents do not currently
choose MCP tools or search the full platform history themselves. Each SDK run has
at most three turns per model and a 28-second total budget inside the UI's
30-second timeout (14 seconds per model when fallback is enabled).

Correlation, timestamps, retries, persistence and UI revisions are application
code. They do not require another model call. The question agent does not create
or update background checks. It answers from source events, so it can reread some
of the same material; shared semantic-result caching is not implemented.

The default `FixtureEngine` is a deterministic test double. It reads explicit
`payload.fixture` annotations for extraction and echoes source descriptions for
questions. It does not understand arbitrary transcripts or translate answers.
Live SDK extraction and answers have been exercised on synthetic messages and the
composite State/Palisades replay through OpenRouter. Semantic accuracy against a
human reference remains unvalidated.
See [scope and results](docs/OPENROUTER.md).

## Palisades channel check

The target demo follows a recorded exchange about a working channel for Coastline
Structure Defense Group. The expected sequence is a request, assignment of
V-Fire 25, and a separate acknowledging reply. Neither the group nor the channel
is hardcoded in the correlation logic.

The extractor distinguishes `channel_requested`, `channel_assigned` and
`channel_acknowledged`. A bare channel mention or intent to switch must not be
classified as an acknowledgement. It classifies the current utterance; a group
named in a preceding fragment can supply context for a request only with a source
citation. Speakers must not be invented.

Preceding context is bounded to 20 candidate records / 24,000 characters within
60 seconds, filtered to the same source. The SQL candidate limit is applied before
the source filter, so other-source traffic can reduce the resulting context.
Background jobs wait until `event.time_ms` is at or before the scenario clock.
For transcript ingestion, publication time must represent the end of the utterance;
the platform adapter currently derives it from the reading timestamp, so the source
producer must align that timestamp with publication availability.

The persisted reducer in `fire_agents/channels.py`:

1. Opens a check from a request with an identified group; a repeated request can
   extend a unique recent pending check.
2. Links an assignment to exactly one compatible request on the same source within
   60 seconds of its last linked event.
3. Links a reply only when its normalized channel matches exactly one candidate
   assignment on the same source, strictly after it and within 30 seconds.
4. Rebuilds from stored extracted facts in event order when late data arrives.
   Ambiguous or unmatched facts remain stored without supporting a conclusion.

These time windows are conservative demo heuristics, not radio protocol rules.
A matching channel and timing do not establish speaker identity. Extraction still
needs evaluation on the actual unverified machine transcript.

The same check normally retains its `hypothesis_id`; its revision increases when
state changes. A late event that changes correlation can replace a check identity,
so the web must reconcile snapshots rather than assume every ID exists forever.

| Published state | `assessment` | Meaning |
|---|---|---|
| Assignment not found | `insufficient_data` | Not found in processed inputs |
| Assignment found; reply not found | `insufficient_data` | Assignment has a source; acknowledgement remains unknown |
| Acknowledging reply found | `supported` | Transcript contains a linked reply; all linked events have reading IDs |

`statement` describes the phase. Separate source claims reference the original
utterances. Missing reading IDs keep the assessment at `insufficient_data`.
Every channel check states that the recording does not establish that all group
members switched. A control replay omitting the reply must remain unconfirmed.
Channel checks have no task-completion timer and enqueue no incident publications.

## Durable state and duplicate work

SQLite stores sessions, source events, jobs, ordinary task watches, channel facts,
channel checks, questions, UI projections, evidence mappings and optional outbox
records. SDK traces are not the state store. Run one API process for this MVP;
PostgreSQL migration and distributed-worker operation are not implemented.

- An event is unique within session/generation by event ID. Identical reimports
  do not create another job; changed content under the same ID is rejected.
- Event jobs use a 45-second lease, a claim token and up to three failed attempts.
  A recovered expired job can repeat a model call. This is not exactly-once model
  execution, but stale tokens cannot commit a second result.
- Questions use a 40-second lease and durable status. `client_request_id` reuses
  the same request for an identical body; a different body returns 409. A different
  client key creates independent work, even for identical question text.
- Cancellation and generation changes prevent an in-flight answer becoming current.
  Expired question work can be reclaimed; error results are returned explicitly.
- Reset advances generation, resets the clock and isolates old state. The platform
  importer stops on generation mismatch and requires an updated explicit scope.
- UI projections are read from this state. The web must not run a second independent
  agent analysis to recreate the same background conclusion.

The older ordinary-task monitor remains supported: `assigned`, `accepted`,
`completed`, `cancelled`, with an explicit `task_ref`. Its timeout uses scenario
rather than wall time. A completion is a report (`supported_by_report`), not proof
of execution. This separate path is not the Palisades channel workflow.

## Web API

| Endpoint | Purpose |
|---|---|
| `POST /agent/v1/questions` | Submit a question, HTTP 202 |
| `GET /agent/v1/questions/{request_id}` | Read answer status, claims and retrieval trace |
| `POST /agent/v1/questions/{request_id}/cancel` | Idempotent cancellation |
| `GET /agent/v1/state` | Snapshot of current answers and checks |
| `GET /agent/v1/cards/{hypothesis_id}` | Read one check projection |
| `GET /agent/v1/evidence/{evidence_id}` | Read scoped source evidence and media status |
| `GET /agent/v1/events` | SSE change hints |

Context is `{demo_context_id, generation, subject_id}`. GET/cancel requests pass
these as query parameters. A question body includes `context`, `client_request_id`,
`question` and `language` (`en` or `ru`). Questions capture the scenario clock at
submission and retrieve at most 20 events / 24,000 characters within the bound
subject. Retrieval traces report `local_event_query`, not an invented MCP call.

Fetch `/state` initially, after reconnect and periodically. SSE has no replay
promise; on a hint, reread the relevant GET endpoint. Ignore older revisions.
On generation change, discard old requests and stop old media. Snapshot membership
is authoritative. Runtime schemas are served at `/openapi.json`; retained contract
examples are in `outputs/agent-ui-contract-v0.1/` and are schema-tested.

Session setup binds development subject `all`. Internal `UIService.bind_context`
can register immutable device scopes. Platform polling binds subject `platform`.
Question parameters cannot expand a registered subject's scope. The legacy
`POST /agent/questions` route is deprecated and does not have the v1 retrieval
boundaries; integrations should use `/agent/v1` exclusively.

## Evidence and uncertainty

Claims must cite known event IDs. Channel citations are checked against the same
source and a preceding time window. The UI requires positive reading IDs and
withholds question claims without them. Model-generated answer claims are tagged
`inference`; original descriptions in check projections are `source_report`.
There is no independent semantic verifier yet, so valid IDs do not prove that a
model's wording follows from its evidence.

Coverage stays partial/unknown. A failed or bounded search does not establish
absence. Raw source JSON is filtered for URLs and credential-like keys. Audio is
currently `pending` or `missing`: no trusted media resolver or playback URL is
implemented. Audio intervals, transcript provenance and source timestamps need
end-to-end verification. The service does not claim that the historical audio has
been human-verified.

## Run locally

From this folder, with Python 3.12 and uv:

```sh
uv sync --frozen
uv run uvicorn fire_agents.api:create_app --factory --host 127.0.0.1 --port 8010
```

API documentation: `http://127.0.0.1:8010/docs`. For SDK execution, supply
`FIRE_ENGINE=sdk`, `FIRE_MODEL` and `OPENAI_API_KEY` through the process environment.
The `.env` file is not loaded automatically. Set `FIRE_FALLBACK_MODEL` to enable
one fallback attempt after a recoverable model failure; see [OpenRouter setup](docs/OPENROUTER.md).
`FIRE_DB_PATH` selects the database (default `work/runtime.sqlite3`);
`FIRE_WATCH_TIMEOUT_MS` controls the ordinary-task timeout (default 300000).

For synthetic ordinary-task UI integration:

```sh
uv run python -m fire_agents.ui_demo --url http://127.0.0.1:8010 assign
uv run python -m fire_agents.ui_demo --url http://127.0.0.1:8010 complete
```

Read context `{"demo_context_id":"ui-demo","generation":0,"subject_id":"all"}`.
The `reset` command returns a new generation. This utility is not a Palisades replay.
Channel fixtures use the three channel actions plus `team` and `channel`; see
`tests/test_channels.py` for phased and negative examples.

By default the API has no authentication and is for loopback use. A shared demo
can set `FIRE_UI_SESSION_TOKEN`, supplied by a trusted same-origin proxy as an
HttpOnly `fire_ui_session` cookie. It also protects legacy setup routes. This is
not multi-user authentication: login issuance, CSRF protection and production
access policies remain unimplemented. Platform credentials stay on the backend.

## Data Platform import

`Reader` calls `query_telemetry` over MCP, reads canonical `transcript` and
`audio_url` with legacy payload fallback, and imports chronologically. Polling is
wired into the API lifespan only when explicitly configured:

```sh
export FIRE_PLATFORM_URL=http://localhost:8000/mcp-server/mcp
# Supply FIRE_PLATFORM_API_KEY securely in the process environment.
export FIRE_PLATFORM_SCOPE='{"session_id":"platform-demo","generation":0,"device_ids":["DEVICE_UUID"],"since":"2026-09-12T10:00:00Z","until":"2026-09-12T10:05:00Z","epoch":"2026-09-12T10:00:00Z","poll_seconds":5}'
uv run uvicorn fire_agents.api:create_app --factory --host 127.0.0.1 --port 8010
```

Replace the URL, UUID and timestamps with the agreed source scope. The importer
creates the session if absent, preserves existing generation, and binds subject
`platform`. `/health` reports importer state, counts and possible truncation;
inspect the nested platform state as well as the overall worker health.

It repeatedly reads the fixed interval, deduplicating unchanged IDs to catch late
arrivals. The interval does not slide. Results are capped at 500 per device with no
stable pagination, so completeness is not guaranteed. The optional SSE listener in
`live.py` is not connected as a polling wakeup mechanism. Import failures retry;
stale generation stops polling. This standalone polling mode is distinct from the
gateway-owned live pipeline verified in [the integration record](../dashboard/live/VALIDATION.md).

Import does not advance replay time. Use
`POST /sessions/platform-demo/0/clock` with `{"time_ms":300000}` to expose the
corresponding interval. The web uses context
`{"demo_context_id":"platform-demo","generation":0,"subject_id":"platform"}`.
`FixtureEngine` will not interpret imported transcripts; enable SDK execution for
actual model analysis. Manual bounded import remains available via
`python -m fire_agents.platform_cli ... pull`; see its `--help`.

## Optional incident publishing

Incident publication is an independent integration option. Leave it unused when
all that is needed is agent state read by the web. Neither the API workers nor
platform polling invoke the publisher. Palisades channel checks create no outbox
entries and do not create or resolve platform incidents.

The legacy task monitor can enqueue local publication intents. Only an explicit
`platform_cli ... publish-one` invocation sends one to Data Platform. If enabled,
run one publisher per database. It retains the incident link, adds evidence and
notes, and preserves existing operator status on updates. An uncertain write is
marked `uncertain` and is not blindly retried. Automatic reconciliation and remote
exactly-once guarantees are not implemented.

`platform_incident_id` and `platform_status` can remain null. The retained contract
currently uses `publication_status=pending` even when publication is unused; this
is not an instruction to publish or a reason to block the dashboard. A dedicated
`not_requested` contract value would require a coordinated future change.

## Validation and review handoff

Run `uv run python -m pytest -q`. Tests cover state/API schema compatibility,
question idempotency, cancellation, reset, leases, source scope, future exclusion,
channel phases, missing/wrong/ambiguous replies, late delivery, evidence IDs,
mocked platform polling, canonical transcript import and publication ambiguity.
They do not call a real model, connect to a real platform or play audio.

The [live integration record](../dashboard/live/VALIDATION.md) now covers the actual
Palisades channel sequence, shared State context, source IDs, original radio playback,
automatic briefings, operator questions and generation isolation in the browser.
Remaining acceptance work includes a human-labelled semantic evaluation, an omitted
acknowledgement control replay through the real model, and broader latency sampling.
Passing offline tests does not establish those results.

Full-history retrieval, semantic verification, additional monitoring scenarios and
public agent/dashboard deployment remain unfinished. Provider fallback is implemented
and mock-tested; both models were smoke-tested, but forced failover during browser
replay was not demonstrated. Optional incident publication is not required for this demo.

## Code map

| File | Responsibility |
|---|---|
| `fire_agents/api.py` | App lifecycle, workers, setup routes, health |
| `fire_agents/models.py`, `engines.py` | Model contracts and the two agent definitions |
| `fire_agents/runtime.py`, `store.py` | Event work, persistence, leases, clocks, ordinary tasks |
| `fire_agents/channels.py` | Persisted radio-channel correlation |
| `fire_agents/ui_service.py`, `ui_models.py`, `ui_routes.py` | Questions, check projections, evidence and web API |
| `fire_agents/adapters.py`, `platform.py`, `platform_sync.py` | Source mapping, MCP reader, opt-in polling and optional publisher |
| `fire_agents/live.py`, `platform_cli.py`, `ui_demo.py` | SSE helper and manual integration utilities |
| `tests/` | Local behavioral and contract checks |

Keep service changes in `agent-service/`; coordinate changes to other teams' folders
with their owners.

## OpenRouter and local replay check

Set `FIRE_ENGINE=sdk`, `FIRE_PROVIDER=openrouter`, `FIRE_MODEL=google/gemini-3.1-flash-lite`,
`FIRE_FALLBACK_MODEL=openai/gpt-5.6-luna` and `OPENROUTER_API_KEY` in the process environment. The provider uses Chat
Completions with typed outputs and disables SDK tracing. It never substitutes
`OPENAI_API_KEY` for the OpenRouter credential. The default provider remains OpenAI.

Both models use strict typed outputs. The current configuration sets
`FIRE_REASONING_EFFORT=minimal`, `FIRE_FALLBACK_REASONING_EFFORT=none` and
`FIRE_PROVIDER_SORT=latency`. The 28-second request budget gives each model at most 14 seconds
when fallback is enabled. Cancellation never starts the fallback. Extraction text
defaults to English; set `FIRE_OUTPUT_LANGUAGE=ru` for Russian. Answers honor the
question's `language`. See [1Password startup and validation](docs/OPENROUTER.md).

For a local replay using the running platform at port 8000, put `API_KEY` and
`OPENROUTER_API_KEY` in `platform/.env`. From `agent-service/`, run:

```sh
.venv/bin/python scripts/e2e/prepare.py
.venv/bin/python scripts/e2e/serve.py
# In another terminal:
.venv/bin/python scripts/e2e/check.py
```

The scripts import the repository's 43 Palisades transcript segments, start an
isolated OpenRouter agent at port 8011, and submit an evidence-backed question.
Scope, database and results are stored under ignored `work/e2e/`. The preparation
step reuses an existing demo device; use a fresh local platform for a clean import.
The check advances replay time and invokes billable model calls. It checks API
transport and answer completion, not semantic correctness or browser/audio playback.
OpenRouter live model execution still requires a configured OpenRouter key.
