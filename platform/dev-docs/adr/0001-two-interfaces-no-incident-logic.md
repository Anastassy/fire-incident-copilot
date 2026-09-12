# 0001. Two independent interfaces, no incident-detection logic in the platform

**Status:** Accepted

## Context

The overall project has three teams: a sensor simulator, a dashboard/UI, and an agentic system
that reasons about incidents. Our team owns the backend platform in between: ingest telemetry,
store it, and expose it. It would have been possible to route the dashboard's data access through
the agent layer, or to have the platform itself decide what counts as a fire/flood/etc.

## Decision

- The platform exposes **two first-class, independent interfaces on one shared store**: REST +
  SSE for the dashboard app, and MCP for the agent system. Neither proxies the other.
- The platform **does not implement incident-detection logic**. `Incident` is a plain record the
  agent system creates via MCP (`create_incident`) after it decides something is happening; the
  platform just stores it and serves it back.
- The dashboard can also read agent-authored "dashboard specs" (custom views assembled by an
  agent on operator request) through the same REST/SSE interface, so a custom, agent-built
  dashboard and the default one are served identically.

## Consequences

- Clear ownership boundary: we build ingestion/storage/API, not reasoning. Kept scope bounded for
  a hackathon timeline.
- The dashboard team is not blocked on the agent team being ready, and vice versa — both can
  integrate against us independently.
- Any future "smart" behavior (auto-detecting fires from telemetry) has to live in the agent
  system, not here — if that boundary is ever wrong, it needs a deliberate follow-up decision,
  not a quiet addition to the platform.
