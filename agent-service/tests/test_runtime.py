import asyncio
import json
from fastapi.testclient import TestClient
from fire_agents.api import create_app
from fire_agents.store import Store, StaleGeneration
from fire_agents.models import Event, Answer, Claim
from fire_agents.engines import FixtureEngine, SDKEngine
from fire_agents.runtime import Runtime
import pytest

def event(id='1',action='assigned',ms=0,generation=0):
    return Event(session_id='demo',generation=generation,event_id=id,time_ms=ms,source_id='radio-1',kind='radio',
        description=f'Поручение T1: {action}',payload={'fixture':{'action':action,'task_ref':'T1','team':'2'}})

def setup(tmp_path):
    s=Store(tmp_path/'test.db');s.start('demo');return s,Runtime(s,FixtureEngine(),100)

def drain(r):
    async def run():
        for _ in range(10):
            if not await r.step(): return
        raise AssertionError('Queue did not drain')
    asyncio.run(run())

def test_assignment_late_report_and_no_duplicate(tmp_path):
    s,r=setup(tmp_path)
    assert s.ingest(event()); assert not s.ingest(event())
    s.tick('demo',0,101)
    assert not s.state('demo',0)['outbox'] # unprocessed data blocks timeout
    drain(r);s.tick('demo',0,101);s.tick('demo',0,102)
    assert len(s.state('demo',0)['outbox'])==1
    s.ingest(event('2','completed',90));drain(r)
    rows=s.state('demo',0)['outbox']
    assert len(rows)==2
    assert json.loads(rows[-1]['body'])['platform_status']=='resolved'

def test_restart_recovers_lease(tmp_path):
    s,r=setup(tmp_path);s.ingest(event());s.claim_job()
    with s.tx() as c:c.execute('UPDATE jobs SET lease_until=0')
    restored=Runtime(Store(s.path),FixtureEngine(),100);drain(restored)
    assert s.state('demo',0)['jobs'][0]['status']=='done'

def test_reset_rejects_old_results(tmp_path):
    s,r=setup(tmp_path);s.ingest(event());job=s.claim_job();s.reset('demo')
    result=asyncio.run(FixtureEngine().extract(event()))
    with pytest.raises(StaleGeneration):s.finish(job,result,100)
    assert not s.state('demo',1)['watches']

def test_event_immutable(tmp_path):
    s,r=setup(tmp_path);s.ingest(event())
    with pytest.raises(ValueError):s.ingest(event(action='completed'))

def test_invalid_evidence_not_published(tmp_path):
    s,r=setup(tmp_path);s.ingest(event())
    class Bad(FixtureEngine):
        async def answer(self,q,events):return Answer(claims=[Claim(text='fiction',evidence_ids=['missing'])])
    with pytest.raises(ValueError):asyncio.run(Runtime(s,Bad()).answer('demo',0,'вопрос'))

def test_api(tmp_path):
    with TestClient(create_app(tmp_path/'api.db',FixtureEngine(),False)) as c:
        assert c.post('/sessions/demo').status_code==200
        assert c.post('/events',json=event().model_dump()).json()['inserted']
        assert c.post('/agent/questions',json={'session_id':'demo','generation':0,'text':'Что известно?'}).status_code==200
        c.post('/sessions/demo/reset')
        assert c.post('/events',json=event().model_dump()).status_code==409

def test_sdk_definitions_build_without_network():
    engine=SDKEngine('explicit-model-for-test')
    assert engine.extractor.output_type.__name__=='Extraction'
