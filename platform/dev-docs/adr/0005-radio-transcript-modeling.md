# 0005. Radio/comms transcripts as TelemetryReading rows, audio storage deferred

**Status:** Accepted

## Context

A new requirement arrived mid-hackathon: ingest a radio/comms feed — transcribed emergency-radio
traffic, with the possibility of an attached original audio clip per message "in the future."
Needed to decide the storage granularity and whether audio itself would be handled now.

## Decision

- One `TelemetryReading` row per transcribed utterance/message (not a continuous raw audio
  stream), reusing the existing `ts`/`end_ts` fields for the utterance's time span.
- Added a new `Device.type = "radio"` (a channel/receiver is a device, like a camera).
- Added three new nullable `TelemetryReading` fields: `transcript` (`Text`), `audio_url`
  (`String`, a *reference*, not the bytes), `audio_duration_ms` (`Integer`).
- Explicitly **out of scope**: hosting/storing actual audio bytes. `audio_url` stays null until
  a real audio-hosting story exists; this was a deliberate deferral, not an oversight.
- When the simulator's own contract later showed a much richer transcript shape (per-word
  timing, model name, delivery/machine-generated/human-verified flags, source dataset
  attribution), those were mapped into the *already-generic* `payload`/`provenance` JSONB
  fields via a documented convention rather than adding more first-class columns — provenance-ish
  fields (model, delivery, verification flags, source attribution) go in `provenance`;
  content-adjacent extras (language, word timings) go in `payload`.

## Consequences

- Zero additional schema migrations were needed to support the richer transcript shape the
  simulator's real data turned out to have — the generic `payload`/`provenance` fields absorbed
  it, validating the earlier decision (ADR-0004) to keep those fields open-ended.
- Evidence-linking (`IncidentEvidence.reading_id`) works unchanged for radio messages, since
  they're just `TelemetryReading` rows like any other metric.
- If real audio hosting is ever needed, `audio_url` is already the field to populate — no schema
  change required then either.
