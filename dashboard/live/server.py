"""Loopback dashboard gateway. Provider/application keys remain outside browser assets."""
from pathlib import Path
import argparse
import http.server
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


class Gateway(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, settings):
        self.settings = settings
        super().__init__(address, Handler)
    def handle_error(self, request, client_address):
        pass  # Disconnects must not log request URLs carrying media tickets.


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass

    def json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def request_json(self, target, path, method='GET', body=None):
        settings = self.server.settings
        headers = {'Content-Type': 'application/json'}
        if target == 'agent' and settings.get('agent_token'):
            headers['Cookie'] = 'fire_ui_session=' + settings['agent_token']
        request = urllib.request.Request(settings[target + '_url'] + path,
            data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.load(response)

    def handle_request(self):
        # A local tool, never an unauthenticated public proxy.
        host = self.headers.get('Host', '').split(':')[0]
        if host not in ['127.0.0.1', 'localhost']:
            return self.json({'error': 'Loopback host required'}, 403)
        origin = self.headers.get('Origin')
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'):
            return self.json({'error': 'Cross-origin request rejected'}, 403)
        if self.command == 'POST' and 'application/json' not in self.headers.get('Content-Type', ''):
            return self.json({'error': 'JSON required'}, 415)
        path = urllib.parse.urlsplit(self.path).path
        settings = self.server.settings
        if path == '/api/config' and self.command == 'GET':
            try: agent = self.request_json('agent', '/health')
            except Exception: agent = {'status': 'unavailable', 'engine': None}
            return self.json({'state_configured': bool(settings.get('read_token')),
                'state_url': settings['state_url'], 'agent_url': settings['agent_url'],
                'agent': agent, 'demo_agent': settings['demo_agent'],
                'agent_context': settings['agent_context'], 'scenario': settings['scenario'],
                'platform_configured': bool(settings.get('platform_url')),
                'platform_url': settings.get('platform_url')})
        if path == '/api/agent-demo' and self.command == 'POST':
            if not settings['demo_agent']:
                return self.json({'error': 'Demo seed is disabled'}, 403)
            if self.request_json('agent', '/health').get('engine') != 'FixtureEngine':
                return self.json({'error': 'Demo seed requires the explicit fixture engine'}, 409)
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            action = body.get('action')
            if action not in ['request', 'assign', 'acknowledge', 'reset']:
                return self.json({'error': 'Unknown fixture action'}, 422)
            sid = 'dashboard-channel-demo'
            session = self.request_json('agent', '/sessions/' + sid, 'POST', {})
            if action == 'reset':
                session = self.request_json('agent', '/sessions/' + sid + '/reset', 'POST', {})
            else:
                phase = {'request': (1, 1000, 'channel_requested', None, 'Demo Group', 'Синтетический тест: Demo Group запрашивает рабочий канал.'),
                         'assign': (2, 2000, 'channel_assigned', 'V-Fire 25', None, 'Синтетический тест: назначен канал V-Fire 25.'),
                         'acknowledge': (3, 3000, 'channel_acknowledged', 'V-Fire 25', None, 'Синтетический тест: отдельная реплика подтверждает V-Fire 25.')}[action]
                reading, timestamp, fact, channel, team, description = phase
                self.request_json('agent', '/events', 'POST', {'session_id': sid, 'generation': session['generation'],
                    'event_id': 'demo-channel-' + action, 'reading_id': reading,
                    'time_ms': timestamp, 'source_id': '00000000-0000-0000-0000-000000000001', 'kind': 'radio',
                    'description': description,
                    'payload': {'fixture': {'action': fact, 'channel': channel, 'team': team}}})
                self.request_json('agent', f'/sessions/{sid}/{session["generation"]}/clock', 'POST',
                    {'time_ms': max(session['time_ms'], timestamp)})
            return self.json({'demo_context_id': sid, 'generation': session['generation'], 'subject_id': 'all'})
        for target in ['state', 'agent', 'platform']:
            prefix = '/api/' + target
            if self.path.startswith(prefix + '/'):
                return self.proxy(target, self.path[len(prefix):])
        if self.command != 'GET': return self.json({'error': 'Not found'}, 404)
        relative = 'index.html' if path == '/' else urllib.parse.unquote(path).lstrip('/')
        file = (ROOT / relative).resolve()
        if not file.is_relative_to(ROOT) or file.suffix not in ['.html', '.js', '.css', '.svg', '.woff2'] or not file.is_file():
            return self.json({'error': 'Not found'}, 404)
        content = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(file)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def proxy(self, target, path):
        settings = self.server.settings
        if not settings.get(target + '_url'):
            return self.json({'error': 'Upstream is not configured'}, 503)
        allowed = {'state': ['/health', '/scenarios', '/capabilities', '/runs'],
                   'agent': ['/health', '/agent/v1/'],
                   'platform': ['/devices', '/telemetry', '/incidents', '/stream/', '/dashboards']}
        clean = urllib.parse.urlsplit(path).path
        if not any(clean == p or clean.startswith(p if p.endswith('/') else p + '/') for p in allowed[target]):
            return self.json({'error': 'Route is outside the dashboard scope'}, 403)
        if target == 'platform' and self.command != 'GET':
            return self.json({'error': 'Platform access is read only'}, 403)
        headers = {'Accept': self.headers.get('Accept', '*/*')}
        for name in ['Content-Type', 'Range', 'If-Range', 'Last-Event-ID', 'Idempotency-Key']:
            if name in self.headers: headers[name] = self.headers[name]
        if target == 'state':
            token = settings.get('control_token' if self.command == 'POST' else 'read_token')
            if not token: return self.json({'error': 'State API credentials are not configured'}, 503)
            headers['Authorization'] = 'Bearer ' + token
        elif target == 'agent' and settings.get('agent_token'):
            headers['Cookie'] = 'fire_ui_session=' + settings['agent_token']
        elif target == 'platform' and settings.get('platform_key'):
            headers['X-API-Key'] = settings['platform_key']
        length = int(self.headers.get('Content-Length', 0))
        if length > 65536: return self.json({'error': 'Request too large'}, 413)
        body = self.rfile.read(length) if length else None
        request = urllib.request.Request(settings[target + '_url'] + path, data=body, method=self.command, headers=headers)
        try: response = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as error: response = error
        except (OSError, ValueError): return self.json({'error': target + ' service is unavailable'}, 502)
        self.send_response(response.status)
        for name in ['Content-Type', 'Content-Range', 'Accept-Ranges', 'ETag', 'Retry-After']:
            if name in response.headers: self.send_header(name, response.headers[name])
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                chunk = response.read1(65536)
                if not chunk: break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError): pass
        finally: response.close()

    def do_GET(self):
        try: self.handle_request()
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception: self.json({'error': 'Gateway request failed'}, 502)
    do_POST = do_GET


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--state-config', type=Path)
    parser.add_argument('--agent-url', default='http://127.0.0.1:8010')
    parser.add_argument('--agent-context', default='dashboard-channel-demo')
    parser.add_argument('--agent-generation', type=int, default=0)
    parser.add_argument('--subject', default='all')
    parser.add_argument('--scenario', default='base2-palisades-v1')
    parser.add_argument('--demo-agent', action='store_true')
    args = parser.parse_args()
    state = json.loads(args.state_config.read_text()) if args.state_config else {}
    settings = {'state_url': state.get('base_url', os.getenv('STATE_API_URL', 'https://api.aitinkerers.space/api/v1')).rstrip('/'),
        'read_token': state.get('read_token', os.getenv('STATE_READ_TOKEN')),
        'control_token': state.get('control_token', os.getenv('STATE_CONTROL_TOKEN')),
        'agent_url': args.agent_url.rstrip('/'), 'agent_token': os.getenv('FIRE_UI_SESSION_TOKEN'),
        'platform_url': os.getenv('PLATFORM_API_URL', '').rstrip('/'), 'platform_key': os.getenv('PLATFORM_API_KEY'),
        'demo_agent': args.demo_agent, 'scenario': args.scenario,
        'agent_context': {'demo_context_id': args.agent_context, 'generation': args.agent_generation, 'subject_id': args.subject}}
    server = Gateway(('127.0.0.1', args.port), settings)
    print(f'Command dashboard: http://127.0.0.1:{args.port}/', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == '__main__': main()
