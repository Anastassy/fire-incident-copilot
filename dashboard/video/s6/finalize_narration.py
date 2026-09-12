"""Select final measured takes and place them in the S6 windows without retiming."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description="Validate and assemble narration without retiming speech.")
parser.add_argument("--output-dir", required=True, type=Path, help="External asset directory created by generate_narration.py")
args = parser.parse_args()
BASE = args.output_dir.expanduser().resolve()
plan = json.loads((BASE / "production/narration-plan.json").read_text())


def asset_path(value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError("Expected a relative asset path")
    resolved = (BASE / path).resolve()
    resolved.relative_to(BASE)
    return resolved


def portable(path):
    return path.relative_to(BASE).as_posix()

final = BASE / "voice/final"
final.mkdir(exist_ok=True)
clips = []
for beat in plan["beats"]:
    if not beat["text"]:
        continue
    attempts = sorted(p for p in (BASE / "voice").glob(beat["id"]+"-take*.json") if ".alignment." not in p.name)
    metadata = json.loads(attempts[-1].read_text())
    assert metadata["text"] == beat["text"], (beat["id"], "Plan does not match final take")
    assert metadata["internal_pauses_over_0_8s"] == 0
    assert metadata["words_per_speech_second"] <= 2.9
    source = asset_path(metadata["audio_path"])
    output = final / (beat["id"] + ".wav")
    allowance = beat["speech_end"] - beat["speech_start"]
    tail_trim = 0
    if metadata["actual_duration"] <= allowance:
        shutil.copyfile(source, output)
    else:
        # Trim only verified terminal silence. Keep >75ms beyond both the
        # low-amplitude silence detector boundary and provider-aligned speech.
        result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(source), "-af",
                                 "silencedetect=noise=-40dB:d=0.05", "-f", "null", "-"],
                                capture_output=True, text=True, check=True)
        silence_starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
        trim_at = allowance - .01
        assert silence_starts and trim_at >= silence_starts[-1] + .075, (beat["id"], "Not terminal silence")
        assert trim_at >= metadata["aligned_speech_end"] + .075, (beat["id"], "Too close to aligned speech")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
                        "-af", f"atrim=end={trim_at:.6f}", "-c:a", "pcm_s16le", "-y", str(output)], check=True)
        tail_trim = metadata["actual_duration"] - trim_at
    measured = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=noprint_wrappers=1:nokey=1", str(output)],
                              capture_output=True, text=True, check=True)
    duration = float(measured.stdout.strip())
    assert duration <= allowance
    clips.append({
        "id": beat["id"], "path": portable(output), "local_filepath": portable(output),
        "start_s": beat["speech_start"], "duration_s": duration, "actual_duration": duration,
        "end_s": beat["speech_start"] + duration,
        "beat_start_s": beat["start"], "beat_end_s": beat["end"],
        "speech_window_end_s": beat["speech_end"],
        "text": beat["text"], "spoken_text": beat["text"], "role": beat["role"],
        "source_take": portable(source), "take_metadata_path": portable(attempts[-1]),
        "provider_alignment_path": metadata["alignment_path"],
        "aligned_speech_start_s": metadata["aligned_speech_start"],
        "aligned_speech_end_s": metadata["aligned_speech_end"],
        "words_per_speech_second": metadata["words_per_speech_second"],
        "trailing_silence_removed_s": round(tail_trim, 6), "time_stretched": False,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    })
assert len(clips) == 23
assert all(a["end_s"] <= b["start_s"] for a, b in zip(clips, clips[1:]))
assert all(c["end_s"] <= 74 or c["start_s"] >= 78 for c in clips)
mix = BASE / "voice/narration-120s.wav"
args = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
filters = []
for i, clip in enumerate(clips):
    args.extend(["-i", str(asset_path(clip["path"]))])
    filters.append(f"[{i}:a]adelay={round(clip['start_s']*1000)}:all=1[a{i}]")
filters.append("".join(f"[a{i}]" for i in range(len(clips))) +
               f"amix=inputs={len(clips)}:duration=longest:normalize=0,apad=whole_dur=120,atrim=end=120[out]")
args.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "24000", "-ac", "1",
             "-c:a", "pcm_s16le", "-y", str(mix)])
subprocess.run(args, check=True)
timeline = {
    "version": plan["version"], "duration_s": 120, "provider": plan["provider"],
    "model_id": plan["model_id"], "voice_id": plan["voice_id"], "voice_name": plan["voice_name"],
    "voice_type": plan["voice_type"], "voice_settings": plan["voice_settings"],
    "audio_sample_rate_hz": 24000, "channels": 1, "narration_stem_path": portable(mix),
    "notes": plan["notes"], "path_base": "Directory passed to --output-dir", "clips": clips,
    "silent_beats": [{"id":"D11", "start_s":74, "end_s":78,
                       "reserved_radio_start_s":74.5, "reserved_radio_end_s":77.5}],
    "validation": {"all_23_clips_measured":True, "all_within_s6_speech_windows":True,
                   "maximum_words_per_speech_second":max(c["words_per_speech_second"] for c in clips),
                   "internal_pauses_over_0_8s":0, "spoken_audio_cut":False, "time_stretch":False,
                   "d11_narration_silence":True, "final_whisper_caption_review":"handled by caption agent"},
    "api_documentation": [
        "https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps",
        "https://elevenlabs.io/docs/api-reference/voices/search"
    ]
}
(BASE / "production/narration-timeline.json").write_text(json.dumps(timeline, indent=2))
print(json.dumps({"clips":len(clips), "total_spoken_file_seconds":round(sum(c["duration_s"] for c in clips),3),
                  "voice":plan["voice_name"], "timeline":"production/narration-timeline.json",
                  "narration_stem":portable(mix), "trimmed_only_terminal_silence":[c["id"] for c in clips if c["trailing_silence_removed_s"]]}))
