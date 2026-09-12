import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from fire_agents.api import create_app
from fire_agents.engines import FixtureEngine
from fire_agents.models import Event, Answer, Claim
from fire_agents.ui_models import Context, QuestionCreate
from fire_agents.ui_service import UIError

CTX={'demo_context_id':'demo','generation':0,'subject_id':'all'}

def event(eid='1',ms=0,action='assigned',source='radio-a',reading=42):
    return Event(session_id='demo',generation=0,event_id=eid,time_ms=ms,source_id=source,kind='radio',reading_id=reading,
        description=f'Synthetic task T1 {action}',payload={'fixture':{'action':action,'task_ref':'T1'},'api_key':'SECRET',
        'nested':{'ticket':'SECRET','note':'see https://host/?token=SECRET'}})

def setup(tmp_path,engine=None):
    app=create_app(tmp_path/'ui.sqlite',engine or FixtureEngine(),background=False)
    app.state.runtime.store.start('demo');app.state.ui.bind_context('demo',0)
    return app,app.state.ui,app.state.runtime

def request(ctx=None,key='client-1',text='What is known?',language='en'):
    return QuestionCreate(context=ctx or CTX,client_request_id=key,question=text,language=language)

def validate(value,name):
    root=Path(__file__).resolve().parents[1]/'outputs/agent-ui-contract-v0.1/openapi.json'
    spec=json.loads(root.read_text())
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','components':spec['components'],'$ref':'#/components/schemas/'+name}
    Draft202012Validator(schema).validate(value)

def test_question_lifecycle_idempotency_and_evidence(tmp_path):
    app,ui,r=setup(tmp_path);r.store.ingest(event())
    with TestClient(app) as client:
        body=request().model_dump();response=client.post('/agent/v1/questions',json=body)
        assert response.status_code==202;queued=response.json();validate(queued,'Answer')
        assert queued['status']=='queued'
        assert client.post('/agent/v1/questions',json=body).json()['request_id']==queued['request_id']
        assert client.post('/agent/v1/questions',json={**body,'question':'Changed'}).status_code==409
        assert asyncio.run(ui.process_one())
        answer=client.get('/agent/v1/questions/'+queued['request_id'],params=CTX).json()
        validate(answer,'Answer');assert answer['status']=='ready' and answer['revision']>queued['revision']
        assert answer['language']=='en' and answer['queries'][0]['tool']=='local_event_query'
        evidence=client.get('/agent/v1/evidence/'+answer['evidence_ids'][0],params=CTX).json()
        validate(evidence,'Evidence');assert evidence['reading_id']==42
        assert evidence['audio']['availability']=='missing'
        assert 'SECRET' not in json.dumps(evidence['raw_reading'])
        snapshot=client.get('/agent/v1/state',params=CTX).json();validate(snapshot,'Snapshot')
        assert len(snapshot['answers'])==1
        assert client.post('/agent/v1/questions/'+queued['request_id']+'/cancel',params=CTX).json()==answer

def test_cancel_during_model_call(tmp_path):
    class Slow(FixtureEngine):
        async def answer(self,*args,**kwargs):
            started.set();await release.wait();return await super().answer(*args,**kwargs)
    app,ui,r=setup(tmp_path,Slow());r.store.ingest(event());q=ui.submit(request())
    async def run():
        global started,release
        started=asyncio.Event();release=asyncio.Event()
        task=asyncio.create_task(ui.process_one());await started.wait()
        cancelled=ui.cancel(q.context,q.request_id)
        release.set();await task
        assert cancelled.status=='cancelled'
        assert ui.get_answer(q.context,q.request_id).model_dump()==cancelled.model_dump()
    asyncio.run(run())

def test_reset_during_model_call_and_context_isolation(tmp_path):
    class Reset(FixtureEngine):
        async def answer(self,*args,**kwargs):
            r.store.reset('demo');return await super().answer(*args,**kwargs)
    app,ui,r=setup(tmp_path,Reset());r.store.ingest(event());q=ui.submit(request())
    asyncio.run(ui.process_one())
    with TestClient(app) as client:
        assert client.get('/agent/v1/questions/'+q.request_id,params=CTX).status_code==409
        ui.bind_context('demo',1)
        assert client.get('/agent/v1/state',params={**CTX,'generation':1}).json()['answers']==[]

def test_future_and_other_subject_excluded(tmp_path):
    app,ui,r=setup(tmp_path)
    r.store.ingest(event('1',0,source='radio-a'));r.store.ingest(event('2',0,source='radio-b'));r.store.ingest(event('3',100,source='radio-a'))
    narrow=ui.bind_context('demo',0,'a',['radio-a'])
    q=ui.submit(request(narrow));asyncio.run(ui.process_one());answer=ui.get_answer(narrow,q.request_id)
    assert len(answer.claims)==1
    assert ui.evidence(narrow,answer.evidence_ids[0]).device_id=='radio-a'
    with pytest.raises(UIError):ui.evidence(Context(**CTX),answer.evidence_ids[0])
    with pytest.raises(UIError):ui.get_answer(Context(**CTX),q.request_id)

def test_recovery_of_abandoned_question(tmp_path):
    app,ui,r=setup(tmp_path);r.store.ingest(event());q=ui.submit(request());ui._claim_question()
    with r.store.tx() as c:c.execute('UPDATE ui_questions SET lease=0')
    app2=create_app(r.store.path,FixtureEngine(),False);ui2=app2.state.ui
    asyncio.run(ui2.process_one());assert ui2.get_answer(q.context,q.request_id).status=='ready'

def test_model_error_and_unknown_evidence(tmp_path):
    class Broken(FixtureEngine):
        async def answer(self,*a,**kw):return Answer(claims=[Claim(text='fiction',evidence_ids=['not-here'])])
    app,ui,r=setup(tmp_path,Broken());r.store.ingest(event());q=ui.submit(request());asyncio.run(ui.process_one())
    result=ui.get_answer(q.context,q.request_id);validate(result.model_dump(),'Answer')
    assert result.status=='error' and result.claims==[]
    assert result.queries[0].status=='succeeded' # retrieval succeeded, model validation failed

def test_no_platform_id_withholds_claim(tmp_path):
    app,ui,r=setup(tmp_path);r.store.ingest(event(reading=None));q=ui.submit(request());asyncio.run(ui.process_one())
    answer=ui.get_answer(q.context,q.request_id)
    assert answer.status=='insufficient_data' and not answer.claims

def test_card_stable_id_and_revision(tmp_path):
    app,ui,r=setup(tmp_path);r.store.ingest(event());asyncio.run(r.step())
    ctx=Context(**CTX);before=ui.snapshot(ctx);validate(before.model_dump(),'Snapshot')
    first=before.cards[0];assert first.assessment=='checking'
    assert ui.snapshot(ctx).model_dump()==before.model_dump()
    r.store.ingest(event('2',0,'completed',reading=43));asyncio.run(r.step())
    second=ui.snapshot(ctx).cards[0]
    validate(second.model_dump(),'Card')
    assert second.hypothesis_id==first.hypothesis_id and second.revision>first.revision
    assert second.assessment=='supported' and len(second.evidence_ids)==2

def test_sse_updates_and_reset(tmp_path):
    app,ui,r=setup(tmp_path);q=ui.submit(request())
    async def run():
        async def connected():return False
        stream=ui.notifications(q.context,connected)
        data=await anext(stream);assert 'answer.changed' in data
        validate(json.loads(data.split('data: ')[1]),'Changed')
        r.store.reset('demo')
        data=await anext(stream);assert 'context.invalidated' in data
        await stream.aclose()
    asyncio.run(run())

def test_auth_validation_and_missing_context(tmp_path,monkeypatch):
    app,ui,r=setup(tmp_path)
    with TestClient(app) as c:
        bad=c.post('/agent/v1/questions',json={})
        assert bad.status_code==422;validate(bad.json(),'Error')
        assert c.get('/agent/v1/state',params={**CTX,'subject_id':'unauthorized'}).status_code==403
        monkeypatch.setenv('FIRE_UI_SESSION_TOKEN','test-only-secret')
        assert c.get('/agent/v1/state',params=CTX).status_code==401
        assert c.post('/events',json=event().model_dump()).status_code==401
        c.cookies.set('fire_ui_session','test-only-secret')
        assert c.get('/agent/v1/state',params=CTX).status_code==200

def test_live_worker_returns_answer(tmp_path):
    app=create_app(tmp_path/'live.sqlite',FixtureEngine(),True)
    with TestClient(app) as c:
        c.post('/sessions/demo');c.post('/events',json=event().model_dump())
        rid=c.post('/agent/v1/questions',json=request().model_dump()).json()['request_id']
        import time
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            response=c.get('/agent/v1/questions/'+rid,params=CTX).json()
            if response['status'] in ('ready','error','insufficient_data'):break
            time.sleep(.05)
        assert response['status']=='ready'
