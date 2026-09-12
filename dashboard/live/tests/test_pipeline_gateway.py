"""Pipeline endpoint guards use a stub worker and never contact real services."""
import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('pipeline_gateway', Path(__file__).parents[1] / 'server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
RUN = '2b6698af-e18c-4a6b-952a-96e2fe43d9f2'


class PipelineStub:
    def __init__(self):
        self.calls = []

    def connect(self, run_id):
        self.calls.append(('connect', run_id))
        return {'enabled': True, 'run_id': run_id, 'state': 'connecting'}

    def status(self, run_id, generation):
        self.calls.append(('status', run_id, generation))
        return {'enabled': True, 'run_id': run_id, 'generation': generation, 'state': 'live',
                'context': {'demo_context_id': f'state-{run_id}-g{generation}', 'generation': 0, 'subject_id': 'all'}}

    def close(self):
        pass


class PipelineGatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = module.Gateway(('127.0.0.1', 0), {
            'state_url': 'http://127.0.0.1:1', 'agent_url': 'http://127.0.0.1:1',
            'platform_url': 'http://127.0.0.1:1', 'read_token': 'test-only-private-state',
            'platform_key': 'test-only-private-platform', 'agent_token': 'test-only-private-agent',
            'control_token': 'test-only-private-control', 'demo_agent': False,
            'agent_context': {}, 'scenario': 'test',
        })
        cls.pipeline = PipelineStub()
        cls.gateway.pipeline = cls.pipeline
        cls.health = patch.object(module.Handler, 'request_json', return_value={
            'engine': 'SDKEngine', 'status': 'ok',
            'model_configuration': {'provider': 'openrouter', 'primary_model': 'openai/test', 'fallback_model': None},
        })
        cls.health.start()
        threading.Thread(target=cls.gateway.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.gateway.shutdown()
        cls.gateway.server_close()
        cls.health.stop()

    def setUp(self):
        self.pipeline.calls.clear()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_pipeline_receives_canonical_run_and_requested_generation_only(self):
        status, body = self.request('/api/pipeline/connect', 'POST', json.dumps({'run_id': RUN.upper()}),
                                    {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(body['run_id'], RUN)
        status, body = self.request(f'/api/pipeline/status?run_id={RUN}&generation=4')
        self.assertEqual(status, 200)
        self.assertEqual(body['context']['demo_context_id'], f'state-{RUN}-g4')
        self.assertEqual(self.pipeline.calls, [('connect', RUN), ('status', RUN, 4)])

    def test_cross_origin_wrong_host_and_non_json_requests_never_reach_worker(self):
        body = json.dumps({'run_id': RUN})
        for headers, expected in [
            ({'Content-Type': 'application/json', 'Origin': 'https://other.example'}, 403),
            ({'Content-Type': 'application/json', 'Host': 'attacker.example'}, 403),
            ({'Content-Type': 'text/plain'}, 415),
        ]:
            status, _ = self.request('/api/pipeline/connect', 'POST', body, headers)
            self.assertEqual(status, expected)
        self.assertEqual(self.pipeline.calls, [])

    def test_invalid_scope_body_and_method_are_rejected_before_worker(self):
        for body in ['{}', '{', '[]', '{"run_id":"not-a-uuid"}', '{"run_id":null}', 'x' * 4097]:
            status, _ = self.request('/api/pipeline/connect', 'POST', body, {'Content-Type': 'application/json'})
            self.assertEqual(status, 400)
        for query in ['run_id=wrong&generation=0', f'run_id={RUN}&generation=-1', f'run_id={RUN}&generation=1.5']:
            self.assertEqual(self.request('/api/pipeline/status?' + query)[0], 400)
        self.assertEqual(self.request('/api/pipeline/connect')[0], 405)
        self.assertEqual(self.request('/api/pipeline/status', 'POST', '{}', {'Content-Type': 'application/json'})[0], 405)
        self.assertEqual(self.pipeline.calls, [])

    def test_pipeline_config_and_status_do_not_contain_gateway_credentials(self):
        for path in ['/api/config', f'/api/pipeline/status?run_id={RUN}&generation=4']:
            status, result = self.request(path)
            self.assertEqual(status, 200)
            serialized = json.dumps(result)
            for value in ['test-only-private-state', 'test-only-private-platform', 'test-only-private-agent', 'test-only-private-control']:
                self.assertNotIn(value, serialized)
        self.assertTrue(self.request('/api/config')[1]['pipeline_enabled'])


if __name__ == '__main__':
    unittest.main()
