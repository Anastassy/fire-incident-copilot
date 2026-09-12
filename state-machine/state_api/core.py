"""Deterministic raw replay and a durable SQLite event journal."""
from pathlib import Path
import copy
import datetime as dt
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid

VERSION = '0.2'

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')

def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False, sort_keys=True)

class APIError(Exception):
    def __init__(self, status, code, message, **details):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details

class Store:
    def __init__(self, bundle, database, monotonic=time.monotonic, max_runs=16):
        self.bundle = Path(bundle).resolve()
        self.monotonic = monotonic
        self.max_runs = max_runs
        self.lock = threading.RLock()
        self.catalog = json.loads((self.bundle / 'catalog.json').read_text())
        self.sources = {s['scenario_id']: json.loads((self.bundle / (s['scenario_id']+'.json')).read_text()) for s in self.catalog}
        self.media = json.loads((self.bundle / 'media.json').read_text())
        self.live_streams = json.loads((self.bundle / 'live-streams.json').read_text())
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, owner TEXT, saved TEXT);
            CREATE TABLE IF NOT EXISTS events(run TEXT, seq INTEGER, value TEXT, PRIMARY KEY(run,seq));
            CREATE TABLE IF NOT EXISTS observations(run TEXT, gen INTEGER, id TEXT, seq INTEGER, received INTEGER, observed INTEGER, device TEXT, value TEXT, PRIMARY KEY(run,gen,id));
            CREATE TABLE IF NOT EXISTS commands(run TEXT, id TEXT, request TEXT, response TEXT, PRIMARY KEY(run,id));
            CREATE TABLE IF NOT EXISTS creations(owner TEXT, id TEXT, request TEXT, run TEXT, response TEXT, PRIMARY KEY(owner,id));
            CREATE INDEX IF NOT EXISTS observations_page ON observations(run,gen,received,observed,id);
        ''')
        self.runs = {}
        with self.db:
            for run_id, owner, saved in self.db.execute('SELECT id,owner,saved FROM runs').fetchall():
                r = json.loads(saved)
                public=r['snapshot']['run']
                if dt.datetime.fromisoformat(public['expires_at'].replace('Z','+00:00'))>dt.datetime.now(dt.timezone.utc) and public['scenario_version']!=self.sources[public['scenario_id']]['scenario']['scenario_version']:
                    raise RuntimeError('Active runs require their original immutable scenario bundle; restore previous release')
                r['owner'] = owner
                r['anchor'] = self.monotonic()
                self.runs[run_id] = r
                if r['snapshot']['run']['status'] == 'playing':
                    r['snapshot']['run']['status'] = 'paused'
                    self.emit(r, 'run.updated', r['snapshot']['run'])
                    self.save(r)

    def save(self, r):
        saved = {k:v for k,v in r.items() if k not in ['owner','anchor']}
        self.db.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?)', (r['snapshot']['run']['run_id'], r['owner'], encoded(saved)))

    def get(self, run_id, owner, generation=None):
        r = self.runs.get(run_id)
        if r is None or r['owner'] != owner: raise APIError(404, 'NOT_FOUND', 'Запуск не найден')
        public = r['snapshot']['run']
        if dt.datetime.fromisoformat(public['expires_at'].replace('Z','+00:00')) <= dt.datetime.now(dt.timezone.utc):
            raise APIError(410, 'RUN_EXPIRED', 'Срок запуска истёк')
        if generation is not None and generation != public['generation']:
            raise APIError(409, 'GENERATION_MISMATCH', 'Поколение изменилось', current_generation=public['generation'])
        return r

    def empty(self, public):
        src = self.sources[public['scenario_id']]
        devices=[]
        for d in src['devices']:
            value={k:d[k] for k in ['device_id','name','kind','building_id','room_id','floor_id','position_m']}
            value.update(availability='missing', last_observation_id=None, last_observed_sim_time_ms=None, readings=[])
            if d['metric']:
                value['readings']=[{'metric':d['metric'],'value':None,'unit':d['unit'],'availability':'missing',
                    'observation_id':None,'observed_sim_time_ms':None,'age_ms':None,'stale_after_ms':d['stale_after_ms']}]
            devices.append(value)
        occupancy={'scope_id':src['scenario']['building_id'],'scope_type':'building','count':None,'basis':'unknown',
            'availability':'missing','as_of_sim_time_ms':0,'observation_id':None,'limitations':['Прямой источник подсчёта людей отсутствует.']}
        access={'scope_id':src['scenario']['building_id'],'window_start_sim_time_ms':0,'window_end_sim_time_ms':0,
            'confirmed_entries':None,'confirmed_exits':None,'availability':'missing','evidence_ids':[],
            'limitations':['Источник пропусков не подтверждает проход или присутствие человека.']}
        transcript_devices = {d['device_id'] for d in src['devices'] if d.get('transcript_delivery') == 'prerecorded'}
        return {'schema_version':VERSION,'run':public,'as_of':{'sequence':0,'cursor':public['run_id']+':0'},
            'devices':devices,'rooms':[{**room,'unavailable_device_ids':list(room['device_ids'])} for room in src['rooms']],
            'cameras':[{'camera_id':d['device_id'],'device_id':d['device_id'],'room_id':d['room_id'],'availability':'missing',
                'latest_video_media_id':None,'latest_frame_media_id':None,'playback_delay_ms':2100} for d in devices if d['kind']=='camera'],
            'access':[access],'occupancy':[occupancy],
            'radio':{'channels':[{'channel_id':d['device_id'],'device_id':d['device_id'],'name':d['name'],
                'availability':'missing','latest_audio_media_id':None,
                **({'transcript_delivery':'prerecorded','latest_transcript':None} if d['device_id'] in transcript_devices else {})} for d in devices if d['kind']=='radio_channel']},
            'system':{'status':'healthy','clock':{'sim_time_ms':0,'wall_time':utc(),'processing_lag_ms':0},
                'events':{'processed':0,'observed':0,'suppressed':0,'transport_controls':0,'dropped':0},
                'blender':{'status':'not_connected','last_ack_at':None,'sim_lag_ms':None},'errors':[]}}

    def create(self, owner, key, body):
        self.valid_uuid(key)
        if set(body)-{'scenario_id','speed'} or 'scenario_id' not in body: raise APIError(422,'INVALID_COMMAND','Поля создания запуска не соответствуют контракту')
        if body['scenario_id'] not in self.sources: raise APIError(422,'FEATURE_UNAVAILABLE','Неизвестный сценарий')
        speed=body.get('speed',1)
        if type(speed) not in [int,float] or speed not in [1,10,60]: raise APIError(422,'INVALID_COMMAND','Недопустимая скорость')
        request=encoded(body)
        with self.lock, self.db:
            prior=self.db.execute('SELECT request,run,response FROM creations WHERE owner=? AND id=?',(owner,key)).fetchone()
            if prior:
                if prior[0]!=request: raise APIError(409,'IDEMPOTENCY_CONFLICT','ID уже связан с другим запросом')
                self.get(prior[1],owner)
                return json.loads(prior[2])
            active=sum(dt.datetime.fromisoformat(r['snapshot']['run']['expires_at'].replace('Z','+00:00'))>dt.datetime.now(dt.timezone.utc) for r in self.runs.values())
            if active>=self.max_runs: raise APIError(429,'RATE_LIMITED','Достигнут лимит одновременных запусков',retry_after_ms=60000)
            run_id=str(uuid.uuid4());base='/api/v1/runs/'+run_id
            scenario=self.sources[body['scenario_id']]['scenario']
            public={'run_id':run_id,'scenario_id':body['scenario_id'],'scenario_version':scenario['scenario_version'],
                'generation':0,'status':'paused','sim_time_ms':0,'duration_ms':scenario['duration_ms'],'speed':speed,
                'created_at':utc(),'expires_at':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=24)).isoformat().replace('+00:00','Z'),
                'links':{'snapshot':base+'/snapshot','stream':base+'/stream','commands':base+'/commands'}}
            r={'owner':owner,'snapshot':self.empty(public),'position':0.0,'index':0,'transport':{},'last_data':{},'published_media':[], 'anchor':self.monotonic()}
            self.runs[run_id]=r
            self.advance(r,0,silent=True)
            self.save(r)
            response=encoded(public)
            self.db.execute('INSERT INTO creations VALUES(?,?,?,?,?)',(owner,key,request,run_id,response))
            return copy.deepcopy(public)

    @staticmethod
    def valid_uuid(value):
        try:
            if not isinstance(value,str) or str(uuid.UUID(value)) != value.lower(): raise ValueError()
        except (ValueError,AttributeError,TypeError): raise APIError(400,'INVALID_REQUEST','Требуется UUID идентификатор запроса')

    def emit(self, r, kind, data, silent=False):
        if silent: return
        snap=r['snapshot'];run=snap['run'];seq=snap['as_of']['sequence']+1
        cursor=run['run_id']+':'+str(seq)
        event={'schema_version':VERSION,'event_id':str(uuid.uuid4()),'run_id':run['run_id'],'generation':run['generation'],
            'sequence':seq,'cursor':cursor,'kind':kind,'sim_time_ms':run['sim_time_ms'],'emitted_at':utc(),'data':data}
        self.db.execute('INSERT INTO events VALUES(?,?,?)',(run['run_id'],seq,encoded(event)))
        snap['as_of']={'sequence':seq,'cursor':cursor}

    def observe(self, r, e, silent):
        snap=r['snapshot'];run=snap['run'];c=snap['system']['events'];device=e['device_id'];k=e['kind']
        c['processed']+=1
        if k=='transport':
            r['transport'][device]=e['data']['mode'];c['transport_controls']+=1;return
        if k=='connectivity':r['transport'][device]='online' if e['data']['connected'] else 'offline'
        elif r['transport'].get(device,'online')!='online':c['suppressed']+=1;return
        c['observed']+=1
        oid=f'g{run["generation"]}-{e["source_event_id"]}'
        observation={key:copy.deepcopy(e[key]) for key in ['kind','device_id','room_id','observed_sim_time_ms','received_sim_time_ms','provenance','data']}
        observation.update(evidence_id=oid,run_id=run['run_id'],generation=run['generation'],received_at=utc())
        self.emit(r,'observation.created',observation,silent)
        self.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',
            (run['run_id'],run['generation'],oid,snap['as_of']['sequence'],e['received_sim_time_ms'],e['observed_sim_time_ms'],device,encoded(observation)))
        if k=='radio_transcript':
            # Supplied text is replayed evidence; it must not refresh the audio device.
            channel=next(c for c in snap['radio']['channels'] if c['device_id']==device)
            channel['latest_transcript']=copy.deepcopy(observation)
            self.emit(r,'radio.channel.updated',channel,silent)
            return
        d=next(d for d in snap['devices'] if d['device_id']==device)
        d['last_observation_id']=oid;d['last_observed_sim_time_ms']=e['observed_sim_time_ms']
        if k=='connectivity':
            availability='stale' if e['data']['connected'] and device in r['last_data'] else 'missing' if e['data']['connected'] else 'disconnected'
            d['availability']=availability
            for reading in d['readings']:reading['availability']=availability
        else:
            r['last_data'][device]=e['observed_sim_time_ms']
            d['availability']={'valid':'fresh','missing':'missing','invalid':'invalid'}.get(e['data'].get('quality'),'fresh')
        if k=='measurement':
            reading={'metric':e['data']['metric'],'value':e['data']['value'],'unit':e['data']['unit'],
                'availability':d['availability'],'observation_id':oid,'observed_sim_time_ms':e['observed_sim_time_ms'],
                'age_ms':run['sim_time_ms']-e['observed_sim_time_ms'],
                'stale_after_ms':next(v['stale_after_ms'] for v in self.sources[run['scenario_id']]['devices'] if v['device_id']==device)}
            d['readings']=[reading]
        self.refresh_device(r,d,silent,force=True)
        if k in ['camera','radio_audio']:
            mid=e['data']['media_id']
            if mid not in r['published_media']:r['published_media'].append(mid)
            if k=='camera':
                camera=next(c for c in snap['cameras'] if c['device_id']==device)
                camera['latest_video_media_id' if e['data']['media_kind']=='video' else 'latest_frame_media_id']=mid
                self.emit(r,'camera.updated',camera,silent)
            else:
                channel=next(c for c in snap['radio']['channels'] if c['device_id']==device)
                channel['latest_audio_media_id']=mid
                self.emit(r,'radio.channel.updated',channel,silent)
        elif k=='access':
            a=snap['access'][0];a['availability']=d['availability'];a['window_end_sim_time_ms']=run['sim_time_ms']+1
            a['evidence_ids'].append(oid)
            self.emit(r,'access.updated',a,silent)
        elif k=='people_count':
            value=e['data'];o={'scope_id':value['scope_id'],'scope_type':value['scope_type'],'count':value['count'],
                'basis':'source_count','availability':d['availability'],'as_of_sim_time_ms':run['sim_time_ms'],
                'observation_id':oid,'limitations':['Значение источника, без подтверждения присутствия этим сервисом.']}
            snap['occupancy']=[old for old in snap['occupancy'] if old['scope_id']!=o['scope_id']]+[o]
            self.emit(r,'occupancy.updated',o,silent)

    def refresh_device(self,r,d,silent,force=False):
        snap=r['snapshot'];now=snap['run']['sim_time_ms'];device=d['device_id']
        old=d['availability']
        config=next(v for v in self.sources[snap['run']['scenario_id']]['devices'] if v['device_id']==device)
        if old=='fresh' and now-r['last_data'].get(device,now)>=config['stale_after_ms']:d['availability']='stale'
        for reading in d['readings']:
            if reading['observed_sim_time_ms'] is not None:reading['age_ms']=now-reading['observed_sim_time_ms']
            if reading['availability']=='fresh' and reading['age_ms']>=reading['stale_after_ms']:reading['availability']='stale'
        if force or old!=d['availability']:
            self.emit(r,'device.updated',d,silent)
        for collection,kind in [(snap['cameras'],'camera.updated'),(snap['radio']['channels'],'radio.channel.updated')]:
            for entity in collection:
                if entity['device_id']==device and entity['availability']!=d['availability']:
                    entity['availability']=d['availability'];self.emit(r,kind,entity,silent)
        if d['kind']=='access_reader':
            for a in snap['access']:
                if a['availability']!=d['availability']:
                    a['availability']=d['availability'];self.emit(r,'access.updated',a,silent)

    def refresh(self,r,silent):
        snap=r['snapshot']
        for device in snap['devices']:self.refresh_device(r,device,silent)
        unavailable={d['device_id'] for d in snap['devices'] if d['availability']!='fresh'}
        for room in snap['rooms']:
            new=[d for d in room['device_ids'] if d in unavailable]
            if new!=room['unavailable_device_ids']:
                room['unavailable_device_ids']=new;self.emit(r,'room.updated',room,silent)
        health=snap['system']
        health['status']='degraded' if any(d['availability'] in ['stale','invalid','disconnected'] for d in snap['devices']) else 'healthy'
        health['clock'].update(sim_time_ms=snap['run']['sim_time_ms'],wall_time=utc())

    def advance(self,r,target,silent=False):
        snap=r['snapshot'];run=snap['run'];source=self.sources[run['scenario_id']];events=source['events']
        while True:
            at=events[r['index']]['received_sim_time_ms'] if r['index']<len(events) else math.inf
            expiries=[r['last_data'][d['device_id']]+config['stale_after_ms'] for d,config in zip(snap['devices'],source['devices']) if d['availability']=='fresh']
            nxt=min([at]+expiries)
            if nxt>target:break
            run['sim_time_ms']=int(nxt)
            self.refresh(r,silent)
            if at==nxt:
                self.observe(r,events[r['index']],silent);r['index']+=1
        run['sim_time_ms']=int(target);r['position']=float(target)
        self.refresh(r,silent)
        if target>=run['duration_ms']:run['status']='completed'

    def tick_one(self,r):
        current=self.monotonic();delta=max(0,current-r['anchor']);r['anchor']=current
        run=r['snapshot']['run']
        if run['status']!='playing':return
        self.advance(r,min(run['duration_ms'],r['position']+delta*1000*run['speed']))
        self.emit(r,'run.updated',run)
        self.emit(r,'system.updated',r['snapshot']['system'])
        self.save(r)

    def tick(self):
        with self.lock,self.db:
            for r in self.runs.values():
                if dt.datetime.fromisoformat(r['snapshot']['run']['expires_at'].replace('Z','+00:00'))>dt.datetime.now(dt.timezone.utc):self.tick_one(r)

    def command(self,owner,run_id,body):
        self.valid_uuid(body.get('command_id'))
        action=body.get('action');fields={'command_id','expected_generation','action'}
        if action=='set_speed':fields.add('speed')
        if action=='seek':fields.add('position_ms')
        if set(body)!=fields or action not in ['play','pause','reset','seek','set_speed'] or type(body['expected_generation']) is not int or body['expected_generation']<0:
            raise APIError(422,'INVALID_COMMAND','Неверная команда')
        request=encoded(body)
        with self.lock,self.db:
            r=self.get(run_id,owner)
            prior=self.db.execute('SELECT request,response FROM commands WHERE run=? AND id=?',(run_id,body['command_id'])).fetchone()
            if prior:
                if prior[0]!=request:raise APIError(409,'IDEMPOTENCY_CONFLICT','Повтор ID с другим телом')
                return json.loads(prior[1])
            self.get(run_id,owner,body['expected_generation'])
            run=r['snapshot']['run']
            if action=='set_speed' and (type(body['speed']) not in [int,float] or body['speed'] not in [1,10,60]):raise APIError(422,'INVALID_COMMAND','Недопустимая скорость')
            if action=='seek' and (type(body['position_ms']) is not int or not 0<=body['position_ms']<=run['duration_ms']):raise APIError(422,'INVALID_COMMAND','Позиция вне сценария')
            if action=='play' and run['sim_time_ms']>=run['duration_ms']:raise APIError(409,'RUN_COMPLETED','Для повтора нужен reset')
            if run['status']=='error' and action not in ['reset','seek']:raise APIError(409,'RUN_ERROR','Нужен reset/seek')
            self.tick_one(r)
            if action=='play' and run['sim_time_ms']>=run['duration_ms']:
                # Time can reach the end while the command is being received.
                # Commit the completed clock before returning its conflict response.
                self.db.commit()
                raise APIError(409,'RUN_COMPLETED','Для повтора нужен reset')
            if action in ['reset','seek']:
                previous=r['snapshot']['as_of'];run['generation']+=1;run['sim_time_ms']=0;run['status']='paused'
                if action=='reset':run['speed']=1
                r['snapshot']=self.empty(run);r['snapshot']['as_of']=previous
                r.update(index=0,transport={},last_data={},published_media=[],position=0.0)
                self.emit(r,'stream.reset',{'reason':action,'snapshot_url':run['links']['snapshot']})
                self.advance(r,body.get('position_ms',0),silent=True)
                run['status']='paused'
            elif action=='play':run['status']='playing'
            elif action=='pause':run['status']='paused'
            elif action=='set_speed':run['speed']=body['speed']
            r['anchor']=self.monotonic()
            self.emit(r,'run.updated',run)
            result={'command_id':body['command_id'],'run_id':run_id,'generation':run['generation'],
                'applied_sequence':r['snapshot']['as_of']['sequence'],'status':'applied','run':copy.deepcopy(run)}
            self.db.execute('INSERT INTO commands VALUES(?,?,?,?)',(run_id,body['command_id'],request,encoded(result)))
            self.save(r)
            return result

    def cursor_sequence(self,r,cursor):
        try:run_id,num=cursor.rsplit(':',1);seq=int(num)
        except (ValueError,AttributeError):raise APIError(400,'INVALID_CURSOR','Некорректный курсор')
        if run_id!=r['snapshot']['run']['run_id']:raise APIError(409,'GENERATION_MISMATCH','Курсор другого запуска')
        if seq<0 or seq>r['snapshot']['as_of']['sequence']:raise APIError(400,'INVALID_CURSOR','Курсор вне журнала')
        return seq

    def journal(self,run_id,owner,after,limit=128):
        with self.lock:
            self.get(run_id,owner)
            return [json.loads(row[0]) for row in self.db.execute('SELECT value FROM events WHERE run=? AND seq>? ORDER BY seq LIMIT ?',(run_id,after,limit))]

    def observation(self,r,oid):
        run=r['snapshot']['run']
        row=self.db.execute('SELECT value FROM observations WHERE run=? AND gen=? AND id=?',(run['run_id'],run['generation'],oid)).fetchone()
        if not row:raise APIError(404,'NOT_FOUND','Наблюдение ещё не доступно')
        return json.loads(row[0])

    def close(self):
        with self.lock:self.db.close()
