# Firewatch · Fire Incident Copilot — submission preparation

**City:** Valencia  
**Participant portal:** https://valencia.aitinkerers.org/hackathons/h_GVqIXzHKOYA  
**Repository:** https://github.com/Anastassy/fire-incident-copilot  
**Public demo video:** pending publication  
**Public project post:** pending publication

Prepared September 12, 2026 using the [Agents Everywhere guidance](https://github.com/CopilotKit/agents-everywhere-starter-kit). This prepares a submission; it does not submit an entry or assert organizer acceptance. Valencia's current portal/handbook takes precedence. Its documentation fetch returned HTTP 403, so the deadline and local posting instructions remain unverified here.

## Project description

Firewatch gives an operator supporting incident command a live workspace for sensor readings, camera feeds and radio traffic. Incident Copilot watches the published stream, updates an evidence-linked briefing, and answers questions using the selected replay and source records. The operator can move from a claim to a measurement or radio utterance, hear its source when available, and see what remains unknown.

The demo asks: **what changed in Gradas, and do the available records establish whether anyone is inside?** Power-loss observations, source availability and radio reports remain distinguishable. A camera view or access record does not automatically establish occupancy. The output helps the operator assemble an inspectable account before briefing command.

This is a composite training demonstration: synthetic Base2 building/CCTV observations and independent historical Palisades radio share a replay clock. They are not recordings of one real incident. No emergency equipment is controlled.

## Context and implemented interaction

Before a question is typed, the surface knows the selected run, generation, clock, published history and device availability. The agent receives that bounded context automatically. Answers appear next to the live evidence, with links to underlying readings and utterances. A standalone chat would require the operator to collect, timestamp and paste that context manually.

| Step | Implementation |
|---|---|
| Receive/persist State observations | [Pipeline](dashboard/live/pipeline.py), [Platform ingestion](platform/app/services/telemetry_service.py) |
| Import reading IDs and replay time into an isolated context | [Pipeline](dashboard/live/pipeline.py), [agent runtime](agent-service/fire_agents/runtime.py) |
| Extract radio facts and answer from bounded context | [SDK engines](agent-service/fire_agents/engines.py), [model input](agent-service/fire_agents/model_input.py) |
| Correlate requested, assigned and acknowledged channels | [Channel reducer](agent-service/fire_agents/channels.py) |
| Present briefing, questions, sources and unknowns | [UI](dashboard/live/app.js), [agent UI service](agent-service/fire_agents/ui_service.py) |
| Reconnect or change replay generation | [Pipeline journal](dashboard/live/pipeline.py), [UI state](dashboard/live/state.js) |

## Technologies actually used

| Technology | Contribution | Boundary |
|---|---|---|
| OpenAI Agents SDK | Typed radio extraction and incident answers | Application-controlled retrieval; no autonomous tool selection or handoffs |
| OpenRouter | Model requests and configured fallback | Account credentials and billable inference |
| Google Gemini 3.1 Flash Lite | Current primary model through OpenRouter | No CCTV pixel analysis |
| OpenAI GPT-5.6 Luna | Current fallback through OpenRouter | Both models smoke-tested; forced live browser failover not recorded |
| ElevenLabs | English narration for the film | Production only, not runtime radio recognition |
| FastAPI, SQLite, PostgreSQL, Redis | APIs, durable work, telemetry persistence and streams | Local/hosted responsibilities specified in the quickstart |

CopilotKit runtime components are not installed. Its starter kit supplied submission guidance, not this application. Sponsor names do not imply endorsement; unused tools are not claimed as integrations.

## Evidence for the judging criteria

| Criterion | Firewatch evidence |
|---|---|
| Core Requirements & Functionality | Play → observations → briefing → question → cited answer/source. [Live validation](dashboard/live/VALIDATION.md); film interface sequence at 00:25–01:30 |
| Innovation & Theme Alignment | Embedded incident context supplies replay time, availability and source identity before the prompt. [Product context](dashboard/PROJECT_CONTEXT.md), [pipeline](dashboard/live/README.md) |
| Technical Execution & Integration | State SSE → Platform readings → SDK → browser. [Architecture decisions](platform/dev-docs/adr/README.md), [tests](scripts/verify.sh), [reconnect/generation validation](dashboard/live/VALIDATION.md). Cancellation/fallback are code-tested; not every recovery path is shown in the film |
| Usefulness & Agentic Experience | An operator asks about a developing situation, inspects evidence and retains unknowns in a briefing. [Scenario](dashboard/MVP_SCENARIO.md). Human control is demonstrated; time saved and factual accuracy are not measured against a human baseline |

## Build history and eligibility

The [general rules](https://github.com/CopilotKit/agents-everywhere-starter-kit/blob/main/hackathon-rules.md) distinguish reusable components from entering an extension of a pre-existing project as new. The exact boundary needs team confirmation against Valencia's rules before eligibility can be marked complete.

**Earlier material:** research, dataset preparation, Blender scenes and a local replay/simulation prototype existed before September 12. The external State service and prepared media are supporting inputs; importing them into Git during the event does not establish when they were authored. Historical audio, the prepared machine transcript, synthetic camera assets, third-party libraries and model services are also not original event code.

**September 12 repository milestones:** these commits document delivered components/integration. Commit dates establish repository history, not the authorship date of every imported line.

| Milestone | Commit |
|---|---|
| Agent service and durable API | [3a7faec](https://github.com/Anastassy/fire-incident-copilot/commit/3a7faec) |
| Telemetry platform import | [8294ebf](https://github.com/Anastassy/fire-incident-copilot/commit/8294ebf) |
| Live dashboard | [034c60c](https://github.com/Anastassy/fire-incident-copilot/commit/034c60c) |
| Copilot as the main workspace | [07c5eb0](https://github.com/Anastassy/fire-incident-copilot/commit/07c5eb0) |
| Shared live State/radio analysis and fast fallback | [5140b63](https://github.com/Anastassy/fire-incident-copilot/commit/5140b63) |
| Complete film and sharp recapture | [3b401e5](https://github.com/Anastassy/fire-incident-copilot/commit/3b401e5), [3e708d7](https://github.com/Anastassy/fire-incident-copilot/commit/3e708d7) |

- [x] Reused research, data and simulation preparation disclosed.
- [x] Delivered interaction mapped to implementation.
- [ ] Component owners confirm the event-authored boundary and imported implementation.
- [ ] Team confirms this scope meets Valencia's new-project rule; clarify with organizers if needed.

## Reproduction and checks

- [x] [English quickstart](docs/QUICKSTART.md) includes dependencies, separate processes, credentials and expected results.
- [x] No-key fixture path documented and HTTP smoke-tested separately from live media/model analysis.
- [x] `npm run verify` passes: 15 JavaScript, 23 gateway/pipeline Python and 74 agent tests, plus design adapter assertions. No live model or Platform database tests in this command.
- [x] [Live validation](dashboard/live/VALIDATION.md) records hosted State/Platform, local SDK inference, browser playback, answers, pause and generation isolation.
- [x] SQLite/journal persistence, external media dependencies and missing capabilities documented.
- [ ] Repeat setup on a fresh participant machine with its own accounts; existing-machine tests do not establish this.

Secrets belong in backend environments/private files. `.env`, agent work and local databases are ignored. This update adds no credentials or raw media; it is not a full audit of all prior commits.

## Two-minute film

**Prepared artifact:** `Firewatch-demo-HD.mp4`, Sharp S6, 120.000 seconds, 1920×1080, 30 fps export, English narration, 58 visible caption cues, original radio at 01:14.5–01:17.5.

**SHA-256:** `8f1f9df409484fb77c69c929a99ce7323607f77f92afe869bffe4d54158e7d8f`

[Script](dashboard/VIDEO_SCRIPT.md) · [Production sources](dashboard/video/s6/README.md) · [Final verification](dashboard/video/s6/verification.sharp.reference.json)

| Time | Visible evidence |
|---|---|
| 00:00–00:25 | Operator problem, sources and intended workflow |
| 00:25–01:30 | Actual UI, observations, cited model output, unknowns, question, transcript and original radio |
| 01:30–02:00 | Architecture, demonstration scope and proposed pilot |

- [x] 120-second file rendered/decoded; narration, source audio and visible captions checked.
- [x] Actual answers and source context preserved; edited replay excerpts identified. Export rate is not capture frequency or a latency measurement.
- [x] Synthetic building material distinguished from independent historical radio.
- [ ] Upload the Sharp final film and add its public URL above.
- [ ] Check the uploaded version while signed out, including readable text and audible radio.

## Final handoff

- [x] Valencia participant portal recorded.
- [ ] Confirm its actual deadline/local rules; no other city's deadline is substituted here.
- [ ] Add the public video URL.
- [ ] Publish a project post using the exact partner tags requested by Valencia organizers; add its URL.
- [ ] Review final materials and component-origin disclosure with the team.
- [ ] Submit through the portal and record confirmation.

### Suggested post copy — not published

We built Firewatch, an incident copilot embedded in a live sensor, camera and radio workspace. It updates a source-linked briefing, answers questions about the replay, and keeps missing information visible. Our training demo combines synthetic building observations with independent historical radio; it does not control emergency equipment. Built with OpenAI Agents SDK and model inference through OpenRouter.

Code: https://github.com/Anastassy/fire-incident-copilot  
Demo: [add the public Sharp S6 video URL]  
Partner tags: [use the Valencia organizer's exact instructions]
