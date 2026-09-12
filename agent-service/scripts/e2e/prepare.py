import json, pathlib, datetime, httpx
root=pathlib.Path(__file__).resolve().parents[3]
(root/'agent-service/work/e2e').mkdir(parents=True,exist_ok=True)
settings=dict(l.split('=',1) for l in (root/'platform/.env').read_text().splitlines() if '=' in l)
epoch=datetime.datetime(2026,9,12,10,tzinfo=datetime.timezone.utc)
source=json.loads((root/'data/demo/palisades-radio-demo/transcripts/decision-focus.en.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:8000',headers={'X-API-Key':settings['API_KEY']}) as c:
 devices=c.get('/devices'); devices.raise_for_status()
 found=[d for d in devices.json() if d['external_id']=='local-e2e-palisades']
 if not found:
  rows=[dict(device=dict(external_id='local-e2e-palisades',type='radio',name='Palisades local recorded replay'),metric_type='radio_audio',ts=(epoch+datetime.timedelta(seconds=s['end'])).isoformat(),transcript=s['text'].strip(),external_event_id=f"local-palisades-{s['id']}",payload={'audio_start_sim_time_ms':round(s['start']*1000),'audio_end_sim_time_ms':round(s['end']*1000)},provenance={'machine_generated':True,'human_verified':False,'source':'repository Palisades recording','replay':'local manual import'}) for s in source['segments']]
  r=c.post('/ingest/telemetry',json=rows); r.raise_for_status(); print(r.json())
  found=[d for d in c.get('/devices').json() if d['external_id']=='local-e2e-palisades']
scope=dict(session_id='local-palisades',generation=0,device_ids=[found[0]['id']],since=epoch.isoformat(),until=(epoch+datetime.timedelta(seconds=207)).isoformat(),epoch=epoch.isoformat(),poll_seconds=2)
(root/'agent-service/work/e2e/scope.json').write_text(json.dumps(scope))
print('Scope prepared for 43 recorded transcript segments')
