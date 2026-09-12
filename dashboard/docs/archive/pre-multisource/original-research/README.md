# Fire Incident Copilot

Helping fire incident operators trace answers back to the evidence.

Built for the Valencia hackathon on September 12, 2026.

## The problem

Radio traffic arrives as a sequence of messages. An operator supporting incident command needs to connect those messages: what was requested, what was assigned, and whether an acknowledgement followed. Finding an answer also means finding the original evidence and understanding what it does—and does not—establish.

## Our approach

Fire Incident Copilot combines an operator dashboard with an assistant that checks incoming information and answers questions with links to the source.

- **Follow the exchange:** a background check updates the same card as new evidence becomes available.
- **Ask a question:** get a concise answer with evidence beside each claim.
- **Verify the answer:** open the original radio interval and inspect its timestamp and machine transcript.

The Data Platform is the source of truth. Agent interpretations remain separate from source observations. Operators retain access to the complete available log through explicit filters. The assistant provides information support; it does not issue tactical instructions or transmit radio messages.

## Demo: Palisades radio replay

The MVP follows a 206-second excerpt of historical Palisades radio from January 7, 2025. The operator investigates a channel assignment to V-Fire 25:

1. A channel request is present in the available history.
2. Replay introduces the assignment and a separate acknowledging reply.
3. The operator asks, “Was the channel assignment acknowledged?”
4. Each part of the answer links to its original audio interval.
5. A follow-up asks whether the whole group switched channels. The recording alone does not establish that.

This is recorded replay with a prerecorded machine transcript, not live speech recognition. The operator interaction is a demonstration scenario. Transcript accuracy and the selected intervals still require human verification.

## Try the prototype

Clone this repository and open [docs/design/palisades-console.html](docs/design/palisades-console.html) in a desktop browser. Keep the repository's folder structure intact so the local audio links resolve. The interface is in English.

Alternatively, serve the repository with any static HTTP server. For example, if Python 3 is installed:

```sh
python3 -m http.server 8080 --bind 127.0.0.1
```

Then open [the local prototype](http://localhost:8080/docs/design/palisades-console.html). No API keys or build step are needed for this mockup.

## Project status

The repository currently contains an interactive HTML mockup with prepared states, local radio recordings and machine transcripts, the MVP specification, and service contracts. The dashboard is not yet connected to the Data Platform or a working agent. The mockup demonstrates the intended interaction, not measured model performance or a completed integration.

The next implementation milestone is the complete replay → platform → background check/question → source-audio flow, including a control replay with the acknowledgement omitted.

## Learn more

- [MVP scope and acceptance criteria](team-handoff/mvp-scope/README.md)
- [Interface specification](PALISADES_INTERFACE_SPEC.md)
- [Service contracts](docs/contracts/README.md)
- [Data, provenance and transcripts](data/demo/palisades-radio-demo/README.md)
- [Contributing and local development](CONTRIBUTING.md)

## Data attribution

**Audio Provided by Broadcastify.** The source recording is from [Broadcastify's Los Angeles fires archive](https://www.broadcastify.com/events/2025-01-lafire/). The included data package records the [CC BY 3.0 US license](https://creativecommons.org/licenses/by/3.0/us/), source metadata and transformations, including excerpting, transcoding and machine transcription. See the [data README](data/demo/palisades-radio-demo/README.md) for details.

The audio license does not apply automatically to the project's own code. A code license has not yet been selected.

## Video script

[Current timed script — S4](VIDEO_SCRIPT.md): only 00:00–00:25 is drafted. [Video versions and render status](VIDEO_STATUS.md). Previous MP4s do not yet reflect this script.
