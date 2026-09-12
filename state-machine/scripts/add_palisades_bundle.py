"""Append timed package audio/transcripts without changing existing scenario versions."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import shutil
import wave

from media_bundle import build_live, checksum

ROOT = Path(__file__).resolve().parents[1]

def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')

def build(base, package, output):
    base, package, output = [Path(p).resolve() for p in (base, package, output)]
    if output == base or output in base.parents or output == package or output in package.parents:
        raise ValueError('Output must be separate from original bundle and source package')
    manifest = json.loads((package / 'manifest.json').read_text())
    source = json.loads((package / 'provenance/source-manifest.json').read_text())
    # Check the entire supplied package before using any transcript or audio.
    for line in (package / 'SHA256SUMS').read_text().splitlines():
        digest, relative = line.split(maxsplit=1)
        path = (package / relative.lstrip('*')).resolve()
        if not path.is_relative_to(package) or checksum(path) != digest:
            raise ValueError('Source package checksum mismatch: ' + relative)
    if output.exists():
        raise ValueError('Use a new output directory; existing bundles are immutable')
    shutil.copytree(base, output)
    assets = output / 'assets'
    catalog = json.loads((output / 'catalog.json').read_text())
    media = json.loads((output / 'media.json').read_text())
    live = json.loads((output / 'live-streams.json').read_text())
    template = json.loads((base / 'escalation.json').read_text())
    additions = []
    for asset in manifest['assets']:
        variant = asset['id']
        scenario_id = 'palisades-full' if variant == 'full-10min' else 'palisades-focus'
        device_id = 'RADIO-PALISADES-FULL' if variant == 'full-10min' else 'RADIO-PALISADES-FOCUS'
        seconds = asset['duration_seconds']; duration = round(seconds * 1000)
        full_offset = round(asset['full_recording_offset_seconds'] * 1000)
        audio_path = package / asset['audio_wav']
        transcript_path = package / asset['transcript_json']
        transcript = json.loads(transcript_path.read_text())
        start_unix = source['source_publication']['audio_index_entry']['recording_start_unix'] + full_offset / 1000
        provenance = {'source_id': 'palisades-radio-demo', 'acquisition_id': manifest['source_audio_sha256'],
            'origin': 'derived', 'source_file': 'palisades-radio-demo/' + asset['audio_wav'],
            'source_url': manifest['source_url'], 'source_sha256': checksum(audio_path),
            'source_row': None, 'source_channel': '38651',
            'recorded_time': {'value': start_unix, 'unit': 'unix_s', 'reference': 'Receiver recording clock; sender acquisition time unknown'},
            'transformation': source.get('packaging_transformation', '') + ' Packaged mono 16 kHz PCM, lossless 2 second segmentation; silence preserved',
            'time_mapping': f'full_recording_ms = sim_ms + {full_offset}; recorded_unix_s = {start_unix} + sim_ms / 1000',
            'independence_group': manifest['source_audio_sha256'],
            'composition_note': 'Palisades full/focus are overlapping excerpts of ONE receiver recording. Other sensors and cameras are independent demo inputs; see their own provenance.',
            'attribution': manifest['attribution'] + '; ' + manifest['license']}
        stream = build_live(assets, device_id, audio_path, 'audio', seconds, provenance, source_clock=True)
        live[device_id] = stream
        scene = copy.deepcopy(template)
        # Retain two cameras and office measurements as explicitly independent demo data.
        radio_ids = {d['device_id'] for d in scene['devices'] if d['kind'] == 'radio_channel'}
        scene['devices'] = [d for d in scene['devices'] if d['device_id'] not in radio_ids]
        scene['devices'].append({'device_id': device_id, 'name': 'Palisades Command · ' + variant,
            'kind': 'radio_channel', 'building_id': scene['scenario']['building_id'], 'room_id': None,
            'floor_id': None, 'position_m': None, 'stale_after_ms': 5000, 'metric': None, 'unit': '',
            'transcript_delivery': 'prerecorded'})
        for room in scene['rooms']:
            room['device_ids'] = [d for d in room['device_ids'] if d not in radio_ids]
        events = [e for e in scene['events'] if e['device_id'] not in radio_ids and e['received_sim_time_ms'] <= duration]
        with wave.open(str(audio_path), 'rb') as audio:
            if audio.getparams()[:3] != (1, 2, 16000) or audio.getnframes() != seconds * 16000:
                raise ValueError('Unexpected source WAV format/duration')
            for i, start in enumerate(range(0, duration, 2000)):
                end = min(start + 2000, duration)
                mid = f'{scenario_id}-audio-{i:04d}'
                path = assets / (mid + '.wav')
                with wave.open(str(path), 'wb') as part:
                    part.setparams(audio.getparams()); part.writeframes(audio.readframes((end - start) * 16))
                p = copy.deepcopy(provenance)
                p['recorded_time']['value'] += start / 1000
                media[mid] = {'file': 'assets/' + path.name, 'kind': 'audio', 'status': 'ready',
                    'mime_type': 'audio/wav', 'codec': 'pcm_s16le', 'byte_length': path.stat().st_size,
                    'sha256': checksum(path), 'duration_ms': end - start, 'width': None, 'height': None,
                    'sample_rate_hz': 16000, 'channels': 1, 'supports_range': True, 'failure_code': None,
                    'media_id': mid, 'device_id': device_id, 'capture_start_sim_time_ms': start,
                    'capture_end_sim_time_ms': end, 'published_sim_time_ms': end, 'chunk_index': i, 'provenance': p}
                events.append({'kind': 'radio_audio', 'device_id': device_id, 'room_id': None,
                    'observed_sim_time_ms': end, 'received_sim_time_ms': end, 'provenance': p,
                    'data': {'channel_id': device_id, 'media_id': mid, 'chunk_index': i,
                        'audio_start_sim_time_ms': start, 'audio_end_sim_time_ms': end}})
        previous_end = 0
        for i, segment in enumerate(transcript['segments']):
            start, end = [round(segment[k] * 1000) for k in ['start', 'end']]
            if not 0 <= start <= end <= duration or end < previous_end:
                raise ValueError('Invalid transcript segment time')
            previous_end = end
            publish = next(f['end_ms'] for f in stream['fragments'] if f['end_ms'] >= end)
            p = copy.deepcopy(provenance)
            p.update(source_file='palisades-radio-demo/' + asset['transcript_json'],
                source_sha256=checksum(transcript_path), source_row=i + 1,
                transformation='Replay supplied machine transcript verbatim; no recognition on server; publish after matching audio fragment is available')
            p['recorded_time']['value'] += start / 1000
            words = [{'text': w['word'], 'start_sim_time_ms': round(w['start'] * 1000),
                'end_sim_time_ms': round(w['end'] * 1000), 'probability': w.get('probability')} for w in segment.get('words', [])]
            if any(not 0 <= w['start_sim_time_ms'] <= w['end_sim_time_ms'] <= duration for w in words):
                raise ValueError('Word timestamp outside recording')
            timing_notes = []
            if any(not start <= w['start_sim_time_ms'] <= w['end_sim_time_ms'] <= end for w in words):
                timing_notes.append('Source ASR word timestamps extend outside the segment; original timings preserved')
            publish = next(f['end_ms'] for f in stream['fragments'] if f['end_ms'] >= max([end] + [w['end_sim_time_ms'] for w in words]))
            events.append({'kind': 'radio_transcript', 'device_id': device_id, 'room_id': None,
                'observed_sim_time_ms': end, 'received_sim_time_ms': publish, 'provenance': p,
                'data': {'channel_id': device_id, 'stream_id': device_id,
                    'segment_id': f'{variant}-{i:04d}', 'source_segment_id': str(segment.get('source_segment_id', segment['id'])),
                    'language': transcript['language'], 'text': segment['text'],
                    'audio_start_sim_time_ms': start, 'audio_end_sim_time_ms': end,
                    'full_recording_offset_ms': full_offset, 'delivery': 'prerecorded',
                    'machine_generated': True, 'human_verified': False, 'model': source['asr']['model'],
                    'audio_source_file': provenance['source_file'], 'audio_source_sha256': provenance['source_sha256'],
                    'words': words, 'timing_notes': timing_notes}})
        events.sort(key=lambda e: (e['received_sim_time_ms'], e['kind'] == 'radio_transcript', e.get('source_event_id', ''), e['device_id']))
        for i, event in enumerate(events): event['source_event_id'] = f'{scenario_id}-{i:06d}'
        public = scene['scenario']
        public.pop('scenario_version')
        public.update(scenario_id=scenario_id, name='Palisades · ' + ('10 минут' if variant == 'full-10min' else '3:26 · ключевой отрезок'),
            description='Palisades audio and supplied timestamped transcript; independent sensor and camera demo inputs; see each source provenance.',
            duration_ms=duration, composition_note=provenance['composition_note'])
        scene['events'] = events
        hashes = {e['data']['media_id']: media[e['data']['media_id']]['sha256'] for e in events if e['kind'] in ['camera', 'radio_audio']}
        public['scenario_version'] = hashlib.sha256(json.dumps({'scenario': scene, 'media_sha256': hashes,
            'stream_sha256': {k: v['sha256'] for k, v in live.items() if k in {d['device_id'] for d in scene['devices']}}}, sort_keys=True).encode()).hexdigest()
        dump(output / (scenario_id + '.json'), scene); catalog.append(public)
        additions.append({'scenario_id': scenario_id, 'channel_id': device_id, 'duration_ms': duration,
            'transcript_segments': len(transcript['segments']), 'full_recording_offset_ms': full_offset})
        print(json.dumps(additions[-1]), flush=True)
    dump(output / 'catalog.json', catalog); dump(output / 'media.json', media); dump(output / 'live-streams.json', live)
    selection = json.loads((output / 'selection.json').read_text())
    selection.update(palisades=additions, prerecorded_transcripts=True, recognition=False,
        continuous_http_streams=len(live), asset_count=len(list(assets.iterdir())), asset_bytes=sum(p.stat().st_size for p in assets.iterdir()))
    dump(output / 'selection.json', selection)
    # Retain attribution/source metadata, but do not expose future transcript files via HTTP.
    shutil.copytree(package, output / 'palisades-source', ignore=shutil.ignore_patterns('audio'))
    for scenario in json.loads((base / 'catalog.json').read_text()):
        name = scenario['scenario_id'] + '.json'
        assert (base / name).read_bytes() == (output / name).read_bytes()
    return additions

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, default=ROOT / 'var/demo-bundle')
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'var/palisades-bundle')
    args = parser.parse_args(); build(args.base, args.package, args.output)
