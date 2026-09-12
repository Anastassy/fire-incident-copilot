#!/usr/bin/env bash
# Prerequisites: Node.js >=18, Python >=3.12, uv.
# Prepare dependencies once: uv sync --project agent-service --locked
# Verification itself never installs packages or contacts live services.
set -euo pipefail

verify_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$verify_root"
verify_python="$verify_root/agent-service/.venv/bin/python"

if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)'; then
  printf '%s\n' 'ERROR: Node.js >=18 is required (npm is required for npm run verify).' >&2
  exit 1
fi
if [[ ! -x "$verify_python" ]]; then
  printf '%s\n' 'ERROR: Agent Python environment is missing. Install Python >=3.12 and uv, then run: uv sync --project agent-service --locked' >&2
  exit 1
fi
if ! "$verify_python" - <<'PY'
import importlib.util
import sys
assert sys.version_info >= (3, 12), 'Python >=3.12 is required'
required = ('pytest', 'fastapi', 'httpx', 'agents', 'jsonschema', 'sqlalchemy', 'pydantic_settings')
missing = [name for name in required if importlib.util.find_spec(name) is None]
assert not missing, f'Missing agent dependencies: {", ".join(missing)}'
PY
then
  printf '%s\n' 'ERROR: Agent dependencies are incomplete. Run: uv sync --project agent-service --locked' >&2
  exit 1
fi

# Do not inherit runtime credentials/configuration into the test process.
while IFS= read -r verify_name; do
  case "$verify_name" in
    FIRE_*|STATE_*|PLATFORM_*|OPENAI_*|OPENROUTER_*|PYTEST_ADDOPTS|PYTHONPATH)
      unset "$verify_name" ;;
  esac
done < <(compgen -e)
export FIRE_ENGINE=fixture
export OPENAI_AGENTS_DISABLE_TRACING=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

printf '%s\n' 'Running dashboard JavaScript tests and design adapter checks...'
node --test dashboard/live/tests/*.test.js
node dashboard/docs/design/palisades/mock-adapters.test.cjs

"$verify_python" - <<'PY'
import ipaddress
import os
from pathlib import Path
import socket
import sys
import unittest

# Gateway tests use temporary loopback HTTP fixtures. Reject every other network
# destination, including DNS lookups, so regressions cannot call an API or LLM.
def local(host):
    if isinstance(host, bytes):
        host = host.decode('ascii')
    if host in (None, '', 'localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

original_resolve = socket.getaddrinfo
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex

def resolve(host, *args, **kwargs):
    if not local(host):
        raise RuntimeError('Offline verification blocked external DNS/network access')
    return original_resolve(host, *args, **kwargs)

def connect(method):
    def guarded(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not local(address[0]):
            raise RuntimeError('Offline verification blocked external network access')
        return method(sock, address)
    return guarded

socket.getaddrinfo = resolve
socket.socket.connect = connect(original_connect)
socket.socket.connect_ex = connect(original_connect_ex)

root = Path.cwd()
print('Running dashboard Python gateway and pipeline tests...', flush=True)
suite = unittest.defaultTestLoader.discover(str(root / 'dashboard/live/tests'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    sys.exit(1)

print('Running agent pytest suite with fixture/mocked models...', flush=True)
os.chdir(root / 'agent-service')
sys.path.insert(0, str(Path.cwd()))
import pytest
sys.exit(pytest.main(['-q', 'tests']))
PY

printf '%s\n' 'PASS: offline dashboard and agent suites.'
printf '%s\n' 'Not run: Platform database integration tests, live State/Platform services, or live LLM calls.'
