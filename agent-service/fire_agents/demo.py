import asyncio
import json
import tempfile
from pathlib import Path
from .store import Store
from .runtime import Runtime
from .engines import FixtureEngine
from .models import Event

async def main():
    with tempfile.TemporaryDirectory() as directory:
        store=Store(Path(directory)/'demo.db');store.start('demo')
        runtime=Runtime(store,FixtureEngine(),100)
        for identifier,action,ms in [('1','assigned',0),('2','completed',110)]:
            store.ingest(Event(session_id='demo',generation=0,event_id=identifier,time_ms=ms,
                source_id='radio',kind='radio',description=f'Тестовая реплика T1: {action}',
                payload={'fixture':{'action':action,'task_ref':'T1','team':'2'}}))
            await runtime.step()
            store.tick('demo',0,105 if identifier=='1' else 120)
        print(json.dumps(store.state('demo',0),ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
