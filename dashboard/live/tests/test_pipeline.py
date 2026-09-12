"""Pipeline boundaries without live APIs, paid models, or replay mutations."""
import copy
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location('pipeline', Path(__file__).parents[1] / 'pipeline.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def observation(evidence='e-1', generation=0, kind='measurement', received=6000):
    return {'run_id': 'run-a', 'generation': generation, 'evidence_id': evidence,
            'device_id': 'TEMP-1', 'room_id': 'ROOM-1', 'kind': kind,
            'observed_sim_time_ms': 2000, 'received_sim_time_ms': received,
            'received_at': '2026-09-12T10:00:00.000Z',
            'provenance': {'origin': 'synthetic', 'source_id': 'recording-1'},
            'data': {'metric': 'temperature', 'value': None, 'unit': 'degC', 'quality': 'missing'}}


def snapshot(generation=0, sim=10000):
    return {'run': {'run_id': 'run-a', 'generation': generation, 'sim_time_ms': sim},
            'devices': [{'device_id': 'TEMP-1', 'name': 'Temperature', 'kind': 'temperature_sensor'}],
            'as_of': {'sequence': 50, 'cursor': 'cursor-50'}}


class FakeServices:
    def __init__(self):
        self.devices, self.readings, self.events, self.sessions, self.calls = {}, [], {}, {}, []
        self.pages = [{'items': [], 'generation': 0, 'next_cursor': None}]
        self.uncertain_ingest = False
        self.questions = []
        self.answer_status = 'running'
        self.return_readings = False
    def request(self, target, path, method='GET', body=None, **kwargs):
        self.calls.append((target, path, method, copy.deepcopy(body)))
        route = urlsplit(path).path
        if target == 'state':
            query = parse_qs(urlsplit(path).query)
            return self.pages[int(query.get('cursor', ['0'])[0])]
        if target == 'platform' and route == '/devices':
            return [{'external_id': key, 'id': value} for key, value in self.devices.items()]
        if target == 'platform' and route == '/telemetry':
            device_id = parse_qs(urlsplit(path).query)['device_id'][0]
            return [copy.deepcopy(row) for row in self.readings if row['device_id'] == device_id]
        if target == 'platform' and route == '/ingest/telemetry':
            for item in body:
                row = copy.deepcopy(item)
                external = row.pop('device')['external_id']
                device_id = self.devices.setdefault(external, 'device-{}'.format(len(self.devices) + 1))
                row.update(id=len(self.readings) + 1001, device_id=device_id)
                self.readings.append(row)
            if self.uncertain_ingest:
                self.uncertain_ingest = False
                raise pipeline.PipelineError('Platform outcome uncertain.')
            result = {'ingested': len(body)}
            if self.return_readings:
                result['readings'] = copy.deepcopy(self.readings[-len(body):])
            return result
        if target == 'agent' and route.startswith('/sessions/'):
            parts = route.split('/')
            session = self.sessions.setdefault(parts[2], {'generation': 0, 'time_ms': 0})
            if route.endswith('/clock'):
                session['time_ms'] = body['time_ms']
            return session.copy()
        if target == 'agent' and route == '/events':
            key = (body['session_id'], body['generation'], body['event_id'])
            inserted = key not in self.events
            if key in self.events:
                assert self.events[key] == body
            self.events[key] = copy.deepcopy(body)
            return {'inserted': inserted}
        if target == 'agent' and route == '/agent/v1/state':
            return {'answers': []}
        if target == 'agent' and route == '/agent/v1/questions':
            self.questions.append(copy.deepcopy(body))
            return {'request_id': 'q-1', 'status': 'queued'}
        if target == 'agent' and route.startswith('/agent/v1/questions/'):
            return {'request_id': 'q-1', 'status': self.answer_status}
        raise AssertionError((target, path, method))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.owner = pipeline.LivePipeline(dict(state_url='https://state.test', read_token='test-read',
            platform_url='https://platform.test', platform_key='test-platform', agent_url='http://agent.test'), self.temporary.name)
        self.services = FakeServices()
        self.worker = self.worker_for()
    def tearDown(self):
        self.owner.close()
        self.temporary.cleanup()
    def worker_for(self):
        worker = pipeline._Worker(self.owner, 'run-a')
        worker.request = self.services.request
        return worker
    def initialize(self, values=None, generation=0, sim=10000):
        self.services.pages = [{'items': values or [], 'generation': generation, 'next_cursor': None}]
        self.worker.initialize(snapshot(generation, sim))

    def test_missing_is_not_zero_or_disconnected(self):
        missing = observation()
        mapped = pipeline.map_observation(missing, {})
        self.assertIsNone(mapped['value'])
        self.assertEqual(mapped['quality'], 'missing')
        missing['data']['value'] = 0
        self.assertEqual(pipeline.map_observation(missing, {})['value'], 0)
        missing['kind'] = 'connectivity'
        missing['data'] = {'connected': None}
        mapped = pipeline.map_observation(missing, {})
        self.assertIsNone(mapped['value'])
        self.assertEqual(mapped['availability'], 'missing')

    def test_publication_time_real_reading_id_and_provenance(self):
        self.initialize([observation()])
        event = next(iter(self.services.events.values()))
        self.assertEqual(event['time_ms'], 6000)
        self.assertEqual(event['reading_id'], 1001)
        self.assertEqual(event['source_id'], self.services.readings[0]['device_id'])
        self.assertEqual(event['payload']['platform'], self.services.readings[0])
        raw = event['payload']['platform']['payload']['state_observation']
        self.assertEqual(raw['observed_sim_time_ms'], 2000)
        self.assertEqual(raw['received_sim_time_ms'], 6000)
        self.assertEqual(self.services.readings[0]['ts'], observation()['received_at'])
        self.assertIn('missing', event['description'])

    def test_pagination_repeated_events_and_future_publication(self):
        self.services.pages = [
            {'items': [observation(), observation()], 'generation': 0, 'next_cursor': '1'},
            {'items': [observation(), observation('future', received=11000)], 'generation': 0, 'next_cursor': None}]
        self.worker.initialize(snapshot(sim=10000))
        self.assertEqual(len(self.services.readings), 1)
        self.assertEqual(len(self.services.events), 1)
        self.assertEqual(self.owner.status('run-a', 0)['imported'], 1)
        self.assertEqual(self.owner.status('run-a', 0)['last_sim_time_ms'], 10000)

    def test_restart_reconciles_existing_platform_without_reinserting(self):
        self.initialize([observation()])
        self.worker = self.worker_for()
        self.worker.initialize(snapshot())
        self.assertEqual(len(self.services.readings), 1)
        self.assertEqual(len(self.services.events), 1)
        self.assertEqual(len([c for c in self.services.calls if c[:3] == ('platform', '/ingest/telemetry', 'POST')]), 1)

    def test_no_journal_still_reconciles_existing_platform_rows(self):
        self.initialize([observation()])
        self.worker.file.unlink()
        self.worker = self.worker_for()
        self.worker.initialize(snapshot())
        self.assertEqual(len(self.services.readings), 1)
        self.assertEqual(len(self.services.events), 1)

    def test_uncertain_success_is_reconciled_before_any_retry(self):
        self.services.uncertain_ingest = True
        self.initialize([observation()])
        self.assertEqual(len(self.services.readings), 1)
        self.assertEqual(len(self.services.events), 1)
        self.assertEqual(self.owner.status('run-a', 0)['state'], 'live')

    def test_returned_real_reading_ids_avoid_post_ingest_queries(self):
        self.services.return_readings = True
        self.initialize([observation()])
        self.assertEqual(next(iter(self.services.events.values()))['reading_id'], 1001)
        writes = [index for index, call in enumerate(self.services.calls) if call[:3] == ('platform', '/ingest/telemetry', 'POST')]
        self.assertEqual(len(writes), 1)
        after = self.services.calls[writes[0] + 1:]
        self.assertFalse(any(target == 'platform' for target, _, _, _ in after))

    def test_fresh_live_batch_needs_only_one_platform_request(self):
        self.services.return_readings = True
        self.initialize()
        self.services.calls.clear()
        self.worker.process([observation('live-a', received=11000), observation('live-b', received=12000)])
        calls = [call for call in self.services.calls if call[0] == 'platform']
        self.assertEqual([(c[1], c[2]) for c in calls], [('/ingest/telemetry', 'POST')])
        self.assertEqual(len(self.services.events), 2)
        self.worker.process([observation('live-a', received=11000)])
        self.assertEqual(len(self.services.readings), 2)

    def test_acknowledged_readings_are_not_reposted_when_queries_lag(self):
        original = self.worker.request
        def delayed(target, path, method='GET', body=None, **kwargs):
            if target == 'platform' and path.startswith('/telemetry?'):
                return []
            return original(target, path, method, body, **kwargs)
        self.worker.request = delayed
        with self.assertRaises(pipeline.PipelineError):
            self.initialize([observation()])
        with self.assertRaises(pipeline.PipelineError):
            self.worker.process([observation()])
        self.assertEqual(len(self.services.readings), 1)
        self.assertFalse(self.services.events)

    def test_unmapped_audio_metadata_is_explicitly_counted(self):
        self.initialize([observation(kind='radio_audio')])
        status = self.owner.status('run-a', 0)
        self.assertEqual((status['published'], status['imported'], status['skipped']), (1, 0, 1))
        self.assertFalse(self.services.readings)

    def test_new_generation_has_new_devices_session_and_no_reset(self):
        self.initialize([observation()])
        old = copy.deepcopy(self.services.events)
        self.initialize([observation(generation=1)], generation=1)
        self.assertEqual(len(self.services.devices), 2)
        self.assertIn('sm-live-run-a-g0-TEMP-1', self.services.devices)
        self.assertIn('sm-live-run-a-g1-TEMP-1', self.services.devices)
        self.assertIn('state-run-a-g0', self.services.sessions)
        self.assertIn('state-run-a-g1', self.services.sessions)
        for key, value in old.items():
            self.assertEqual(self.services.events[key], value)
        self.assertFalse(any('reset' in path or 'commands' in path for _, path, _, _ in self.services.calls))
        self.assertEqual(self.owner.status('run-a', 1)['context'], {'demo_context_id': 'state-run-a-g1', 'generation': 0, 'subject_id': 'all'})

    def test_audio_offsets_and_original_transcript_are_preserved(self):
        value = observation(kind='radio_transcript')
        value['data'] = {'text': 'Copy V-Fire 25, thank you.', 'audio_start_sim_time_ms': 2000,
                         'audio_end_sim_time_ms': 5000, 'segment_id': 'segment-a', 'machine_generated': True, 'human_verified': False}
        self.initialize([value])
        event = next(iter(self.services.events.values()))
        self.assertEqual(event['description'], value['data']['text'])
        self.assertEqual(event['media_start_ms'], 2000)
        self.assertEqual(event['media_end_ms'], 5000)
        self.assertEqual(event['time_ms'], 6000)
        self.assertEqual(event['payload']['platform']['payload']['audio_start_sim_time_ms'], 2000)

    def test_fragmented_radio_context_survives_paginated_sensor_backfill(self):
        group = observation('group', kind='radio_transcript', received=81856)
        group['device_id'] = 'RADIO-1'
        group['data'] = {'text': "I'd like to make this Coastline Structured Defense Group,",
                         'audio_start_sim_time_ms': 79000, 'audio_end_sim_time_ms': 81000}
        request = observation('request', kind='radio_transcript', received=83904)
        request['device_id'] = 'RADIO-1'
        request['data'] = {'text': 'and if you could let me know what tack I can operate on.',
                           'audio_start_sim_time_ms': 81000, 'audio_end_sim_time_ms': 83000}
        self.services.pages = [
            {'items': [group, observation('sensor', received=82000)], 'generation': 0, 'next_cursor': '1'},
            {'items': [request], 'generation': 0, 'next_cursor': None}]
        self.worker.initialize(snapshot(sim=84000))
        radio = [event for event in self.services.events.values() if event['kind'] == 'radio']
        self.assertEqual([event['description'] for event in radio], [group['data']['text'], request['data']['text']])
        self.assertEqual(radio[0]['source_id'], radio[1]['source_id'])
        self.assertEqual([event['time_ms'] for event in radio], [81856, 83904])
        self.assertNotEqual(radio[0]['reading_id'], radio[1]['reading_id'])

    def test_live_assessment_coalesces_while_previous_is_running(self):
        self.initialize([observation()])
        status = self.owner.status('run-a', 0)
        journal = {}
        self.worker.analysis_step(self.worker.context, status, journal, 0)
        self.assertEqual(len(self.services.questions), 1)
        self.assertTrue(self.services.questions[0]['question'].startswith('Live assessment:'))
        status['imported'] = 25
        self.worker.analysis_step(self.worker.context, status, journal, 0)
        self.assertEqual(len(self.services.questions), 1)
        self.services.answer_status = 'ready'
        self.worker.analysis_step(self.worker.context, status, journal, 0)
        self.assertEqual(len(self.services.questions), 2)
        self.assertTrue(self.services.questions[-1]['client_request_id'].endswith('-25'))
        self.assertEqual(journal['completed_as_of_ms'], 10000)

    def test_context_is_not_exposed_before_session_creation(self):
        def fail(*args, **kwargs):
            raise pipeline.PipelineError('Agent unavailable.')
        self.worker.request = fail
        with self.assertRaises(pipeline.PipelineError):
            self.worker.initialize(snapshot())
        self.assertIsNone(self.owner.status('run-a', 0)['context'])

    def test_sse_unicode_multiline_and_crlf(self):
        data = ': keep alive\r\nevent: event\r\ndata: {"text":\r\ndata: "дым"}\r\n\r\n'.encode('utf-8')
        class Fragmented(io.BytesIO):
            def read1(self, size=-1):
                return super().read1(min(size, 1))
        self.assertEqual(list(pipeline.iter_sse(Fragmented(data))), [('event', {'text': 'дым'})])


if __name__ == '__main__':
    unittest.main()
