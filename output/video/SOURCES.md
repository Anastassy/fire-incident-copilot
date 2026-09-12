# Sources and transformations

## Recorded radio and transcript

- Publication: [Broadcastify — January 2025 Los Angeles fires](https://www.broadcastify.com/events/2025-01-lafire/).
- Attribution: **Audio Provided by Broadcastify**.
- License recorded in local provenance: [Creative Commons Attribution 3.0 United States](https://creativecommons.org/licenses/by/3.0/us/).
- Feed: Los Angeles County Fire V-1 / Palisades Fire Command, 7 January 2025.
- Local provenance: `data/demo/palisades-radio-demo/provenance/source-manifest.json`.
- Original archive member: `LA_County_Fire_v1_2025-01-07/38651-1736281253.mp3`; SHA256 `4581c204cb97ccbf830f7f58c17c23f92496554ec347e5c4721e5328e21511f6`.
- Local audio: `data/demo/palisades-radio-demo/audio/decision-focus.wav`, mono 16 kHz PCM, a continuous 206-second crop from full-recording 292–498 seconds. No edits to the original file.
- Included audio: focus 128.500–130.420 seconds, equivalent to original recording 420.500–422.420 seconds. Placed at video 8.080–10.000 seconds. Resampled to 48 kHz, level adjusted, 20 ms edge fades, mixed with local narrator, programme loudness normalization, AAC encoding. No synthetic radio or added noise. The request explicitly asked for original radio, superseding the narration-only sentence in the supplied prompt. No assignment or acknowledging reply is included.
- On-screen text: exact three consecutive transcript entries at focus 120.840–123.480, 123.960–125.500, 128.600–130.420. Source `transcripts/decision-focus.en.txt`. Machine transcript · not human-verified. “tack” is the uncorrected source ASR wording. Speaker identity is unknown. Published history ends at 130.420; no later message is shown.
- The three displayed rows are explicitly labeled as an editorial excerpt. This is a video composition, not a claim that the application has hidden other records.
- Recording time is the archive receiver's clock; video timing is a separate editorial clock. The first question is an editorial hook, not a historical quotation or a claim of operator error.

## Generated materials

- English narrator: installed macOS Samantha voice, generated locally using `/usr/bin/say`; five AIFF source blocks, no paid voice service. Synthetic narrator is not a radio participant.
- Graphic design: locally drawn with Python/Pillow, system Avenir Next and Menlo fonts. No external photographs, stock assets, music, logos or generated incident imagery.
- Project references: PROJECT_CONTEXT.md, CREATE_DEMO_VIDEO_CODEX_PROMPT.md, PALISADES_INTERFACE_SPEC.md, DEMO_OPENING_25S.md, team-handoff/mvp-scope/README.md, team-handoff/mvp-scope/04_VIDEO_TIMING.md and docs/design/palisades-console.html. No claim of historical console reconstruction or working agent integration.
- FFmpeg 7.1 via imageio-ffmpeg 0.6.0 performs local encoding. Sources remain in video/opening; all outputs in output/video. No external publication.
