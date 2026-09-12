import httpx,time,json,pathlib,uuid
root=pathlib.Path(__file__).resolve().parents[2]/'work/e2e'
ctx={'demo_context_id':'local-palisades','generation':0,'subject_id':'platform'}
with httpx.Client(base_url='http://127.0.0.1:8011',timeout=20) as c:
 health=c.get('/health');health.raise_for_status(); print('Health:',health.json())
 r=c.post('/sessions/local-palisades/0/clock',json={'time_ms':206000});r.raise_for_status()
 r=c.post('/agent/v1/questions',json={'context':ctx,'client_request_id':str(uuid.uuid4()),'question':'Was the channel assignment acknowledged?','language':'en'});r.raise_for_status();answer=r.json()
 for i in range(120):
  r=c.get('/agent/v1/questions/'+answer['request_id'],params=ctx);r.raise_for_status();answer=r.json()
  if answer['status'] not in ('queued','running'):break
  time.sleep(.3)
 state=c.get('/agent/v1/state',params=ctx);state.raise_for_status()
 evidence=[]
 for claim in answer.get('claims',[]):
  for eid in claim.get('evidence_ids',[]):
   r=c.get('/agent/v1/evidence/'+eid,params=ctx);r.raise_for_status();evidence.append(r.json())
 report={'health':health.json(),'answer':answer,'state':state.json(),'evidence':evidence,'mode':health.json()['engine']}
 (root/'result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
 assert health.json()['platform_connected'], 'Platform importer is disconnected'
 assert answer['status'] not in ('queued','running','error'), answer.get('error')
 print('Answer status:',answer['status'],'claims:',len(answer.get('claims',[])),'evidence:',len(evidence),'cards:',len(state.json().get('cards',[])))
 print('Answer fields:',list(answer));print('Evidence media:', [e.get('audio') for e in evidence[:1]])
