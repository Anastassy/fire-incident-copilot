import asyncio
from unittest.mock import AsyncMock

from agents import Runner
from fire_agents.api import create_app
from fire_agents.engines import FixtureEngine, SDKEngine
from fire_agents.models import Event
from fire_agents.model_input import compact_event
from fire_agents.ui_models import Context


def sample(eid, ms, kind='radio', source='radio', metric=None, value=None):
    return Event(session_id='live', generation=0, event_id=eid, time_ms=ms,
                 source_id=source, kind=kind, reading_id=ms+1,
                 description=eid, payload={'platform': {'metric_type': metric,
                                                          'value': value}})


def test_radio_context_survives_dense_sensor_traffic(tmp_path):
    app=create_app(tmp_path/'live.sqlite', FixtureEngine(), background=False)
    store=app.state.runtime.store
    store.start('live')
    store.ingest(sample('group-report', 1))
    for i in range(50):
        store.ingest(sample(f'sensor-{i}', i+2, 'sensor', 'thermometer', 'temperature', i))
    event=sample('channel-request', 60)
    assert [e.event_id for e in store.recent_context(event)] == ['group-report']


def test_question_keeps_latest_readings_and_radio_without_future_data(tmp_path):
    app=create_app(tmp_path/'live.sqlite', FixtureEngine(), background=False)
    store=app.state.runtime.store
    store.start('live');app.state.ui.bind_context('live', 0)
    store.ingest(sample('group-report', 1))
    for i in range(60):
        store.ingest(sample(f'temp-{i}', i+2, 'sensor', 'thermometer', 'temperature', i))
    store.ingest(sample('occupancy-unknown', 63, 'sensor', 'people', 'occupancy', None))
    store.ingest(sample('real-zero', 64, 'sensor', 'smoke', 'smoke', 0))
    store.ingest(sample('future-ack', 100))
    with store.tx() as c:
        result=app.state.ui._events(c, Context(demo_context_id='live',generation=0,subject_id='all'), 70)
    by_id={e.event_id:e for e in result}
    assert {'group-report','temp-59','occupancy-unknown','real-zero'} <= set(by_id)
    assert 'future-ack' not in by_id
    assert by_id['occupancy-unknown'].payload['platform']['value'] is None
    assert by_id['real-zero'].payload['platform']['value'] == 0
    assert len(result) <= 20


def test_sensor_updates_do_not_queue_radio_model_calls(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only')
    monkeypatch.delenv('FIRE_FALLBACK_MODEL', raising=False)
    run=AsyncMock()
    monkeypatch.setattr(Runner, 'run', run)
    engine=SDKEngine('test-model')
    event=sample('temperature', 1, 'sensor', 'thermometer', 'temperature', 48)
    assert asyncio.run(engine.extract(event)).action == 'none'
    assert asyncio.run(engine.extract_with_context(event, [])).action == 'none'
    run.assert_not_called()


def test_fast_models_use_distinct_reasoning_settings(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only')
    monkeypatch.setenv('FIRE_FALLBACK_MODEL', 'openai/gpt-5.6-luna')
    monkeypatch.setenv('FIRE_REASONING_EFFORT', 'minimal')
    monkeypatch.setenv('FIRE_FALLBACK_REASONING_EFFORT', 'none')
    monkeypatch.setenv('FIRE_MAX_OUTPUT_TOKENS', '1200')
    monkeypatch.setenv('FIRE_PROVIDER_SORT', 'latency')
    engine=SDKEngine('google/gemini-3.5-flash-lite')
    assert engine.responder.model_settings.extra_body['reasoning']['effort'] == 'minimal'
    assert engine.fallback_responder.model_settings.extra_body['reasoning']['effort'] == 'none'
    assert engine.responder.model_settings.extra_body['provider']['sort'] == 'latency'
    assert engine.responder.model_settings.max_tokens == 1200


def test_compaction_retains_radio_and_raw_evidence_under_payload_budget(tmp_path):
    app=create_app(tmp_path/'live.sqlite', FixtureEngine(), background=False)
    store=app.state.runtime.store
    store.start('live');app.state.ui.bind_context('live', 0)
    radio=sample('channel-assignment',1)
    radio.description='Use V-Fire 25.'
    p=radio.payload['platform']
    p['transcript']=radio.description
    p['payload']={'words':[{'text':'timing detail'}]*150,
                  'machine_generated':True,'human_verified':False,
                  'state_observation':{'room_id':'radio','device_id':'R1','data':{'words':['original']*100}}}
    p['provenance']={'origin':'derived','composition_note':'Unrelated historical radio',
                     'state_machine':{'run_id':'source-run','generation':4,'evidence_id':'original-id'}}
    raw=radio.model_dump_json();store.ingest(radio)
    for i in range(10):
        event=sample(f'reading-{i}',i+2,'sensor',f'device-{i}','temperature',None if i==0 else 0)
        event.payload['platform']['payload']={'state_observation':{'data':{'repeated': 'x'*8000}}}
        store.ingest(event)
    with store.tx() as c:
        result=app.state.ui._events(c,Context(demo_context_id='live',generation=0,subject_id='all'),20)
        stored=c.execute("SELECT body FROM events WHERE event_id='channel-assignment'").fetchone()['body']
    by_id={e.event_id:e for e in result}
    assert set(by_id)=={'channel-assignment',*(f'reading-{i}' for i in range(10))}
    assert stored==raw==radio.model_dump_json()
    view=by_id['channel-assignment'];vp=view.payload['platform']
    assert vp['transcript']=='Use V-Fire 25.'
    assert vp['provenance']==p['provenance']
    assert vp['payload']['machine_generated'] is True
    assert vp['payload']['room_id']=='radio'
    assert 'words' not in vp['payload'] and 'state_observation' not in vp['payload']
    assert compact_event(view)==view
    assert by_id['reading-0'].payload['platform']['value'] is None
    assert by_id['reading-1'].payload['platform']['value']==0
