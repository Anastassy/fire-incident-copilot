"""Authorized local production: ElevenLabs key is held in memory and never logged.

Usage: python3 generate_narration.py --output-dir PATH --beats B01 B02 ...
Only requested beats generate, completed takes remain untouched. Edit plan text
before retrying a beat. Never changes speed or trims spoken audio.
"""
import argparse
import os
import base64
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE = None


def duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                            capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def generate(beat, plan, api_key):
    voice_id, voice_type = (BASE / "voice/voice.lock").read_text().strip().split()
    if voice_id != plan["voice_id"] or voice_type != "premade":
        raise RuntimeError("Voice lock mismatch")
    attempts = sorted((BASE / "voice").glob(f"{beat['id']}-take*.mp3"))
    attempt = len(attempts) + 1
    if attempt > 3:
        return {"id": beat["id"], "status": "attempt_limit"}
    request_body = {
        "text": beat["text"], "model_id": plan["model_id"],
        "voice_settings": plan["voice_settings"], "seed": 94211 + attempt,
    }
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
        data=json.dumps(request_body).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"}, method="POST")
    began = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=100) as response:
            payload = json.load(response)
            request_id = response.headers.get("request-id")
            billed_characters = response.headers.get("character-cost")
    except urllib.error.HTTPError as error:
        return {"id": beat["id"], "status": "provider_error", "http_status": error.code}
    except Exception as error:
        return {"id": beat["id"], "status": "transport_error", "error_type": type(error).__name__}
    stem = BASE / "voice" / f"{beat['id']}-take{attempt:02d}"
    mp3 = stem.with_suffix(".mp3")
    mp3.write_bytes(base64.b64decode(payload.pop("audio_base64")))
    wav = stem.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp3),
                    "-ac", "1", "-ar", "24000", str(wav)], check=True)
    alignment = payload.get("normalized_alignment") or payload.get("alignment") or {}
    characters = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    spoken = [i for i, char in enumerate(characters) if char.strip()]
    speech_begin = starts[spoken[0]] if spoken else None
    speech_end = ends[spoken[-1]] if spoken else None
    full_duration = duration(wav)
    speech_duration = speech_end - speech_begin if spoken else None
    word_count = len(re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", beat["text"]))
    metrics = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af",
                              "silencedetect=noise=-35dB:d=0.8", "-f", "null", "-"],
                             capture_output=True, text=True)
    silences = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", metrics.stderr)]
    internal_pauses = [x for x in silences if speech_begin is not None and speech_begin + .05 < x < speech_end - .8]
    allowance = beat["speech_end"] - beat["speech_start"]
    metadata = dict(beat,
        attempt=attempt, provider="ElevenLabs", model_id=plan["model_id"],
        voice_id=voice_id, voice_type=voice_type, request_id=request_id,
        billed_characters=billed_characters, audio_path=wav.relative_to(BASE).as_posix(), original_audio_path=mp3.relative_to(BASE).as_posix(),
        alignment_path=stem.with_suffix(".alignment.json").relative_to(BASE).as_posix(),
        actual_duration=full_duration, aligned_speech_start=speech_begin,
        aligned_speech_end=speech_end, aligned_speech_duration=speech_duration,
        word_count=word_count, words_per_speech_second=round(word_count/speech_duration, 3) if speech_duration else None,
        internal_pauses_over_0_8s=len(internal_pauses),
        fits_window=full_duration <= allowance + .005,
        generation_seconds=round(time.monotonic()-began, 3),
        sha256=hashlib.sha256(wav.read_bytes()).hexdigest(),
        transformations=["MP3 decoded to 24 kHz mono PCM WAV; no trim or time stretch"])
    stem.with_suffix(".alignment.json").write_text(json.dumps(payload, indent=2))
    stem.with_suffix(".json").write_text(json.dumps(metadata, indent=2))
    return {key: metadata[key] for key in (
        "id", "attempt", "actual_duration", "aligned_speech_duration", "words_per_speech_second",
        "internal_pauses_over_0_8s", "fits_window")}


def main():
    global BASE
    parser = argparse.ArgumentParser(description="Generate explicitly selected paid stock-voice narration takes.")
    parser.add_argument("--output-dir", required=True, type=Path, help="External video asset directory; keep outside Git.")
    parser.add_argument("--plan", type=Path, default=SCRIPT_DIR / "narration-plan.json")
    parser.add_argument("--beats", nargs="+", required=True, help="Explicit beat IDs; no implicit paid batch.")
    args = parser.parse_args()
    BASE = args.output_dir.expanduser().resolve()
    plan = json.loads(args.plan.read_text())
    selected = set(args.beats)
    if len(selected) != len(args.beats):
        parser.error("Duplicate beat IDs")
    beats = [b for b in plan["beats"] if b["id"] in selected and b["text"]]
    if len(beats) != len(selected):
        parser.error("Unknown or silent beat selection")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        parser.error("ELEVENLABS_API_KEY is required; never pass a key on the command line")
    (BASE / "voice").mkdir(parents=True, exist_ok=True)
    (BASE / "production").mkdir(parents=True, exist_ok=True)
    lock = BASE / "voice/voice.lock"
    expected_lock = f"{plan['voice_id']} {plan['voice_type']}"
    if lock.exists() and lock.read_text().strip() != expected_lock:
        parser.error("Existing voice.lock differs from the plan")
    if not lock.exists():
        lock.write_text(expected_lock + "\n")
    # The finalized output is immutable; a new asset directory is needed for
    # another production version, instead of paying to replace accepted takes.
    if any((BASE / "voice/final" / (beat["id"] + ".wav")).exists() for beat in beats):
        parser.error("A selected beat is finalized; use a new output directory for a new production version")
    (BASE / "production/narration-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    errors = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(generate, beat, plan, api_key) for beat in beats]
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                errors = errors or result.get("status") in {"provider_error", "transport_error", "attempt_limit"}
                print(json.dumps(result), flush=True)
            except Exception as error:
                errors = True
                print(json.dumps({"status": "local_error", "error_type": type(error).__name__}), flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
