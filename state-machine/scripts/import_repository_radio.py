"""Import the repository's focus excerpt; never rewrite or duplicate tracked media."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from add_palisades_bundle import build as append_package
from media_bundle import checksum


def build(base, output, repository_package=None):
    source_dir = Path(repository_package or ROOT.parent / 'data/demo/palisades-radio-demo').resolve()
    mp3 = source_dir / 'audio/decision-focus.mp3'
    transcript_path = source_dir / 'transcripts/decision-focus.en.json'
    source_path = source_dir / 'provenance/source-manifest.json'
    transcript = json.loads(transcript_path.read_text())
    source = json.loads(source_path.read_text())
    duration = transcript['duration_seconds']
    offset = transcript['full_recording_offset_seconds']
    if duration != 206 or offset != 292 or not transcript['machine_generated']:
        raise ValueError('Unexpected focus package; inspect its time mapping before importing')
    if Path(output).exists():
        raise ValueError('Use a new output directory; existing bundles are immutable')
    with tempfile.TemporaryDirectory(prefix='state-radio-package-') as tmp:
        package = Path(tmp)
        for directory in ['audio', 'transcripts', 'provenance', 'licenses']:
            (package / directory).mkdir()
        wav = package / 'audio/decision-focus.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(mp3), '-ac', '1', '-ar', '16000',
                        '-c:a', 'pcm_s16le', str(wav)], check=True)
        shutil.copy2(transcript_path, package / 'transcripts/decision-focus.en.json')
        for license_path in (source_dir / 'licenses').iterdir():
            if license_path.is_file():
                shutil.copy2(license_path, package / 'licenses' / license_path.name)
        source['packaging_transformation'] = (
            'Decoded repository data/demo/palisades-radio-demo/audio/decision-focus.mp3 '
            f'(SHA256 {checksum(mp3)}) to mono 16 kHz PCM; this decoding is not the original master WAV. '
            'No denoising, silence removal, time stretching or new recognition.')
        source['repository_inputs'] = {
            'audio_sha256': checksum(mp3), 'transcript_sha256': checksum(transcript_path),
            'provenance_sha256': checksum(source_path)}
        (package / 'provenance/source-manifest.json').write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n')
        manifest = {
            'source_audio_sha256': source['source']['source_sha256'],
            'source_url': source['source_publication']['url'],
            'attribution': source['attribution'], 'license': source['license'],
            'assets': [{'id': 'decision-focus', 'duration_seconds': duration,
                        'full_recording_offset_seconds': offset,
                        'audio_wav': 'audio/decision-focus.wav',
                        'transcript_json': 'transcripts/decision-focus.en.json'}]}
        (package / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (package / 'SHA256SUMS').write_text(''.join(
            f'{checksum(path)}  {path.relative_to(package).as_posix()}\n'
            for path in sorted(package.rglob('*')) if path.is_file()))
        return append_package(base, package, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, default=ROOT / 'var/demo-bundle')
    parser.add_argument('--output', type=Path, default=ROOT / 'var/palisades-bundle')
    parser.add_argument('--package', type=Path, help='Repository package directory')
    args = parser.parse_args()
    build(args.base, args.output, args.package)
