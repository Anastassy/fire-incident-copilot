"""Start the local dashboard and, when necessary, its fixture API process."""
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / 'agent-service'

def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8010/health',timeout=1) as response:
            return response.status==200
    except OSError:return False

def main():
    children=[]
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        if not healthy():
            python=AGENT/'.venv/bin/python'
            if not python.is_file():
                raise SystemExit('First run uv sync --frozen in agent-service/')
            children.append(subprocess.Popen([str(python),'-m','uvicorn','fire_agents.api:create_app','--factory','--host','127.0.0.1','--port','8010'],cwd=AGENT))
            for _ in range(100):
                if healthy():break
                if children[0].poll() is not None:raise SystemExit('The agent failed to start.')
                time.sleep(.1)
            else:raise SystemExit('The agent did not respond within 10 seconds.')
        children.append(subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py')),'--demo-agent',*sys.argv[1:]],cwd=ROOT))
        children[-1].wait()
    except KeyboardInterrupt:pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()

if __name__=='__main__':main()
