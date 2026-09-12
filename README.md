# Firewatch · Fire Incident Copilot

An incident-support workspace for camera feeds, sensor readings, access events and radio traffic. The operator needs to understand what changed, which information is current and what remains unverified before briefing command.

## Current MVP

The MVP includes all available source types. It uses the Base2 × Palisades replay: synthetic Base2 cameras/building observations plus a separate historical Palisades radio recording. Sharing a replay clock does not make these recordings evidence of the same real incident.

The target workflow links changes in measurements and source availability, lets the operator inspect evidence, and checks whether available records establish presence in a room. Access permission is not occupancy; missing data is not safety. The earlier radio-channel-only demonstration is retained as a component test.

## Run the current interface

Use [dashboard/live/README.md](dashboard/live/README.md) for the Firewatch launcher, private State configuration and agent settings. State credentials remain server-side. The static HTML files in dashboard/docs/design are historical mockups.

## What works and what remains

The live dashboard implements State streams, two CCTV views, radio playback/transcripts, metrics, published history, replay controls and the agent API. The repository also contains the telemetry platform, bridge and agent service. The default fixture agent is a deterministic test handler in a separate synthetic session; it does not analyze the displayed State run. Full multi-source inference and a shared end-to-end evidence context still require validation. See [implementation status](dashboard/IMPLEMENTATION_STATUS.md) and [recorded UI validation](dashboard/live/VALIDATION.md).

## Product and demo documents

- [Current project context](dashboard/PROJECT_CONTEXT.md)
- [Problem, business case and preserved calculations](dashboard/BUSINESS_CASE.md)
- [Evidence Bank](dashboard/EVIDENCE_BANK.md)
- [Multi-source MVP scenario and acceptance](dashboard/MVP_SCENARIO.md)
- [Document audit and preserved originals](dashboard/DOCS_AUDIT.md)

## Provenance

Audio Provided by Broadcastify. [Palisades source package](data/demo/palisades-radio-demo/README.md) records the original audio, machine transcript and CC BY 3.0 US attribution. Synthetic Base2 data is not a reconstruction of Palisades. A validated reduction in response time or loss of life is not claimed. The source-audio license does not automatically license project code.
