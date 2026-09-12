"""Contract/security boundaries of the local gateway, with a loopback upstream."""
import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location('gateway', Path(__file__).parents[1] / 'server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.received.append(dict(self.headers))
        data=json.dumps({'engine':'FixtureEngine','status':'ok'}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    do_POST=do_GET

class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream);cls.upstream.received=[]
        url='http://127.0.0.1:'+str(cls.upstream.server_port)
        cls.gateway=module.Gateway(('127.0.0.1',0),dict(state_url=url,agent_url=url,platform_url=url,
            read_token='private-read-test',control_token='private-control-test',agent_token='private-agent-test',
            platform_key='private-platform-test',demo_agent=False,agent_context={},scenario='test'))
        for server in [cls.upstream,cls.gateway]:threading.Thread(target=server.serve_forever,daemon=True).start()
        cls.base='http://127.0.0.1:'+str(cls.gateway.server_port)
    @classmethod
    def tearDownClass(cls):
        for s in [cls.gateway,cls.upstream]:s.shutdown();s.server_close()
    def request(self,path,method='GET',headers=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base+path,method=method,headers=headers or {},data=b'{}' if method=='POST' else None),timeout=2) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    def test_config_and_assets_do_not_expose_secrets(self):
        for path in ['/api/config','/','/app.js']:
            status,body=self.request(path);self.assertEqual(status,200)
            for secret in ['private-read-test','private-control-test','private-agent-test','private-platform-test']:self.assertNotIn(secret.encode(),body)
        self.assertEqual(self.request('/server.py')[0],404)
        self.assertEqual(self.request('/../server.py')[0],404)
    def test_credentials_and_range_are_injected_only_server_side(self):
        self.assertEqual(self.request('/api/state/runs/r/media/m/content',headers={'Range':'bytes=0-9'})[0],200)
        self.assertEqual(self.upstream.received[-1]['Authorization'],'Bearer private-read-test')
        self.assertEqual(self.upstream.received[-1]['Range'],'bytes=0-9')
        self.assertEqual(self.request('/api/state/runs/r/commands','POST',{'Content-Type':'application/json'})[0],200)
        self.assertEqual(self.upstream.received[-1]['Authorization'],'Bearer private-control-test')
    def test_cross_origin_mutation_and_out_of_scope_routes_rejected(self):
        self.assertEqual(self.request('/api/state/runs','POST',{'Origin':'https://unrelated.example','Content-Type':'application/json'})[0],403)
        self.assertEqual(self.request('/api/state/runs','POST')[0],415)
        self.assertEqual(self.request('/api/agent/sessions/test','POST',{'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.request('/api/platform/incidents','POST',{'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.request('/api/agent-demo','POST',{'Content-Type':'application/json'})[0],403)

if __name__=='__main__':unittest.main()
