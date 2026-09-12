# 0004. Keep our push contract; extend the data model instead of adopting the simulator's architecture

**Status:** Accepted

## Context

The platform was built first against our own push-based ingestion contract (`POST
/ingest/telemetry`, upsert-by-`external_id`). Partway through, the simulator team shared their
own draft contract ("Fire Safety State Machine v0.2/v0.2.2") describing a fundamentally different
shape: a pull-based, run/generation/sequence/cursor SSE architecture where consumers subscribe to
a stateful "run," not push events in. Their document was rich — device/room/camera/access/
occupancy/radio/system state, provenance, technical-freshness semantics (quality/availability).

This raised a real fork: rebuild our ingestion around their pull/SSE/run model, or keep our own
contract.

## Decision

- **Keep our own push-based contract.** Do not adopt runs/generation/cursor/SSE-as-source-of-
  truth into our ingestion path.
- **Do** port the *data* concepts their contract identified as valuable, additively, into our
  existing schema: `quality`, `availability`, `provenance` (free-form), `external_event_id`, and
  a widened `metric_type` vocabulary (`access`, `occupancy`, `radio_audio`, `system`,
  `obscuration`, `co`, `eco2`). No schema churn beyond additive nullable columns.
- Later, once the simulator's State Machine actually went live on a real server, this was
  revisited (see ADR-0008): we built a *bridge* that consumes their pull/SSE model and re-posts
  through our own existing push contract, rather than changing the contract our downstream teams
  already integrated against.

## Consequences

- Dashboard and agent teams integrated against a contract that never changed shape mid-hackathon,
  even though the upstream source's own contract kept evolving underneath (v0.2 → v0.2.1 → v0.2.2
  added continuous media, then prerecorded transcripts).
- We benefited from their domain modeling (quality/availability/provenance) without inheriting
  their operational complexity (run lifecycle, generation resets, cursor-based reconnection,
  media ticketing).
- The cost is a translation layer (the bridge, ADR-0008) that has to track their contract's
  evolution on one side while presenting a stable contract on the other.
