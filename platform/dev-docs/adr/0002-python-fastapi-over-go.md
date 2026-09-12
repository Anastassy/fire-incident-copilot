# 0002. Python/FastAPI over Go

**Status:** Accepted

## Context

The backend needs to serve ingestion, a REST/SSE API, and an MCP server on a hackathon clock.
Go was raised as an alternative for its throughput/concurrency headroom and lower memory
footprint under a large sensor fleet.

## Decision

Build on Python 3.12 + FastAPI + async SQLAlchemy. Rejected Go for this project.

Reasoning, weighed explicitly:
- Development speed matters more than raw throughput here — the sensor stream is a hackathon
  simulation, not an industrial-scale fleet.
- Pydantic gives request validation, response schemas, and an auto-generated OpenAPI spec for
  free — that OpenAPI doc became the literal machine-readable contract handed to the other two
  teams, which would have been hand-maintained boilerplate in Go.
- The official MCP SDK's Python bindings are more declarative/prototype-friendly than the Go one.
- Go's advantages (throughput, compile-time safety) don't bind at this scale or timeline.

## Consequences

- OpenAPI-driven contract generation became a real, load-bearing part of the team's workflow
  (see the `contracts/` package), which wouldn't have been as automatic in Go.
- If ingestion volume ever became genuinely large (a real industrial deployment, not a hackathon
  demo), this choice would need revisiting — noted, not acted on.
