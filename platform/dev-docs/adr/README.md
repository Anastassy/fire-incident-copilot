# Architecture Decision Records

Decisions made during the hackathon build of the Safety Telemetry Platform, in the order they
came up. Each ADR captures context, the decision, and consequences — not a full design doc.

| # | Title | Status |
|---|---|---|
| [0001](0001-two-interfaces-no-incident-logic.md) | Two independent interfaces (REST/SSE + MCP), no incident-detection logic in the platform | Accepted |
| [0002](0002-python-fastapi-over-go.md) | Python/FastAPI over Go | Accepted |
| [0003](0003-shared-static-api-key.md) | Single shared static X-API-Key, not per-team keys | Accepted |
| [0004](0004-own-contract-extend-dont-adopt.md) | Keep our push contract; extend the data model from the simulator's contract instead of adopting its pull/SSE/run architecture | Accepted |
| [0005](0005-radio-transcript-modeling.md) | Radio/comms transcripts as TelemetryReading rows, audio storage deferred | Accepted |
| [0006](0006-sse-full-object-payload.md) | SSE events carry the full object, not a narrow delta | Accepted (fixed after initial mistake) |
| [0007](0007-isolated-test-database.md) | Isolate the test database from the live/dev database | Accepted |
| [0008](0008-state-machine-bridge-adapter.md) | Build our own State Machine bridge/adapter; dual-mode local-run vs. shared production run | Accepted |
| [0009](0009-monorepo-via-git-subtree.md) | Join the team monorepo via `git subtree` under `platform/`, preserving history | Accepted |
| [0010](0010-hetzner-deployment.md) | Deploy the full stack via Docker Compose on the shared Hetzner box, isolated from `state-api` | Accepted |
