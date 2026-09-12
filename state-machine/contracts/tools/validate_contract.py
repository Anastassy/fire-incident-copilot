"""Validate OpenAPI, synthetic examples, event references and consumer recovery invariants."""
from pathlib import Path
import copy
import datetime
import json
import math
import re

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec

ROOT=Path(__file__).resolve().parents[1]/'v0.2'
spec=json.loads((ROOT/'openapi.json').read_text())
validate_spec(spec)
schemas=spec['components']['schemas']
for schema in schemas.values():Draft202012Validator.check_schema(schema)
def validator(name):
    return Draft202012Validator({'$ref':'#/components/schemas/'+name,'components':spec['components']},format_checker=FormatChecker())
def validate(name,value):validator(name).validate(value)
def finite(value):
    if isinstance(value,float):assert math.isfinite(value)
    if isinstance(value,dict):
        for v in value.values():finite(v)
    if isinstance(value,list):
        for v in value:finite(v)

manifest=json.loads((ROOT/'examples/manifest.json').read_text())
for filename,name in manifest['examples'].items():
    data=json.loads((ROOT/'examples'/filename).read_text());validate(name,data);finite(data)
events=json.loads((ROOT/'examples/events.json').read_text())
for event in events:validate('Event',event);finite(event)
initial=json.loads((ROOT/'examples/snapshot.initial.json').read_text())
final=json.loads((ROOT/'examples/snapshot.after-play.json').read_text())
assert [e['sequence'] for e in events]==list(range(1,len(events)+1))
assert len({e['event_id'] for e in events})==len(events)
assert len({e['cursor'] for e in events})==len(events)
assert all(e['run_id']==initial['run']['run_id'] and e['generation']==0 for e in events)
assert all(a['sim_time_ms']<=b['sim_time_ms'] for a,b in zip(events,events[1:]))
evidence={}
for event in events:
    kind,data=event['kind'],event['data']
    if kind=='observation.created':
        assert data['observed_sim_time_ms']<=data['received_sim_time_ms']<=event['sim_time_ms']
        assert data['evidence_id'] not in evidence;evidence[data['evidence_id']]=data
        if data['kind']=='camera':assert data['data']['capture_end_sim_time_ms']<=event['sim_time_ms']
        if data['kind']=='radio_audio':assert data['data']['audio_end_sim_time_ms']<=event['sim_time_ms']
    elif kind=='device.updated':
        assert data['last_observation_id'] is None or data['last_observation_id'] in evidence
        for reading in data['readings']:
            assert reading['observation_id'] in evidence
            assert reading['age_ms']==event['sim_time_ms']-reading['observed_sim_time_ms']
    elif kind=='access.updated':
        assert all(id in evidence for id in data['evidence_ids'])
    elif kind=='occupancy.updated':
        if data['basis']=='source_count':
            source=evidence[data['observation_id']]
            assert source['kind']=='people_count' and data['count']==source['data']['count']
        else:assert data['count'] is None and data['observation_id'] is None

for filename in ['media.video.json','media.audio.json']:
    media=json.loads((ROOT/'examples'/filename).read_text())
    assert media['capture_start_sim_time_ms']<=media['capture_end_sim_time_ms']<=media['published_sim_time_ms']
    assert media['duration_ms']==media['capture_end_sim_time_ms']-media['capture_start_sim_time_ms']
    assert media['published_sim_time_ms']<=final['run']['sim_time_ms']

def upsert(items,value,key):
    for i,item in enumerate(items):
        if item[key]==value[key]:items[i]=copy.deepcopy(value);return
    items.append(copy.deepcopy(value))

def reduce_events(messages):
    state=copy.deepcopy(initial)
    for event in messages:
        if event['sequence']<=state['as_of']['sequence']:continue
        assert event['sequence']==state['as_of']['sequence']+1
        kind,data=event['kind'],event['data']
        if kind=='run.updated':state['run']=copy.deepcopy(data)
        elif kind=='system.updated':state['system']=copy.deepcopy(data)
        elif kind=='radio.channel.updated':upsert(state['radio']['channels'],data,'channel_id')
        else:
            target={'device.updated':('devices','device_id'),'camera.updated':('cameras','camera_id'),
                    'room.updated':('rooms','room_id'),'access.updated':('access','scope_id'),
                    'occupancy.updated':('occupancy','scope_id')}.get(kind)
            if target:upsert(state[target[0]],data,target[1])
        state['as_of']={'sequence':event['sequence'],'cursor':event['cursor']}
    return state

assert reduce_events(events)==final
assert reduce_events([e for event in events for e in [event,event]])==final
assert reduce_events(events[:10]+events[8:])==final  # reconnect with overlap
assert final['occupancy'][0]['count'] is None
smoke=next(d for d in final['devices'] if d['device_id']=='SMK-SRV')
assert smoke['availability']=='disconnected' and smoke['readings'][0]['value']==11.017
assert smoke['readings'][0]['observation_id']=='ev-smoke-1'
assert final['rooms'][0]['unavailable_device_ids']==['SMK-SRV']
assert final['access'][0]['confirmed_entries'] is None
assert final['access'][0]['confirmed_exits'] is None
people=json.loads((ROOT/'examples/observation.people-count.json').read_text())
count=json.loads((ROOT/'examples/occupancy.source-count.json').read_text())
assert count['observation_id']==people['evidence_id'] and count['count']==people['data']['count']
assert people['kind']=='people_count'
transcript=json.loads((ROOT/'examples/observation.radio-transcript.json').read_text())
assert transcript['kind']=='radio_transcript' and transcript['data']['delivery']=='prerecorded'
assert transcript['data']['audio_end_sim_time_ms']<=transcript['received_sim_time_ms']
assert transcript['data']['machine_generated'] and not transcript['data']['human_verified']
assert all(w['end_sim_time_ms']<=transcript['received_sim_time_ms'] for w in transcript['data']['words'])

# A raw-data producer must not accidentally export recognition or derived incident state.
forbidden={'analysis_mode','analysis_modes','asr','asr_live','transcript_replay',
           'transcription_status','latest_transcripts','transcripts_total','pending_audio_ms',
           'context','conclusions','overall_severity','severity','condition','hazard_latched',
           'assessment','assessment_evidence_ids','signal_quality','speaker_ref'}
def check_raw(value):
    if isinstance(value,dict):
        assert not forbidden.intersection(value), forbidden.intersection(value)
        for item in value.values():check_raw(item)
    elif isinstance(value,list):
        for item in value:check_raw(item)
check_raw(spec)
for name in manifest['examples']:check_raw(json.loads((ROOT/'examples'/name).read_text()))
check_raw(events)
assert not {'Transcript','TranscriptSpan','Conclusion','Context','VisualAssessmentData','ReportData'}.intersection(schemas)
assert all('/transcripts' not in path and '/context' not in path for path in spec['paths'])
assert final['system']['events']['observed']==sum(e['kind']=='observation.created' for e in events)
assert final['system']['events']['processed']==sum(final['system']['events'][k] for k in ['observed','suppressed','transport_controls'])
reset=json.loads((ROOT/'examples/event.reset.json').read_text())
assert reset['generation']==1 and reset['sequence']==final['as_of']['sequence']+1
assert reset['sim_time_ms']==0  # clock moves back, sequence never does
heartbeat=json.loads((ROOT/'examples/heartbeat.json').read_text())
assert events[-1]['emitted_at']<=heartbeat['server_time']<=reset['emitted_at']
content_path=spec['paths']['/runs/{run_id}/media/{media_id}/content']
assert 'Content-Range' in content_path['get']['responses']['416']['headers']
assert 'Retry-After' in spec['components']['responses']['Error']['headers']
assert all('content' not in response for response in content_path['head']['responses'].values())
assert '206' not in content_path['head']['responses'] and '416' not in content_path['head']['responses']

# Verify complete SSE framing, JSON payloads and cursor identity; comments/retry are not events.
wire=(ROOT/'examples/stream.sse').read_text()
assert wire.endswith('\n\n')
frames=[]
for block in wire.split('\n\n'):
    if not block.strip():continue
    fields={}
    for line in block.splitlines():
        if line.startswith(':'):continue
        name,_,value=line.partition(':');fields.setdefault(name,[]).append(value.lstrip(' '))
    if 'data' not in fields:continue
    kind=fields['event'][0];data=json.loads('\n'.join(fields['data']))
    validate({'snapshot':'Snapshot','event':'Event','heartbeat':'Heartbeat'}[kind],data)
    if kind=='event':assert fields['id'][0]==data['cursor']
    if kind=='heartbeat':assert 'id' not in fields
    frames.append((kind,data))
assert frames[0][1]==initial
assert [data for kind,data in frames if kind=='event']==events

# Useful negative checks: invalid control, fake certainty and missing data cannot validate.
bad=copy.deepcopy(json.loads((ROOT/'examples/play.request.json').read_text()));bad['action']='set_speed';bad['speed']=7
assert not validator('Command').is_valid(bad)
bad=copy.deepcopy(final['occupancy'][0]);bad.update(basis='unknown',count=1)
assert not validator('Occupancy').is_valid(bad)
bad={'metric':'temperature','value':0,'unit':'degC','quality':'missing'}
assert not validator('MeasurementData').is_valid(bad)
bad={'scenario_id':'contract-demo','analysis_mode':'asr_live'}
assert not validator('CreateRun').is_valid(bad)

# All local Markdown targets in the package resolve; example URLs and credentials are clearly synthetic.
for file in ROOT.glob('*.md'):
    for target in re.findall(r'\]\(([^)]+)\)',file.read_text()):
        if '://' not in target and not target.startswith('#'):
            assert (file.parent/target.split('#')[0]).exists(),(file,target)
for file in ROOT.rglob('*'):
    if file.is_file():
        text=file.read_text()
        assert '-----BEGIN OPENSSH PRIVATE KEY-----' not in text
        assert not re.search(r'\bops_[A-Za-z0-9_-]{20,}',text)

result={'result':'PASS','contract_version':spec['info']['version'],'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'openapi':'3.1.1','schema_count':len(schemas),'path_count':len(spec['paths']),
    'json_examples':len(manifest['examples']),'event_examples':len(events),'sse_frames':len(frames),
    'semantic_checks':['evidence references','no future media','prerecorded transcript timing and provenance','raw data boundary','source-only people counts','unknown occupancy',
        'disconnected preserves last raw reading','reconnect deduplication','reset generation barrier','SSE cursor identity',
        'four invalid payloads rejected','package links'],
    'scope':'Contract and synthetic fixtures only; backend runtime and deployment not tested.'}
(ROOT/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
