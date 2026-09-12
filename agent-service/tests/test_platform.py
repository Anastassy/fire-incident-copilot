import asyncio
from types import SimpleNamespace
import pytest
from fire_agents.platform import Reader, Publisher, MCPTools
from fire_agents.store import Store
from fire_agents.engines import FixtureEngine
from fire_agents.runtime import Runtime
from fire_agents.models import Event

class FakeTools:
    def __init__(self):self.calls=[];self.fail=False;self.rows=[]
    async def call(self,name,args):
        self.calls.append((name,args))
        if self.fail:raise TimeoutError()
        if name=='query_telemetry':return self.rows
        if name=='get_incident':return {'id':'i1','status':'acknowledged','evidence':[]}
        return {'id':'i1'}

def make(tmp_path):
    s=Store(tmp_path/'db');s.start('demo');return s,FakeTools()

def prepare(s):
    e=Event(session_id='demo',generation=0,event_id='42',reading_id=42,time_ms=0,source_id='radio',kind='radio',
        description='Поручение T1 принято',payload={'fixture':{'action':'assigned','task_ref':'T1'}})
    s.ingest(e);asyncio.run(Runtime(s,FixtureEngine(),10).step());s.tick('demo',0,11)

def test_reader_mapping_and_truncation(tmp_path):
    s,t=make(tmp_path)
    t.rows=[{'id':42,'device_id':'radio','metric_type':'radio_audio','ts':'2026-01-01T00:00:01Z',
             'payload':{'custom_text':'Принял','clip':'https://example.invalid/audio'}}]
    kwargs=dict(session_id='demo',generation=0,device_id='radio',since='2026-01-01T00:00:00Z',until='2026-01-01T00:00:02Z',epoch='2026-01-01T00:00:00Z',description_field='custom_text',media_field='clip',limit=1)
    result=asyncio.run(Reader(t,s).pull(**kwargs))
    assert result['possibly_truncated'] and not result['coverage_complete']
    assert s.events('demo',0)[0].description=='Принял'
    assert asyncio.run(Reader(t,s).pull(**kwargs))['inserted']==0

def test_publish_once(tmp_path):
    s,t=make(tmp_path);prepare(s);p=Publisher(t,s)
    assert asyncio.run(p.step())
    assert not asyncio.run(p.step())
    assert [n for n,a in t.calls]==['create_incident']
    assert s.state('demo',0)['outbox'][0]['status']=='sent'

def test_unknown_write_is_not_retried(tmp_path):
    s,t=make(tmp_path);prepare(s);t.fail=True;p=Publisher(t,s)
    asyncio.run(p.step());t.fail=False
    assert not asyncio.run(Publisher(t,s).step())
    assert len(t.calls)==1
    assert s.state('demo',0)['outbox'][0]['status']=='uncertain'

def test_reset_before_publish(tmp_path):
    s,t=make(tmp_path);prepare(s);s.reset('demo')
    assert not asyncio.run(Publisher(t,s).step());assert not t.calls

def test_update_preserves_operator_status(tmp_path):
    s,t=make(tmp_path);prepare(s);p=Publisher(t,s);asyncio.run(p.step())
    s.ingest(Event(session_id='demo',generation=0,event_id='43',reading_id=43,time_ms=20,source_id='radio',kind='radio',description='T1 завершено',payload={'fixture':{'action':'completed','task_ref':'T1'}}))
    asyncio.run(Runtime(s,FixtureEngine(),10).step());asyncio.run(p.step())
    updates=[a for n,a in t.calls if n=='update_incident']
    assert len(updates)==1 and 'status' not in updates[0]
    assert 'supported_by_report' in updates[0]['note']

def test_mcp_wrapped_result():
    class Server:
        async def call_tool(self,name,args):return SimpleNamespace(isError=False,structuredContent={'result':[{'id':1}]})
    assert asyncio.run(MCPTools(Server()).call('query_telemetry',{}))==[{'id':1}]

def test_sse_signal_and_auth_failure():
    import httpx
    from fire_agents.live import watch_telemetry
    async def run():
        count=0
        def handler(request):
            nonlocal count
            count+=1
            if count==1:return httpx.Response(200,text=': keepalive\r\ndata: {"x":\r\ndata: 1}\r\n\r\n')
            return httpx.Response(401)
        changed=asyncio.Event()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await watch_telemetry('https://platform.invalid/stream/telemetry','test-key',changed,client=client)
        assert changed.is_set() and count==2
    asyncio.run(run())
