# 0003. Single shared static X-API-Key, not per-team keys

**Status:** Accepted

## Context

Every interface (ingestion, REST, SSE, WS, MCP) needed some form of access control before being
handed to two other teams. Options considered: no auth at all, one shared static key, or
separate keys per consuming team for finer-grained revocation/tracing.

## Decision

One static `X-API-Key` header, checked by a single `ApiKeyMiddleware`, shared by all callers
(simulator ingestion, dashboard REST/SSE, agent MCP). Exempted paths: `/health`, `/docs`,
`/openapi.json`, `/redoc`. WebSocket ingestion checks the same key manually at the handshake
(middleware doesn't cover WS upgrades).

## Consequences

- Fast to implement and integrate against; every team needs exactly one header value.
- No per-team revocation or attribution — if one team's key leaked there'd be no way to rotate
  just theirs. Accepted as fine for a hackathon's lifetime and trust level.
- The key still had to be treated as a real secret operationally: generated with `openssl rand
  -hex 32` (not left as the code-level dev placeholder `dev-secret-change-me`) for the actual
  deployment, and distributed via a 1Password vault item rather than pasted into any shared
  document.
