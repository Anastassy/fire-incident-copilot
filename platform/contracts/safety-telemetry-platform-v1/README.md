# Safety Telemetry Platform — Contract v1

**Status: implemented and running.** This is not a draft — every endpoint and MCP tool
documented here exists in the codebase today (`app/`) and has been exercised locally.

**Base URLs:**
- Production: `https://platform.aitinkerers.space` (target domain once DNS/Caddy deployment completes)
- Local dev: `http://localhost:8000` (configurable — treat it as a client setting, not a constant; see `docker-compose.yml` / `.env` for how the hackathon deployment overrides it)

Three consumer roles share one platform:

- **Simulator team** — pushes sensor/camera/access/radio/system telemetry in.
- **Dashboard team** — pulls REST snapshots and/or subscribes to SSE for live updates.
- **Agent-system team** — reads state and writes incident hypotheses / dashboard specs over MCP.

Start with [CLIENT_FLOW.md](CLIENT_FLOW.md) for the integration sequence for your role.
The machine-readable HTTP contract is [openapi.json](openapi.json) (exported directly from
the running FastAPI app — `app.openapi()`, so it is always in sync with the code that
generated it). The MCP tool contract (not covered by OpenAPI) is [mcp-tools.json](mcp-tools.json),
introspected live from the MCP server. Concrete request/response fixtures are in
[examples/](examples/). Version history is in [CHANGELOG.md](CHANGELOG.md).

## Authorization

Every endpoint except `/health`, `/docs`, `/openapi.json`, `/redoc` requires:

```
X-API-Key: <shared secret>
```

This is **one static key for every caller** (simulator, dashboard, and agent system alike) —
a hackathon-scope simplification, not per-team keys. Default value `dev-secret-change-me`;
the actual value is `API_KEY` in `.env` / `app/core/config.py`. The same header is required
for HTTP, WebSocket (as a connect-time header), SSE, and the MCP `/mcp-server` transport.
There is no per-team scoping, rate limiting, or token expiry in this version — see
`app/core/security.py` for the full (intentionally minimal) mechanism.

## What this platform is (and isn't)

Push-based ingestion + a REST/SSE read API + an MCP read/write API, backed by Postgres
(readings, devices, incidents, dashboards) and Redis (pub/sub for SSE fan-out). There is
no run/session/generation/cursor model: every telemetry event is independent and durably
persisted the moment it's ingested, and SSE streams are fire-and-forget live feeds with
no replay. See [CLIENT_FLOW.md](CLIENT_FLOW.md) for what that means concretely for each
consumer role, including the one known limitation dashboard consumers should plan around.

## Files

| File | What it is |
|---|---|
| [CLIENT_FLOW.md](CLIENT_FLOW.md) | Integration sequence per role, with a diagram each |
| [openapi.json](openapi.json) | Live-exported OpenAPI 3.1 schema (HTTP paths + JSON Schemas) |
| [mcp-tools.json](mcp-tools.json) | All 13 MCP tools: name, description, input schema, return shape |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [examples/](examples/) | Realistic, schema-valid request/response/SSE fixtures |

## Maintenance: Keeping openapi.json in sync

The `openapi.json` file is exported from `app/main.py`'s FastAPI version parameter. When you bump
the version in `CHANGELOG.md`, also update `version=` in `app/main.py`'s FastAPI constructor and
re-export openapi.json:

```bash
.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" \
  > contracts/safety-telemetry-platform-v1/openapi.json
```

This keeps the machine-readable spec's version number synchronized with the contract package version.
