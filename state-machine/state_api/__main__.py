from pathlib import Path
import argparse
import json
import os
import signal
import threading
from .core import Store
from .http import Service, Server

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--bundle',required=True);p.add_argument('--database',required=True)
    p.add_argument('--config',required=True);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8787)
    p.add_argument('--spec',default=str(Path(__file__).resolve().parents[1]/'contracts/v0.2/openapi.json'))
    args=p.parse_args()
    config=json.loads(Path(args.config).read_text())
    store=Store(args.bundle,args.database,max_runs=config.get('max_runs',16))
    service=Service(store,config,args.spec);server=Server((args.host,args.port),service)
    def tick():
        while not service.stop.wait(.25):
            try:store.tick()
            except Exception:
                # A failed durable transaction restarts from the last committed state.
                import traceback
                traceback.print_exc()
                os._exit(1)
    threading.Thread(target=tick,daemon=True).start()
    def stop(*_):
        service.stop.set();threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    print(f'Raw State API listening on {args.host}:{args.port}; schema 0.2',flush=True)
    try:server.serve_forever(poll_interval=.2)
    finally:service.stop.set();server.server_close();store.close()

if __name__=='__main__':main()
