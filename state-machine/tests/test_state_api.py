"""Raw API contract, deterministic replay, access control, recovery and media boundaries."""
from pathlib import Path
import copy
import concurrent.futures
import hashlib
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import uuid

from state_api.core import Store, APIError
from state_api.http import Server, Service

ROOT=Path(__file__).resolve().parents[1]
BUNDLE = None
BASE_BUNDLE = None
FORBIDDEN={'analysis_mode','transcripts','context','conclusions','condition','severity','asr','assessment','Fire Alarm','report_type'}

class RawAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global BUNDLE, BASE_BUNDLE
        from scripts.build_demo_bundle import build as build_demo
        from scripts.import_repository_radio import build as import_radio
        cls.bundle_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.bundle_tmp.cleanup)
        BASE_BUNDLE = Path(cls.bundle_tmp.name) / 'base'
        BUNDLE = Path(cls.bundle_tmp.name) / 'palisades'
        build_demo(BASE_BUNDLE)
        import_radio(BASE_BUNDLE, BUNDLE)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=0.0
        self.db=Path(self.tmp.name)/'state.sqlite'
        self.store=Store(BUNDLE,self.db,monotonic=lambda:self.clock)
        self.config={'extra_origins':['https://ui.example.test'],'ticket_secret':'test-only-ticket-secret','public_url':'http://127.0.0.1/api/v1','tokens':[
            {'sha256':hashlib.sha256(b'test-control').hexdigest(),'owner':'team','scopes':['state:read','run:control'],'expires_at':time.time()+3600},
            {'sha256':hashlib.sha256(b'test-reader').hexdigest(),'owner':'team','scopes':['state:read'],'expires_at':time.time()+3600}]}
        self.service=Service(self.store,self.config,ROOT/'contracts/v0.2/openapi.json')
        self.server=Server(('127.0.0.1',0),self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.service.stop.set();self.server.shutdown();self.server.server_close();self.store.close();self.tmp.cleanup()

    def request(self,path,method='GET',body=None,token='test-control',headers=None):
        c=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        h={'Authorization':'Bearer '+token} if token else {}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {})
        c.request(method,path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();data=r.read();result=(r.status,dict(r.getheaders()),data);c.close();return result

    def create(self,scenario='degraded',speed=1):
        return self.store.create('team',str(uuid.uuid4()),{'scenario_id':scenario,'speed':speed})

    def command(self,run,action,**kwargs):
        return self.store.command('team',run['run_id'],{'command_id':str(uuid.uuid4()),'expected_generation':run['generation'],'action':action,**kwargs})

    def assert_raw(self,value):
        if isinstance(value,dict):
            self.assertFalse(FORBIDDEN.intersection(value))
            for child in value.values():self.assert_raw(child)
        elif isinstance(value,list):
            for child in value:self.assert_raw(child)

    def test_create_idempotency_and_request_scope(self):
        key=str(uuid.uuid4());body={'scenario_id':'normal','speed':1}
        first=self.store.create('team',key,body)
        self.assertEqual(first,self.store.create('team',key,{'speed':1,'scenario_id':'normal'}))
        with self.assertRaises(APIError) as caught:self.store.create('team',key,{'scenario_id':'degraded'})
        self.assertEqual(caught.exception.status,409)
        status,_,_=self.request('/api/v1/runs','POST',{'scenario_id':'normal','analysis_mode':'asr_live'},headers={'Idempotency-Key':str(uuid.uuid4())})
        self.assertEqual(status,422)

    def test_pause_reset_generation_and_command_dedup(self):
        run=self.create();self.command(run,'play');self.clock=4;self.store.tick()
        self.command(run,'pause');self.clock=10;self.store.tick()
        self.assertEqual(self.store.get(run['run_id'],'team')['snapshot']['run']['sim_time_ms'],4000)
        cmd={'command_id':str(uuid.uuid4()),'expected_generation':0,'action':'reset'}
        result=self.store.command('team',run['run_id'],cmd)
        self.assertEqual(result,self.store.command('team',run['run_id'],cmd))
        self.assertEqual(result['generation'],1)
        with self.assertRaises(APIError):self.command(run,'play')
        self.assertEqual(self.store.get(run['run_id'],'team')['snapshot']['run']['sim_time_ms'],0)

    def test_raw_replay_suppression_missing_and_source_references(self):
        run=self.create();self.command(run,'seek',position_ms=450000)
        r=self.store.get(run['run_id'],'team');snap=r['snapshot'];self.assert_raw(snap)
        self.assertIsNone(snap['occupancy'][0]['count'])
        devices={d['device_id']:d for d in snap['devices']}
        self.assertEqual(devices['SMK-SRV']['availability'],'disconnected')
        self.assertEqual(devices['IOT-VOC']['availability'],'stale')
        self.assertIsNotNone(devices['SMK-SRV']['readings'][0]['value'])
        c=snap['system']['events'];self.assertGreater(c['suppressed'],0)
        self.assertEqual(c['processed'],c['observed']+c['suppressed']+c['transport_controls'])
        for d in snap['devices']:
            if d['last_observation_id']:self.assert_raw(self.store.observation(r,d['last_observation_id']))

    def test_replay_observations_equal_at_different_speeds(self):
        normalized=[]
        for speed in [1,10,60]:
            run=self.create(speed=speed);self.command(run,'play')
            self.clock+=660/speed;self.store.tick()
            r=self.store.get(run['run_id'],'team');self.assertEqual(r['snapshot']['run']['status'],'completed')
            rows=self.store.db.execute('SELECT value FROM observations WHERE run=? ORDER BY received,observed,id',(run['run_id'],)).fetchall()
            observations=[]
            for row in rows:
                d=json.loads(row[0]);self.assert_raw(d)
                for key in ['received_at','run_id']:d.pop(key)
                observations.append(d)
            normalized.append(observations)
        self.assertEqual(normalized[0],normalized[1]);self.assertEqual(normalized[1],normalized[2])

    def test_restart_pauses_and_keeps_journal_and_dedup(self):
        run=self.create();cmd={'command_id':str(uuid.uuid4()),'expected_generation':0,'action':'play'}
        result=self.store.command('team',run['run_id'],cmd);self.clock=2;self.store.tick()
        before=self.store.get(run['run_id'],'team')['snapshot']['as_of']['sequence']
        self.store.close();self.store=Store(BUNDLE,self.db,monotonic=lambda:self.clock);self.service.store=self.store
        snap=self.store.get(run['run_id'],'team')['snapshot']
        self.assertEqual(snap['run']['status'],'paused');self.assertEqual(snap['run']['sim_time_ms'],2000)
        self.assertGreater(snap['as_of']['sequence'],before)
        self.assertEqual(self.store.command('team',run['run_id'],cmd),result)

    def test_http_auth_cors_and_owner_isolation(self):
        self.assertEqual(self.request('/api/v1/health',token=None)[0],200)
        self.assertEqual(self.request('/api/v1/scenarios',token=None)[0],401)
        self.assertEqual(self.request('/api/v1/runs','POST',{'scenario_id':'normal'},token='test-reader')[0],403)
        for origin in ['http://localhost:3000','http://127.0.0.1:5173','https://ui.example.test']:
            status,headers,_=self.request('/api/v1/runs','OPTIONS',token=None,headers={'Origin':origin})
            self.assertEqual(status,204);self.assertEqual(headers['Access-Control-Allow-Origin'],origin)
        self.assertEqual(self.request('/api/v1/scenarios',headers={'Origin':'https://ui.example.test.attacker.example'})[0],403)
        run=self.create()
        with self.assertRaises(APIError) as caught:self.store.get(run['run_id'],'another-team')
        self.assertEqual(caught.exception.status,404)

    def test_media_no_future_range_refresh_and_generation(self):
        run=self.create();base='/api/v1/runs/'+run['run_id']
        mid='radio-a-0000'
        self.assertEqual(self.request(base+'/media/'+mid+'?generation=0')[0],404)
        self.command(run,'seek',position_ms=5000)
        status,_,data=self.request(base+'/media/'+mid+'?generation=1');self.assertEqual(status,200)
        metadata=json.loads(data);self.assert_raw(metadata)
        content=metadata['content_url'].removeprefix('http://127.0.0.1')
        status,headers,data=self.request(content,token=None,headers={'Range':'bytes=0-31'})
        self.assertEqual(status,206);self.assertEqual(len(data),32);self.assertEqual(data[:4],b'RIFF')
        self.assertTrue(headers['Content-Range'].startswith('bytes 0-31/'))
        status,headers,data=self.request(content,'HEAD',token=None,headers={'Range':'bytes=0-31'})
        self.assertEqual(status,200);self.assertEqual(data,b'')
        self.assertEqual(self.request(content,token=None,headers={'Range':'bytes=999999999-'})[0],416)
        self.assertEqual(self.request(content,token=None,headers={'Range':'bytes=0-1,4-5'})[0],416)
        self.assertEqual(self.request(content,token=None,headers={'Range':'bytes=0-1','If-Range':'"different"'})[0],200)
        self.command({'run_id':run['run_id'],'generation':1},'reset')
        self.assertEqual(self.request(content,token=None)[0],409)

    def test_history_pagination_freezes_highwater(self):
        run=self.create();self.command(run,'play');self.clock=3;self.store.tick()
        path='/api/v1/runs/'+run['run_id']+'/observations?generation=0&limit=3'
        status,_,data=self.request(path);self.assertEqual(status,200);first=json.loads(data)
        self.clock=8;self.store.tick()
        items=list(first['items']);cursor=first['next_cursor']
        while cursor:
            status,_,data=self.request(path+'&cursor='+cursor);self.assertEqual(status,200)
            page=json.loads(data);self.assertEqual(page['as_of_sequence'],first['as_of_sequence'])
            items+=page['items'];cursor=page['next_cursor']
        self.assertEqual(len(items),len({x['evidence_id'] for x in items}))
        self.assertTrue(all(x['received_sim_time_ms']<=3000 for x in items))

    def test_sse_snapshot_reconnect_and_live_command(self):
        run=self.create();base='/api/v1/runs/'+run['run_id']
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        conn.request('GET',base+'/stream',headers={'Authorization':'Bearer test-reader'})
        response=conn.getresponse();self.assertEqual(response.status,200)
        def next_frame():
            lines=[]
            while True:
                line=response.fp.readline().decode().rstrip('\r\n')
                if not line:
                    if any(l.startswith('data:') for l in lines):return lines
                    lines=[]
                else:lines.append(line)
        frame=next_frame();self.assertIn('event: snapshot',frame)
        snap=json.loads(next(l[6:] for l in frame if l.startswith('data: ')))
        self.command(run,'play');frame=next_frame();self.assertIn('event: event',frame)
        event=json.loads(next(l[6:] for l in frame if l.startswith('data: ')))
        self.assertEqual(event['sequence'],snap['as_of']['sequence']+1)
        conn.close()
        self.clock=3;self.store.tick()
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        conn.request('GET',base+'/stream?after='+event['cursor'],headers={'Authorization':'Bearer test-reader'})
        response=conn.getresponse();frame=next_frame()
        self.assertIn('event: event',frame)
        resumed=json.loads(next(l[6:] for l in frame if l.startswith('data: ')))
        self.assertEqual(resumed['sequence'],event['sequence']+1);conn.close()

    def test_continuous_media_uses_one_connection_and_waits_for_play(self):
        run=self.create();base='/api/v1/runs/'+run['run_id']
        status,_,data=self.request(base+'/media-streams');self.assertEqual(status,200)
        streams=json.loads(data)['items'];self.assertEqual(len(streams),4)
        item=next(s for s in streams if s['stream_id']=='CAM-EXT')
        source=self.store.live_streams['CAM-EXT'];conn=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        conn.request('GET',item['content_url'].removeprefix('http://127.0.0.1'))
        response=conn.getresponse();self.assertEqual(response.status,200)
        init=response.read(source['init_length']);self.assertIn(b'ftyp',init);self.assertIn(b'moov',init)
        self.assertNotIn(b'mdat',init)
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            waiting=pool.submit(response.read,source['fragments'][0]['length'])
            time.sleep(.15);self.assertFalse(waiting.done(),'Future media arrived before Play')
            self.command(run,'play');self.clock=3;self.store.tick()
            fragment=waiting.result(timeout=3);self.assertIn(b'moof',fragment);self.assertIn(b'mdat',fragment)
        # Reset ends this stream; its old connection cannot transmit another generation.
        self.command(run,'reset');self.assertEqual(response.read(),b'');conn.close()

    def palisades(self, variant='focus', speed=1):
        return self.create('palisades-'+variant, speed)

    def transcript_rows(self, run):
        r=self.store.get(run['run_id'],'team')
        rows=self.store.db.execute('SELECT value FROM observations WHERE run=? AND gen=? ORDER BY received,observed,id',
            (run['run_id'],r['snapshot']['run']['generation'])).fetchall()
        return [item for row in rows if (item:=json.loads(row[0]))['kind']=='radio_transcript']

    def test_palisades_text_time_pause_reset_and_source_fidelity(self):
        run=self.palisades();r=self.store.get(run['run_id'],'team')
        first=next(e for e in self.store.sources['palisades-focus']['events'] if e['kind']=='radio_transcript')
        self.assertIsNone(r['snapshot']['radio']['channels'][0]['latest_transcript'])
        self.command(run,'play');self.clock=(first['received_sim_time_ms']-1)/1000;self.store.tick()
        self.assertEqual(self.transcript_rows(run),[])
        self.command(run,'pause');self.clock+=100;self.store.tick()
        self.assertEqual(self.transcript_rows(run),[])
        self.command(run,'play');self.clock+=.01;self.store.tick()
        row=self.transcript_rows(run)[0]
        source=json.loads((ROOT.parent/'data/demo/palisades-radio-demo/transcripts/decision-focus.en.json').read_text())
        self.assertEqual(row['data']['text'],source['segments'][0]['text'])
        self.assertEqual(row['data']['delivery'],'prerecorded')
        self.assertFalse(row['data']['human_verified'])
        d=next(d for d in r['snapshot']['devices'] if d['kind']=='radio_channel')
        self.assertEqual(self.store.observation(r,d['last_observation_id'])['kind'],'radio_audio')
        self.command(run,'reset')
        self.assertEqual(self.transcript_rows(run),[])
        self.assertIsNone(r['snapshot']['radio']['channels'][0]['latest_transcript'])

    def test_palisades_focus_speed_equivalence_and_schema(self):
        from jsonschema import Draft202012Validator, FormatChecker
        schema={'$ref':'#/components/schemas/Observation','components':self.service.spec['components']}
        validate=Draft202012Validator(schema,format_checker=FormatChecker()).validate
        for variant,count,duration,offset in [('focus',43,206000,292000)]:
            results=[]
            for speed in [1,10,60]:
                run=self.palisades(variant,speed);self.command(run,'play')
                self.clock+=duration/(1000*speed)+.001;self.store.tick()
                rows=self.transcript_rows(run);self.assertEqual(len(rows),count)
                source=json.loads((ROOT.parent/'data/demo/palisades-radio-demo/transcripts'/
                    ('full-10min.en.json' if variant=='full' else 'decision-focus.en.json')).read_text())
                self.assertEqual([r['data']['text'] for r in rows],[s['text'] for s in source['segments']])
                for row in rows:
                    validate(row)
                    self.assertEqual(row['data']['full_recording_offset_ms'],offset)
                    self.assertLessEqual(row['data']['audio_end_sim_time_ms'],row['received_sim_time_ms'])
                    self.assertLessEqual(row['received_sim_time_ms'],duration)
                results.append([r['data'] for r in rows])
            self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2])

    def test_palisades_stream_isolation_and_complete_eof(self):
        run=self.palisades('focus');base='/api/v1/runs/'+run['run_id']
        status,_,body=self.request(base+'/media-streams');self.assertEqual(status,200)
        streams=json.loads(body)['items'];self.assertEqual({s['stream_id'] for s in streams},{'CAM-EXT','CAM-SRV','RADIO-PALISADES-FOCUS'})
        self.assertEqual(self.request(base+'/media-streams/RADIO-PALISADES-FULL/content?generation=0')[0],404)
        self.assertEqual(self.request(base+'/media-streams/RADIO-A/content?generation=0')[0],404)
        result=self.command(run,'seek',position_ms=206000)
        status,_,body=self.request(base+'/media-streams/RADIO-PALISADES-FOCUS/content?generation='+str(result['generation']))
        source=self.store.live_streams['RADIO-PALISADES-FOCUS']
        self.assertEqual(status,200)
        expected=(BUNDLE/source['file']).read_bytes()
        wanted=expected[:source['init_length']]+b''.join(expected[f['offset']:f['offset']+f['length']] for f in source['fragments'])
        self.assertEqual(body,wanted)
        self.assertEqual(source['fragments'][-1]['end_ms'],206000)

    def test_palisades_sse_reconnect_and_restart_retains_text(self):
        run=self.palisades();self.command(run,'play');self.clock=21;self.store.tick()
        r=self.store.get(run['run_id'],'team');latest=copy.deepcopy(r['snapshot']['radio']['channels'][0]['latest_transcript'])
        events=self.store.journal(run['run_id'],'team',0,10000)
        texts=[e for e in events if e['kind']=='observation.created' and e['data']['kind']=='radio_transcript']
        self.assertEqual(len(texts),2)
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        conn.request('GET','/api/v1/runs/'+run['run_id']+'/stream',headers={'Authorization':'Bearer test-reader','Last-Event-ID':texts[0]['cursor']})
        response=conn.getresponse();self.assertEqual(response.status,200)
        seen=[];lines=[]
        while len(seen)<1:
            line=response.readline().decode().strip()
            if line.startswith('data: '):lines.append(json.loads(line[6:]))
            if not line:
                for event in lines:
                    if event.get('kind')=='observation.created' and event['data']['kind']=='radio_transcript':seen.append(event)
                lines=[]
        self.assertEqual(seen[0]['event_id'],texts[1]['event_id']);conn.close();response.close()
        self.store.close();self.store=Store(BUNDLE,self.db,monotonic=lambda:self.clock);self.service.store=self.store
        snap=self.store.get(run['run_id'],'team')['snapshot']
        self.assertEqual(snap['radio']['channels'][0]['latest_transcript'],latest)
        self.assertEqual(snap['run']['status'],'paused')
        self.assertEqual(len(self.transcript_rows(run)),2)

    def test_appending_palisades_preserves_existing_scenarios(self):
        self.palisades()
        original=BASE_BUNDLE
        for name in ['normal','escalation','degraded']:
            self.assertEqual((BUNDLE/(name+'.json')).read_bytes(),(original/(name+'.json')).read_bytes())
        for name,value in json.loads((original/'live-streams.json').read_text()).items():
            self.assertEqual(self.store.live_streams[name],value)

    def test_runtime_payloads_match_openapi(self):
        from jsonschema import Draft202012Validator,FormatChecker
        spec=self.service.spec
        def validate(name,value):
            Draft202012Validator({'$ref':'#/components/schemas/'+name,'components':spec['components']},format_checker=FormatChecker()).validate(value)
        run=self.create();validate('Run',run)
        self.command(run,'play');self.clock=5;self.store.tick()
        base='/api/v1/runs/'+run['run_id']
        for path,schema in [('/api/v1/health','Health'),('/api/v1/scenarios','ScenarioList'),('/api/v1/capabilities','Capabilities'),
                (base,'Run'),(base+'/snapshot','Snapshot'),(base+'/devices','DeviceList'),(base+'/cameras','CameraList'),
                (base+'/access','AccessList'),(base+'/occupancy','OccupancyList'),(base+'/system','SystemHealth'),
                (base+'/media-streams','MediaStreamList'),(base+'/observations?generation=0','ObservationPage'),
                (base+'/media/radio-a-0000?generation=0','Media'),(base+'/devices/TMP-SRV?generation=0','DeviceState')]:
            status,_,data=self.request(path);self.assertEqual(status,200,path);validate(schema,json.loads(data))
        for event in self.store.journal(run['run_id'],'team',0,1000):validate('Event',event)

if __name__=='__main__':unittest.main()
