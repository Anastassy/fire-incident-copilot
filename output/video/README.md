# Fire Incident Copilot — 25-second opening

This opening was drawn graphically in Python/Pillow. It is an illustrative prototype, not a recording of a running agent or an integrated application. No application, contracts, original radio files or MVP scope were modified. No paid services, APIs or external publishing were used.

From the repository root, rebuild and validate with one command:

```sh
video/opening/.venv/bin/python video/opening/build.py && video/opening/.venv/bin/python video/opening/verify.py
```

Requirements: Python 3.12 with Pillow, NumPy, imageio-ffmpeg 0.6.0; the supplied local venv uses the bundled workspace Pillow/NumPy. On a new Mac create a venv and install those packages. Fonts are system Avenir Next and Menlo. FFmpeg is supplied by imageio-ffmpeg; ffprobe is not required. The build retains five AIFF voice sources so ordinary rebuilding does not need speech service access. To regenerate narration after editing config.json use `build.py --synthesize` on macOS with installed Samantha voice. In a restricted agent sandbox the system speech service requires the normal permission mechanism; it otherwise produces an empty AIFF. The build checks actual nonempty voice durations.

Edit `config.json` for timing, narration, radio interval, colors, fonts, layout anchors and exact source quotations. Additional scene coordinates are editable in `build.py`. Five PNG scene plates, AIFF/WAV voice sources, the extracted radio segment and the audio master are retained here. The frame renderer generates exactly 750 RGB frames and streams them to FFmpeg; transitions are 0.3-second dissolves. The final image holds after narration, with no black ending. FFmpeg H.264/yuv420p + AAC, faststart, 1920×1080, 30 fps.

## Editorial decision

The execution request explicitly asked to add original radio, overriding the older prompt's narration-only restriction. One unanswered source question plays at 8.08–10.00 seconds, separately from narration: focus 02:08.500–02:10.420, “And what tack can I operate on?” The assignment and acknowledgement are neither heard nor displayed. The opening does not reveal the answer. This changes only this video's sound edit; it does not change application/MVP scope. “tack” is retained exactly from the machine transcript, not silently corrected.

Narration uses the prompt's permitted shorter wording in blocks 4–10 and 21–25. The first spoken question is already the large on-screen subtitle; all other narration and the original radio are burned in and included in SRT. The original radio transcript remains machine-generated and not human-verified; no speaker identity is asserted.

## Design

Palette: console #EFF3F6, ink #1D3040, evidence blue #185C85, pale panel #E7F2FA, metadata #536B7B, dividers #CEDBE4. Avenir Next for editorial questions and body; Menlo for archive time. The signature is the separation of the question from the original radio record, with the same unanswered exchange surviving the handoff. Large type carries the story; restrained dissolves explain the edit and do not simulate incoming data or agent latency. Radio Log is on the left and Copilot on the right as specifically requested in the video prompt; the later V2 app reference is not modified or presented as a working integration.

## Verification

`verify.py` decodes the entire video/audio, checks 750 frames, format and duration, measures decoded AAC loudness/true peak, checks moov before mdat, extracts six final-MP4 frames at 0.5/5/12/17/22/24.5 seconds, creates 960×540 copies and storyboard.jpg, and extracts frame 749. See output/video/verification.json and decode-check.txt. Listening/transcription by a human has not been claimed.
