# 0006. SSE events carry the full object, not a narrow delta

**Status:** Accepted (corrected after an initial mistake)

## Context

The MCP write path (`create_incident`, `update_incident`, `create_dashboard`, `update_dashboard`)
publishes an event to Redis, which `/stream/incidents` and `/stream/dashboards/{id}` relay
verbatim to SSE clients. The first implementation published only a narrow subset of fields (e.g.
an incident event carried just `{id, type, status, severity, summary}`), on the assumption that
SSE was a "something changed, go re-fetch via REST" signal.

A later documentation review caught that this contradicted what was actually documented/expected
(a full `IncidentOut`/`DashboardOut`-shaped object) and would leave dashboard clients missing
`location`, `metadata`, timestamps, and evidence unless they made a follow-up REST call for every
SSE event.

## Decision

Publish the **full object shape** (matching the REST `GET` response exactly, including incident
`evidence`) on every incident/dashboard write, not a narrow field subset. The SSE relay itself
(`app/api/streams.py`) needed no change — it was always a correct dumb relay; the bug was in what
got published.

## Consequences

- Dashboard clients can apply an SSE event directly as the new state for that entity (upsert by
  `id`) instead of treating every event as a mandatory REST-refetch trigger.
- Re-fetching on reconnect is still advised (there's no replay/cursor system in this version —
  see ADR-0008's contrast with the simulator's own cursor-based SSE), but that's a different,
  still-true limitation, not the reason to distrust an individual event's contents anymore.
- Caught late (after the dashboard-facing contract had already been documented and handed off)
  because the writer and the documentation were produced by different people/passes without a
  cross-check — worth a lesson: contract docs and the code that produces the wire format need to
  be verified against each other, not just against the schema types.
