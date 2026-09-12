# 0008. Build our own State Machine bridge/adapter; dual-mode local vs. shared production run

**Status:** Accepted

## Context

The simulator team's "State Machine" API went from an undeployed draft to a real, live, deployed
service (`https://api.aitinkerers.space/api/v1`) mid-hackathon, with real Bearer-token auth and a
pull/SSE/run-based consumption model (see ADR-0004). We had already decided not to change our own
ingestion contract to match theirs. That left the question of how real data would ever reach our
platform at all.

Options considered: (a) ask the simulator team to build a push adapter into *our* contract
themselves; (b) do nothing and stay on hand-crafted curl examples; (c) build our own adapter that
consumes their pull/SSE model and re-posts through our own existing `/ingest/telemetry`.

## Decision

- Build the bridge ourselves (`app/adapter/bridge.py`), as a separate long-running process (not
  part of the FastAPI request lifecycle) that: creates/resumes a State Machine run, opens its SSE
  stream with correct chunk-boundary-safe parsing (`httpx-sse`), maps each relevant event kind to
  our `TelemetryIn` shape, and POSTs it to our own ingestion endpoint like any other client.
  Continuous audio/video HTTP streaming was explicitly descoped for this pass — text/state only.
- **Two operating modes**, driven by the simulator team's own deployment guidance once it arrived:
  - **Local/dev mode** (default, `STATE_MACHINE_RUN_ID` unset): creates and controls its own run
    with a `control_token`, sends `play`. Used for local development and integration testing.
  - **Production/shared mode** (`STATE_MACHINE_RUN_ID` set): subscribes to one externally-agreed
    run with a `read_token`, never calls `create_run` or sends any command (`play`/`pause`/
    `reset`) — a production subscriber must not control a run it doesn't own, and multiple
    independent consumers must watch the *same* run/clock, not each spin up their own.

## Consequences

- Every downstream contract (REST/SSE/MCP, and everything the dashboard/agent teams built
  against) stayed stable regardless of what the upstream source did — the bridge absorbs that
  churn.
- The mode split meant a config-only change (`STATE_MACHINE_RUN_ID` + `read_token` vs. unset +
  `control_token`) flips between "my own sandbox run" and "the team's shared live run," with no
  code change — the same image runs in both places.
- Real data (a real Palisades wildfire radio-transcript demo, real D-Fire camera-dataset
  provenance) flowed through the exact same ingestion path as synthetic curl examples, which
  validated the platform contract design (ADR-0004) rather than requiring a special path for
  "real" data.
- A concrete bug surfaced by exactly this mode split: `docker-compose.yml` never forwarded
  `STATE_MACHINE_RUN_ID` into the bridge container's environment, so the "production mode" setting
  silently had no effect until caught during the actual deployment — fixed once found.
