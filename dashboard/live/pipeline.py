"""Server-only State -> Platform -> agent bridge; no replay controls or recognition."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_MAPPER_PATH = Path(__file__).resolve().parents[2] / 'platform/app/adapter/mapper.py'
_spec = importlib.util.spec_from_file_location('firewatch_platform_mapper', _MAPPER_PATH)
_mapper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mapper)

LIVE_QUESTION = ('Live assessment: Give at most 3 concise English claims about the current incident, each citing its event IDs. '
    'When both sources are provided, include a separate current sensor finding AND a separate radio or crew-report finding; '
    'do not omit either source to save space. Use the latest supplied readings with their units, quality and time. '
    'Identify what changed or needs confirmation only when the evidence supports it, and put critical unknowns in limitations. '
    'One reading cannot establish a stable condition or a trend; a trend needs multiple time-ordered readings from the same sensor. '
    'Treat radio statements as reports, not verified facts. Missing data, silence and absence of reports never establish safety. '
    'Camera metadata is not visual analysis; do not invent occupancy, evacuation status or safe routes.')


class PipelineError(RuntimeError):
    """A diagnostic safe to display without upstream bodies or credential URLs."""


class _Stopped(Exception):
    pass


def iter_sse(response):
    """Decode whole UTF-8 lines, including split transport chunks and CR/LF endings."""
    source = io.TextIOWrapper(response, encoding='utf-8-sig', newline=None)
    name, data = 'message', []
    for line in source:
        line = line.rstrip('\r\n')
        if not line:
            if data:
                yield name, json.loads('\n'.join(data))
            name, data = 'message', []
        elif not line.startswith(':'):
            field, separator, value = line.partition(':')
            if separator and value.startswith(' '):
                value = value[1:]
            if field == 'event':
                name = value
            elif field == 'data':
                data.append(value)


def map_observation(observation, device_meta):
    mapped = _mapper.map_observation_to_telemetry_in(observation, device_meta)
    if mapped is None:
        return None
    mapped['device']['external_id'] = 'sm-live-{}-g{}-{}'.format(
        observation['run_id'], observation['generation'], observation['device_id'])
    # Retain the immutable raw observation, including quality, interval and provenance.
    mapped.setdefault('payload', {})['state_observation'] = copy.deepcopy(observation)
    if observation['kind'] == 'connectivity' and observation['data'].get('connected') is None:
        mapped['availability'] = 'missing'
    return mapped


def agent_event(observation, reading, session_id):
    reading_id = reading.get('id')
    if not isinstance(reading_id, int) or isinstance(reading_id, bool) or reading_id <= 0:
        raise PipelineError('Platform did not return a valid reading ID.')
    data, kind = observation['data'], observation['kind']
    source = '{} / {}'.format(observation['device_id'], observation.get('room_id') or 'room unknown')
    if kind == 'radio_transcript':
        description = data.get('text') or '[Transcript text missing]'
        event_kind = 'radio'
    elif kind == 'measurement':
        value = 'missing' if data.get('value') is None else json.dumps(data['value'])
        description = '{}: {} = {} {}; quality={}. Raw measurement.'.format(
            source, data.get('metric') or 'metric unknown', value, data.get('unit') or '', data.get('quality') or 'unknown')
        event_kind = 'sensor'
    elif kind == 'camera':
        description = '{}: camera metadata, media_id={}, capture interval={}–{} ms. No image analysis has been performed.'.format(
            source, data.get('media_id'), data.get('capture_start_sim_time_ms'), data.get('capture_end_sim_time_ms'))
        event_kind = 'system'
    elif kind == 'people_count':
        description = '{}: reported people count={}, quality={}; missing count does not mean zero occupants.'.format(
            source, 'missing' if data.get('count') is None else data['count'], data.get('quality') or 'unknown')
        event_kind = 'sensor'
    else:
        description = '{}: raw {} report {}.'.format(source, kind, json.dumps(data, ensure_ascii=False, sort_keys=True))
        event_kind = 'system'
    result = {
        'session_id': session_id, 'generation': 0, 'event_id': observation['evidence_id'],
        'reading_id': reading_id, 'source_id': str(reading['device_id']),
        'time_ms': observation['received_sim_time_ms'], 'kind': event_kind,
        'description': description, 'payload': {'platform': copy.deepcopy(reading)},
    }
    if kind == 'radio_transcript':
        start, end = data.get('audio_start_sim_time_ms'), data.get('audio_end_sim_time_ms')
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end:
            result.update(media_start_ms=start, media_end_ms=end)
        result['payload']['media_id'] = data.get('media_id') or data.get('segment_id')
    return result


class LivePipeline:
    def __init__(self, settings, work_dir):
        self.settings = dict(settings)
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.work_dir, 0o700)
        self.enabled = all(settings.get(key) for key in ('state_url', 'read_token', 'platform_url', 'platform_key', 'agent_url'))
        self._lock = threading.RLock()
        self._worker = None
        self._statuses = {}

    def connect(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
            raise ValueError('Invalid run ID')
        with self._lock:
            if self._worker and self._worker.run_id == run_id and self._worker.thread.is_alive():
                return self.status(run_id)
            if self._worker:
                self._worker.stop.set()
            worker = _Worker(self, run_id)
            self._worker = worker
            worker.update(state='connecting' if self.enabled else 'error', error=None if self.enabled else 'Pipeline credentials are not configured.')
            if self.enabled:
                worker.thread.start()
            return self.status(run_id)

    def status(self, run_id=None, generation=None):
        with self._lock:
            if run_id is None and self._worker:
                run_id = self._worker.run_id
            if generation is None and self._worker and self._worker.run_id == run_id:
                return copy.deepcopy(self._worker._status)
            matches = [value for (rid, gen), value in self._statuses.items()
                       if rid == run_id and (generation is None or generation == gen)]
            if matches:
                return copy.deepcopy(matches[-1])
            return {'enabled': self.enabled, 'run_id': run_id, 'generation': generation, 'context': None,
                    'state': 'connecting', 'published': 0, 'imported': 0, 'skipped': 0, 'last_sim_time_ms': 0, 'error': None}

    def close(self):
        with self._lock:
            if self._worker:
                self._worker.stop.set()


class _Worker:
    def __init__(self, owner, run_id):
        self.owner, self.run_id = owner, run_id
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='state-agent-pipeline')
        self.analysis_thread = threading.Thread(target=self.analyze, daemon=True, name='state-agent-analysis')
        self.generation = None
        self.context = None
        self.meta, self.records, self.devices = {}, {}, {}
        self.sequence = 0
        self.clock = 0
        self.file = None
        self._status = {'enabled': owner.enabled, 'run_id': run_id, 'generation': None, 'context': None,
                        'state': 'connecting', 'published': 0, 'imported': 0, 'skipped': 0, 'last_sim_time_ms': 0, 'error': None,
                        'latest_analysis': None, 'analysis_lag_ms': None, 'analysis_error': None}

    def update(self, **values):
        with self.owner._lock:
            self._status.update(values)
            self.owner._statuses[(self.run_id, self.generation)] = copy.deepcopy(self._status)

    def check(self):
        if self.stop.is_set():
            raise _Stopped()

    def request(self, target, path, method='GET', body=None, stream=False, headers=None):
        self.check()
        settings = self.owner.settings
        outgoing = {'Content-Type': 'application/json', 'Accept': 'text/event-stream' if stream else 'application/json'}
        if target == 'state':
            outgoing['Authorization'] = 'Bearer ' + settings['read_token']
        elif target == 'platform':
            outgoing['X-API-Key'] = settings['platform_key']
        elif settings.get('agent_token'):
            outgoing['Cookie'] = 'fire_ui_session=' + settings['agent_token']
        outgoing.update(headers or {})
        request = urllib.request.Request(settings[target + '_url'].rstrip('/') + path, method=method,
            headers=outgoing, data=None if body is None else json.dumps(body, ensure_ascii=False).encode())
        try:
            response = urllib.request.urlopen(request, timeout=12)
            if stream:
                return response
            with response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise PipelineError('{} request failed (HTTP {}).'.format(target.capitalize(), error.code)) from None
        except (OSError, ValueError):
            raise PipelineError('{} request failed; reconnecting.'.format(target.capitalize())) from None

    def save(self):
        if self.file is None:
            return
        temporary = self.file.with_suffix('.tmp')
        content = {'run_id': self.run_id, 'generation': self.generation, 'records': self.records, 'clock': self.clock}
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(content, output, ensure_ascii=False)
        os.replace(temporary, self.file)
        self.update(published=len(self.records), imported=sum(bool(r.get('posted')) for r in self.records.values()),
                    skipped=sum(bool(r.get('skipped')) for r in self.records.values()), last_sim_time_ms=self.clock)

    def initialize(self, snapshot):
        run = snapshot['run']
        if run['run_id'] != self.run_id:
            raise PipelineError('State snapshot belongs to another run.')
        generation = run['generation']
        changed = generation != self.generation
        if changed:
            self.generation = generation
            self.context = None
            self.meta, self.records, self.devices, self.clock = {}, {}, {}, 0
            self.file = self.owner.work_dir / ('{}-g{}.json'.format(self.run_id, generation))
            if self.file.exists():
                saved = json.loads(self.file.read_text())
                if saved.get('run_id') != self.run_id or saved.get('generation') != generation:
                    raise PipelineError('Pipeline journal context does not match this run.')
                self.records = saved.get('records', {})
                self.clock = saved.get('clock', 0)
        self.update(generation=generation, context=None, state='connecting', error=None)
        if changed:
            self.update(latest_analysis=None, analysis_lag_ms=None, analysis_error=None,
                published=len(self.records), imported=sum(bool(r.get('posted')) for r in self.records.values()),
                skipped=sum(bool(r.get('skipped')) for r in self.records.values()), last_sim_time_ms=self.clock)
        _mapper.apply_snapshot(self.meta, snapshot)
        session_id = 'state-{}-g{}'.format(self.run_id, generation)
        session = self.request('agent', '/sessions/' + session_id, 'POST', {})
        if session.get('generation') != 0:
            raise PipelineError('Agent context was independently reset; restore its original generation before connecting.')
        # Repair an empty agent database using the preserved journal without resetting it.
        if session.get('time_ms', 0) < self.clock:
            for record in self.records.values():
                record.pop('posted', None)
            self.clock = session.get('time_ms', 0)
        self.context = {'demo_context_id': session_id, 'generation': 0, 'subject_id': 'all'}
        self.update(context=self.context)
        self.sequence = snapshot['as_of']['sequence']
        self.backfill(run['sim_time_ms'])
        self.tick(run['sim_time_ms'])
        self.update(state='live', error=None)

    def backfill(self, boundary):
        cursor = None
        seen = set()
        while True:
            query = {'generation': self.generation, 'limit': 500}
            if cursor:
                query['cursor'] = cursor
            page = self.request('state', '/runs/{}/observations?{}'.format(self.run_id, urllib.parse.urlencode(query)))
            if page.get('generation') != self.generation:
                raise PipelineError('State generation changed during history recovery.')
            observations = [o for o in page['items'] if o.get('run_id') == self.run_id and o.get('generation') == self.generation
                            and isinstance(o.get('received_sim_time_ms'), int) and o['received_sim_time_ms'] <= boundary]
            for start in range(0, len(observations), 100):
                self.process(observations[start:start + 100], recover=True)
            cursor = page.get('next_cursor')
            if not cursor:
                return
            if cursor in seen:
                raise PipelineError('State history repeated a pagination cursor.')
            seen.add(cursor)

    def load_devices(self):
        self.devices = {d['external_id']: str(d['id']) for d in self.request('platform', '/devices') if d.get('external_id')}

    def reconcile(self, entries, refresh_devices=False):
        if refresh_devices or not self.devices:
            self.load_devices()
        groups = {}
        for observation, mapped in entries:
            external = mapped['device']['external_id']
            groups.setdefault(external, []).append((observation, mapped))
        for external, group in groups.items():
            device_id = self.devices.get(external)
            if not device_id:
                continue
            timestamps = [mapped['ts'] for _, mapped in group]
            query = {'device_id': device_id, 'since': min(timestamps), 'until': max(timestamps), 'limit': 500}
            rows = self.request('platform', '/telemetry?' + urllib.parse.urlencode(query))
            by_id = {}
            for row in rows:
                if str(row.get('device_id')) != device_id:
                    continue
                evidence_id = row.get('external_event_id')
                if evidence_id:
                    by_id.setdefault(evidence_id, row)
            for observation, mapped in group:
                evidence_id = observation['evidence_id']
                if evidence_id in by_id:
                    row = by_id[evidence_id]
                    provenance = row.get('provenance', {}).get('state_machine', {})
                    if provenance.get('run_id') != self.run_id or provenance.get('generation') != self.generation:
                        raise PipelineError('Platform reading provenance belongs to another replay context.')
                    self.records.setdefault(evidence_id, {})['reading'] = row
            # Never infer absence outside a truncated response, which would duplicate rows.
            if len(rows) >= 500 and any('reading' not in self.records.get(o['evidence_id'], {}) for o, _ in group):
                raise PipelineError('Platform reconciliation window is full; narrow the history batch before retrying.')

    def process(self, observations, recover=False):
        entries = []
        seen = set()
        for observation in sorted(observations, key=lambda o: (o.get('received_sim_time_ms', -1), o.get('evidence_id', ''))):
            self.check()
            if observation.get('run_id') != self.run_id or observation.get('generation') != self.generation:
                continue
            if not isinstance(observation.get('received_sim_time_ms'), int) or observation['received_sim_time_ms'] < 0:
                raise PipelineError('Observation publication time is missing.')
            evidence_id = observation['evidence_id']
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            record = self.records.setdefault(evidence_id, {})
            if record.get('posted') or record.get('skipped'):
                continue
            mapped = map_observation(observation, self.meta)
            if mapped is None:
                record['skipped'] = True
            else:
                entries.append((observation, mapped))
        unresolved = [(o, m) for o, m in entries if 'reading' not in self.records[o['evidence_id']]]
        if unresolved:
            # Backfill may overlap a previous process, including a lost journal.
            # Fresh SSE entries cannot have been sent by this sole worker yet.
            # Only uncertain sends need readback; routine per-device GETs delay
            # the entire live stream by multiple network round trips.
            to_reconcile = [(o, m) for o, m in unresolved if recover
                or self.records[o['evidence_id']].get('pending_platform')
                or self.records[o['evidence_id']].get('platform_accepted')]
            if to_reconcile:
                self.reconcile(to_reconcile)
            missing = [(o, m) for o, m in unresolved if 'reading' not in self.records[o['evidence_id']]]
            if missing:
                if any(self.records[o['evidence_id']].get('platform_accepted') for o, _ in missing):
                    raise PipelineError('Platform accepted these readings; waiting for their IDs without ingesting them again.')
                # Persist uncertainty before a non-idempotent endpoint receives any bytes.
                for observation, _ in missing:
                    self.records[observation['evidence_id']]['pending_platform'] = True
                self.save()
                try:
                    result = self.request('platform', '/ingest/telemetry', 'POST', [mapped for _, mapped in missing])
                    if result.get('ingested') != len(missing):
                        raise PipelineError('Platform did not acknowledge the complete ingestion batch.')
                    for observation, _ in missing:
                        self.records[observation['evidence_id']]['platform_accepted'] = True
                    returned = result.get('readings')
                    if isinstance(returned, list) and len(returned) == len(missing):
                        expected = {o['evidence_id']: mapped for o, mapped in missing}
                        valid = {}
                        for row in returned:
                            evidence_id = row.get('external_event_id')
                            provenance = row.get('provenance', {}).get('state_machine', {})
                            reading_id = row.get('id')
                            if (evidence_id not in expected or evidence_id in valid
                                    or not isinstance(reading_id, int) or isinstance(reading_id, bool) or reading_id <= 0
                                    or not row.get('device_id') or provenance.get('run_id') != self.run_id
                                    or provenance.get('generation') != self.generation
                                    or provenance.get('evidence_id') != evidence_id):
                                break
                            external = expected[evidence_id]['device']['external_id']
                            raw_device = row.get('payload', {}).get('state_observation', {}).get('device_id')
                            expected_device = expected[evidence_id]['payload']['state_observation']['device_id']
                            if (raw_device != expected_device
                                    or (external in self.devices and str(row['device_id']) != self.devices[external])):
                                break
                            valid[evidence_id] = row
                        if len(valid) == len(missing):
                            for evidence_id, row in valid.items():
                                self.records[evidence_id]['reading'] = row
                                self.devices[expected[evidence_id]['device']['external_id']] = str(row['device_id'])
                    self.save()
                except PipelineError as error:
                    self.reconcile(missing, refresh_devices=True)
                    self.save()
                    if any('reading' not in self.records[o['evidence_id']] for o, _ in missing):
                        raise PipelineError('{} Reconciliation did not find every reading.'.format(error)) from None
                else:
                    waiting = [(o, m) for o, m in missing if 'reading' not in self.records[o['evidence_id']]]
                    if waiting:
                        self.reconcile(waiting, refresh_devices=True)
                    self.save()
                if any('reading' not in self.records[o['evidence_id']] for o, _ in missing):
                    raise PipelineError('Platform accepted readings but their IDs are not yet visible.')
        for observation, _ in entries:
            record = self.records[observation['evidence_id']]
            event = agent_event(observation, record['reading'], self.context['demo_context_id'])
            self.request('agent', '/events', 'POST', event)
            record['posted'] = True
            record.pop('pending_platform', None)
        self.save()
        if observations:
            times = [o['received_sim_time_ms'] for o in observations if o.get('run_id') == self.run_id and o.get('generation') == self.generation]
            if times:
                self.tick(max(times))

    def tick(self, time_ms):
        if time_ms <= self.clock:
            return
        self.request('agent', '/sessions/{}/0/clock'.format(self.context['demo_context_id']), 'POST', {'time_ms': time_ms})
        self.clock = time_ms
        self.save()

    def analyze(self):
        scope, journal, file = None, {}, None
        minimum_interval = max(3, float(self.owner.settings.get('analysis_interval_seconds', 5)))
        while not self.stop.is_set():
            try:
                with self.owner._lock:
                    status = copy.deepcopy(self._status)
                context = status.get('context')
                if context and context != scope:
                    pending = journal.get('pending')
                    if pending and pending.get('request_id'):
                        query = urllib.parse.urlencode(scope)
                        self.request('agent', '/agent/v1/questions/{}/cancel?{}'.format(pending['request_id'], query), 'POST', {})
                    scope = context
                    file = self.owner.work_dir / ('{}-g{}.analysis.json'.format(self.run_id, status['generation']))
                    journal = json.loads(file.read_text()) if file.exists() else {}
                if scope and status['state'] == 'live':
                    self.analysis_step(scope, status, journal, minimum_interval)
                    temporary = file.with_suffix('.tmp')
                    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(descriptor, 'w') as output:
                        json.dump(journal, output)
                    os.replace(temporary, file)
                    completed = journal.get('completed_as_of_ms')
                    with self.owner._lock:
                        if self._status.get('context') == scope:
                            self.update(latest_analysis=journal.get('latest'),
                                analysis_lag_ms=None if completed is None else max(0, status['last_sim_time_ms'] - completed), analysis_error=None)
            except _Stopped:
                return
            except Exception as error:
                self.update(analysis_error=str(error) if isinstance(error, PipelineError) else 'Automatic assessment is reconnecting.')
            self.stop.wait(1)

    def analysis_step(self, context, status, journal, minimum_interval):
        pending = journal.get('pending')
        if pending:
            if pending.get('request_id'):
                query = urllib.parse.urlencode(context)
                answer = self.request('agent', '/agent/v1/questions/{}?{}'.format(pending['request_id'], query))
            else:
                # Reusing the complete request body makes uncertain submission idempotent.
                answer = self.request('agent', '/agent/v1/questions', 'POST', pending['body'])
                pending['request_id'] = answer['request_id']
            journal['latest'] = {'request_id': answer['request_id'], 'status': answer['status'],
                'as_of_sim_time_ms': answer.get('coverage', {}).get('as_of_ms', pending['as_of_sim_time_ms']),
                'latency_ms': round((time.time() - pending['started_at']) * 1000)}
            if answer['status'] in ('queued', 'running'):
                return
            if answer['status'] in ('ready', 'insufficient_data'):
                journal['completed_as_of_ms'] = journal['latest']['as_of_sim_time_ms']
            journal['pending'] = None
        if (status['imported'] <= journal.get('requested_count', 0)
                or time.time() - journal.get('last_submitted_at', 0) < minimum_interval):
            return
        # User questions get their turn; automatic work cannot create a queue backlog.
        state = self.request('agent', '/agent/v1/state?' + urllib.parse.urlencode(context))
        if any(answer.get('status') in ('queued', 'running') for answer in state.get('answers', [])):
            return
        body = {'context': context, 'client_request_id': 'live-{}-g{}-{}'.format(
            self.run_id, status['generation'], status['imported']), 'question': LIVE_QUESTION, 'language': 'en'}
        if self.context != context:
            return
        journal['pending'] = {'body': body, 'request_id': None, 'as_of_sim_time_ms': status['last_sim_time_ms'], 'started_at': time.time()}
        journal['last_submitted_at'] = time.time()
        journal['requested_count'] = status['imported']
        answer = self.request('agent', '/agent/v1/questions', 'POST', body)
        journal['pending']['request_id'] = answer['request_id']
        journal['latest'] = {'request_id': answer['request_id'], 'status': answer['status'],
            'as_of_sim_time_ms': status['last_sim_time_ms'], 'latency_ms': 0}

    def run(self):
        self.analysis_thread.start()
        while not self.stop.is_set():
            try:
                snapshot = self.request('state', '/runs/' + self.run_id + '/snapshot')
                self.initialize(snapshot)
                cursor = snapshot['as_of']['cursor']
                pending = []
                with self.request('state', '/runs/' + self.run_id + '/stream', stream=True, headers={'Last-Event-ID': cursor}) as response:
                    for frame, body in iter_sse(response):
                        self.check()
                        if frame == 'snapshot':
                            self.initialize(body)
                        elif frame == 'stream_error':
                            raise PipelineError('State stream requested reconnection.')
                        elif frame == 'heartbeat':
                            if body.get('generation') != self.generation:
                                break
                            self.process(pending)
                            pending = []
                            self.tick(body['sim_time_ms'])
                        elif frame == 'event':
                            if body.get('generation') != self.generation or body.get('kind') == 'stream.reset':
                                break
                            sequence = body['sequence']
                            if sequence <= self.sequence:
                                continue
                            if sequence != self.sequence + 1:
                                raise PipelineError('State stream sequence gap; recovering published history.')
                            self.sequence = sequence
                            kind, data = body.get('kind'), body.get('data') or {}
                            if kind == 'device.updated':
                                _mapper.apply_device_state(self.meta, data)
                            elif kind == 'observation.created':
                                pending.append(data)
                            if kind == 'run.updated' or len(pending) >= 50:
                                self.process(pending)
                                pending = []
                            if kind == 'run.updated':
                                self.tick(data['sim_time_ms'])
                self.update(state='connecting')
            except _Stopped:
                return
            except Exception as error:
                self.update(state='error', error=str(error) if isinstance(error, PipelineError) else 'Pipeline recovery failed ({}).'.format(type(error).__name__))
                if self.stop.wait(2):
                    return
