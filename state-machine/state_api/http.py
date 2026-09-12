"""Authenticated JSON/SSE and bounded media delivery; served behind a TLS proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
import time
import urllib.parse
import uuid

from .core import APIError, VERSION, encoded, utc

class Service:
    def __init__(self, store, config, spec_path):
        self.store=store;self.config=config;self.spec=json.loads(Path(spec_path).read_text())
        self.key=config['ticket_secret'].encode();self.stop=threading.Event()
        self.stream_slots=threading.BoundedSemaphore(config.get('max_streams',24))

    def sign(self, data):
        body=base64.urlsafe_b64encode(encoded(data).encode()).decode().rstrip('=')
        signature=hmac.new(self.key,body.encode(),hashlib.sha256).hexdigest()
        return body+'.'+signature

    def unsign(self, value, code='INVALID_CURSOR'):
        try:
            body,sig=value.split('.')
            if not hmac.compare_digest(sig,hmac.new(self.key,body.encode(),hashlib.sha256).hexdigest()):raise ValueError()
            data=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)))
            if not isinstance(data,dict):raise ValueError()
            return data
        except (ValueError,KeyError,TypeError):raise APIError(400,code,'Некорректный подписанный идентификатор')

    def auth(self, authorization, scope):
        if not authorization or not authorization.startswith('Bearer '):raise APIError(401,'UNAUTHORIZED','Требуется токен приложения')
        digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
        for token in self.config['tokens']:
            if hmac.compare_digest(digest,token['sha256']):
                if token['expires_at']<=time.time():raise APIError(401,'TOKEN_EXPIRED','Срок токена истёк')
                if scope not in token['scopes']:raise APIError(403,'FORBIDDEN','Недостаточно прав')
                return token
        raise APIError(401,'UNAUTHORIZED','Неизвестный токен приложения')

    def allowed_origin(self, origin):
        try:
            p=urllib.parse.urlsplit(origin)
            return bool(p.scheme in ['http','https'] and not p.username and not p.password and not p.path and not p.query and not p.fragment and
                (p.hostname in ['localhost','127.0.0.1','::1'] or origin in self.config.get('extra_origins',[])))
        except ValueError:return False

    def media_metadata(self,r,mid):
        if mid not in r['published_media'] or mid not in self.store.media:raise APIError(404,'NOT_FOUND','Медиа ещё не опубликовано')
        source=self.store.media[mid];run=r['snapshot']['run'];expires=int(time.time()+120)
        data={k:copy.deepcopy(v) for k,v in source.items() if k!='file'}
        data.update(run_id=run['run_id'],generation=run['generation'])
        ticket=self.sign({'type':'media','run':run['run_id'],'gen':run['generation'],'media':mid,'owner':r['owner'],'exp':expires})
        data['content_url']=self.config['public_url'].rstrip('/')+f'/runs/{run["run_id"]}/media/{mid}/content?'+urllib.parse.urlencode({'generation':run['generation'],'ticket':ticket})
        data['url_expires_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(expires))
        return data

    def live_metadata(self,r,source):
        run=r['snapshot']['run'];expires=int(time.time()+120)
        sid=source['stream_id'];duration=source['duration_ms'];position=run['sim_time_ms']
        token=self.sign({'type':'live_media','run':run['run_id'],'gen':run['generation'],'media':sid,'owner':r['owner'],'exp':expires})
        status='completed' if position>=duration else 'paused' if run['status']=='paused' else 'streaming' if position else 'waiting'
        return {'stream_id':sid,'run_id':run['run_id'],'generation':run['generation'],'device_id':source['device_id'],
            'kind':source['kind'],'mime_type':source['mime_type'],'codec':source['codec'],'framing':'fragmented_mp4',
            'capture_start_sim_time_ms':source['capture_start_sim_time_ms'],'duration_ms':duration,
            'available_until_sim_time_ms':max([0]+[f['end_ms'] for f in source['fragments'] if f['end_ms']<=position]),'status':status,
            'content_url':self.config['public_url'].rstrip('/')+f'/runs/{run["run_id"]}/media-streams/{sid}/content?'+urllib.parse.urlencode({'generation':run['generation'],'ticket':token}),
            'url_expires_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(expires)), 'provenance':copy.deepcopy(source['provenance']),
            **({'media_timestamp_offset_ms':source['media_timestamp_offset_ms']} if 'media_timestamp_offset_ms' in source else {})}

class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=64
    def __init__(self,address,service):
        self.service=service
        super().__init__(address,Handler)
    def handle_error(self,request,client_address):
        # Request URLs can carry short-lived media tickets; never log raw request lines.
        print('HTTP connection aborted',flush=True)

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='StateAPI/0.2'
    sys_version=''

    def setup(self):
        super().setup();self.connection.settimeout(15)

    @property
    def service(self):return self.server.service

    def log_message(self,*args):pass

    def headers_out(self,status,headers=None,length=None):
        self.send_response(status)
        self.send_header('X-Request-ID',self.request_id)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        if 'Cache-Control' not in (headers or {}):self.send_header('Cache-Control','no-store')
        origin=self.headers.get('Origin')
        if origin and self.service.allowed_origin(origin):
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
            self.send_header('Access-Control-Expose-Headers','Content-Length, Content-Range, Accept-Ranges, ETag, Retry-After, X-Request-ID')
        for k,v in (headers or {}).items():self.send_header(k,str(v))
        if length is not None:self.send_header('Content-Length',str(length))
        self.send_header('Connection','close');self.close_connection=True
        self.end_headers()

    def output(self,status,value,headers=None):
        data=encoded(value).encode()
        self.headers_out(status,{'Content-Type':'application/json; charset=utf-8',**(headers or {})},len(data))
        if self.command!='HEAD':self.wfile.write(data)

    def error(self,error,headers=None):
        extra=dict(headers or {})
        if error.status==429:extra['Retry-After']=str(max(1,error.details.get('retry_after_ms',1000)//1000))
        if error.status==401:extra['WWW-Authenticate']='Bearer'
        self.output(error.status,{'error':{'code':error.code,'message':str(error),'request_id':self.request_id,
            'retryable':error.status in [429,503],'details':error.details}},extra)

    def do_OPTIONS(self):self.dispatch()
    def do_GET(self):self.dispatch()
    def do_HEAD(self):self.dispatch()
    def do_POST(self):self.dispatch()

    def dispatch(self):
        self.request_id=str(uuid.uuid4())
        try:self.route()
        except APIError as error:self.error(error)
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        except (ValueError,TypeError,KeyError):self.error(APIError(400,'INVALID_REQUEST','Неверный формат запроса'))

    def route(self):
        uri=urllib.parse.urlsplit(self.path);path=uri.path
        pairs=urllib.parse.parse_qs(uri.query,keep_blank_values=True)
        if any(len(v)!=1 for v in pairs.values()):raise APIError(400,'INVALID_REQUEST','Повтор query-параметра')
        q={k:v[0] for k,v in pairs.items()}
        origin=self.headers.get('Origin')
        if origin and not self.service.allowed_origin(origin):raise APIError(403,'FORBIDDEN','Origin не разрешён')
        if self.command=='OPTIONS':
            self.headers_out(204,{'Access-Control-Allow-Methods':'GET, HEAD, POST, OPTIONS',
                'Access-Control-Allow-Headers':'Authorization, Content-Type, Idempotency-Key, Last-Event-ID, Range, If-Range',
                'Access-Control-Max-Age':'600'},0);return
        if self.command in ['GET','HEAD'] and path in ['/','/api/v1/health']:
            self.output(200,{'status':'ok','schema_version':VERSION});return
        match=re.fullmatch(r'/api/v1/runs/([a-zA-Z0-9-]+)(?:/(.*))?',path)
        suffix=match.group(2) if match else None
        media_match=re.fullmatch(r'media/([a-zA-Z0-9_-]+)/content',suffix or '')
        live_match=re.fullmatch(r'media-streams/([a-zA-Z0-9_-]+)/content',suffix or '')
        ticket_match=media_match or live_match
        if ticket_match and self.command in ['GET','HEAD'] and q.get('ticket'):
            ticket=self.service.unsign(q['ticket'],'INVALID_REQUEST')
            if ticket.get('type')!=('live_media' if live_match else 'media') or ticket.get('run')!=match.group(1) or ticket.get('media')!=ticket_match.group(1):raise APIError(403,'FORBIDDEN','Ticket другого ресурса')
            if ticket['exp']<=time.time():raise APIError(403,'MEDIA_TICKET_EXPIRED','Обновите ссылку через Media')
            if self.integer(q,'generation',required=True)!=ticket['gen']:raise APIError(403,'FORBIDDEN','Ticket другого поколения')
            token={'owner':ticket['owner'],'expires_at':ticket['exp']}
        else:token=self.service.auth(self.headers.get('Authorization'),'run:control' if self.command=='POST' else 'state:read')
        store=self.service.store;owner=token['owner']
        if self.command=='GET' and path=='/api/v1/capabilities':
            self.output(200,{'schema_version':VERSION,'api_version':'v1','features':{'sse':True,'camera_clips':True,'radio_audio':True,'source_people_counts':False,'continuous_media':True,
                'prerecorded_radio_transcripts':any(e['kind']=='radio_transcript' for source in store.sources.values() for e in source['events'])},
                'heartbeat_interval_ms':5000,'stream_timeout_ms':15000,'max_page_size':500,'event_retention':'24 hours from run creation'});return
        if self.command=='GET' and path=='/api/v1/scenarios':self.output(200,{'items':store.catalog});return
        if self.command=='GET' and path=='/api/v1/openapi.json':self.output(200,self.service.spec);return
        if self.command=='POST' and path=='/api/v1/runs':
            self.output(201,store.create(owner,self.headers.get('Idempotency-Key'),self.body()));return
        if not match:raise APIError(404,'NOT_FOUND','Endpoint не найден')
        run_id=match.group(1)
        if self.command=='POST' and suffix=='commands':self.output(200,store.command(owner,run_id,self.body()));return
        if self.command not in ['GET','HEAD']:raise APIError(404,'NOT_FOUND','Endpoint не найден')
        if suffix=='stream' and self.command=='GET':self.stream(run_id,owner,token,q);return
        if live_match and self.command=='GET':self.live_content(run_id,owner,live_match.group(1),q);return
        if media_match:self.media_content(run_id,owner,media_match.group(1),q);return
        with store.lock:
            need_gen=bool(suffix and (suffix.startswith(('devices/','evidence/','media/')) or suffix=='observations'))
            r=store.get(run_id,owner,self.integer(q,'generation',required=True) if need_gen else None)
            snap=r['snapshot']
            if not suffix:value=copy.deepcopy(snap['run'])
            elif suffix=='snapshot':value=copy.deepcopy(snap)
            elif suffix in ['devices','cameras','occupancy','access']:value={'items':copy.deepcopy(snap[suffix])}
            elif suffix=='system':value=copy.deepcopy(snap['system'])
            elif suffix=='media-streams':
                devices={d['device_id'] for d in snap['devices']}
                value={'items':[self.service.live_metadata(r,source) for source in store.live_streams.values() if source['device_id'] in devices]}
            elif suffix.startswith('devices/'):
                value=next((copy.deepcopy(d) for d in snap['devices'] if d['device_id']==suffix[8:]),None)
                if value is None:raise APIError(404,'NOT_FOUND','Прибор не найден')
            elif suffix.startswith('evidence/'):value=store.observation(r,suffix[9:])
            elif suffix.startswith('media/'):value=self.service.media_metadata(r,suffix[6:])
            elif suffix=='observations':value=self.history(r,q)
            else:raise APIError(404,'NOT_FOUND','Endpoint не найден')
        self.output(200,value)

    def body(self):
        if self.headers.get('Transfer-Encoding'):raise APIError(400,'INVALID_REQUEST','Требуется Content-Length')
        try:length=int(self.headers.get('Content-Length','-1'))
        except ValueError:raise APIError(400,'INVALID_REQUEST','Некорректная длина тела')
        if not 0<=length<=65536:raise APIError(400,'INVALID_REQUEST','Размер JSON должен быть до 64 KiB')
        if not self.headers.get('Content-Type','').lower().startswith('application/json'):raise APIError(400,'INVALID_REQUEST','Требуется application/json')
        def invalid(_):raise ValueError('non-finite JSON')
        data=json.loads(self.rfile.read(length),parse_constant=invalid)
        if not isinstance(data,dict):raise APIError(400,'INVALID_REQUEST','Требуется JSON object')
        return data

    @staticmethod
    def integer(q,key,default=None,required=False):
        value=q.get(key)
        if value is None:
            if required:raise APIError(400,'INVALID_REQUEST','Не указан '+key)
            return default
        if not re.fullmatch(r'\d+',value):raise APIError(400,'INVALID_REQUEST','Неверный '+key)
        return int(value)

    def history(self,r,q):
        run=r['snapshot']['run'];store=self.service.store
        limit=self.integer(q,'limit',100)
        if not 1<=limit<=500:raise APIError(400,'INVALID_REQUEST','limit вне диапазона 1..500')
        filters={'device':q.get('device_id'),'from':self.integer(q,'from_ms',0),'to':self.integer(q,'to_ms',None)}
        if q.get('cursor'):
            page=self.service.unsign(q['cursor'])
            if page.get('type')!='history' or page.get('run')!=run['run_id'] or page.get('gen')!=run['generation']:raise APIError(409,'GENERATION_MISMATCH','История другого run/generation')
            if page['filters']!=filters:raise APIError(400,'INVALID_CURSOR','Фильтры страницы изменились')
        else:
            page={'type':'history','run':run['run_id'],'gen':run['generation'],'filters':filters,
                'highwater':r['snapshot']['as_of']['sequence'],'end':filters['to'] if filters['to'] is not None else run['sim_time_ms']+1,'offset':0}
        if page['end']<filters['from']:raise APIError(400,'INVALID_REQUEST','Неверный диапазон времени')
        sql='SELECT value FROM observations WHERE run=? AND gen=? AND seq<=? AND observed>=? AND observed<?'
        args=[run['run_id'],run['generation'],page['highwater'],filters['from'],page['end']]
        if filters['device'] is not None:sql+=' AND device=?';args.append(filters['device'])
        sql+=' ORDER BY received,observed,id LIMIT ? OFFSET ?';args.extend([limit+1,page['offset']])
        rows=[json.loads(row[0]) for row in store.db.execute(sql,args)]
        next_cursor=None
        if len(rows)>limit:
            page['offset']+=limit;next_cursor=self.service.sign(page)
        return {'items':rows[:limit],'next_cursor':next_cursor,'generation':run['generation'],'as_of_sequence':page['highwater']}

    def stream(self,run_id,owner,token,q):
        if q.get('after') is not None and self.headers.get('Last-Event-ID') is not None:raise APIError(400,'INVALID_CURSOR','Передайте один курсор')
        store=self.service.store
        with store.lock:
            r=store.get(run_id,owner)
            cursor=q.get('after',self.headers.get('Last-Event-ID'))
            snapshot=copy.deepcopy(r['snapshot']) if cursor is None else None
            seq=snapshot['as_of']['sequence'] if snapshot else store.cursor_sequence(r,cursor)
        if not self.service.stream_slots.acquire(blocking=False):raise APIError(429,'RATE_LIMITED','Лимит SSE-соединений',retry_after_ms=5000)
        self.connection.settimeout(10)
        try:
            self.headers_out(200,{'Content-Type':'text/event-stream; charset=utf-8','X-Accel-Buffering':'no','Cache-Control':'no-cache, no-transform'})
            self.wfile.write(b'retry: 2000\n\n');self.wfile.flush()
            if snapshot:self.frame('snapshot',snapshot,snapshot['as_of']['cursor'])
            heartbeat=time.monotonic()
            while not self.service.stop.is_set():
                if token['expires_at']<=time.time():return
                try:batch=store.journal(run_id,owner,seq)
                except APIError as error:
                    self.frame('stream_error',{'error':{'code':error.code,'message':str(error),'request_id':self.request_id,'retryable':False,'details':error.details}});return
                with store.lock:
                    backlog=store.runs[run_id]['snapshot']['as_of']['sequence']-seq
                if backlog>50000:
                    self.frame('stream_error',{'error':{'code':'BACKPRESSURE_RESYNC','message':'Получите новый snapshot; история доступна через GET observations.',
                        'request_id':self.request_id,'retryable':False,'details':{'snapshot_url':'/api/v1/runs/'+run_id+'/snapshot'}}});return
                if batch:
                    for event in batch:
                        self.frame('event',event,event['cursor']);seq=event['sequence']
                if time.monotonic()-heartbeat>=5:
                    with store.lock:
                        r=store.get(run_id,owner);run=r['snapshot']['run']
                        data={'run_id':run_id,'generation':run['generation'],'last_sequence':r['snapshot']['as_of']['sequence'],
                              'sim_time_ms':run['sim_time_ms'],'server_time':utc()}
                    self.frame('heartbeat',data);heartbeat=time.monotonic()
                if not batch:self.service.stop.wait(.15)
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        finally:self.service.stream_slots.release()

    def frame(self,kind,data,cursor=None):
        text=('id: '+cursor+'\n' if cursor else '')+'event: '+kind+'\ndata: '+encoded(data)+'\n\n'
        self.wfile.write(text.encode());self.wfile.flush()

    def live_content(self,run_id,owner,sid,q):
        store=self.service.store;generation=self.integer(q,'generation',required=True)
        with store.lock:
            r=store.get(run_id,owner,generation)
            source=store.live_streams.get(sid)
            if source is None or source['device_id'] not in {d['device_id'] for d in r['snapshot']['devices']}:
                raise APIError(404,'NOT_FOUND','Поток не найден')
            path=(store.bundle/source['file']).resolve()
            if not path.is_relative_to(store.bundle/'assets') or not path.is_file():raise APIError(404,'NOT_FOUND','Поток недоступен')
        if not self.service.stream_slots.acquire(blocking=False):raise APIError(429,'RATE_LIMITED','Лимит потоковых соединений',retry_after_ms=5000)
        self.connection.settimeout(10)
        try:
            self.headers_out(200,{'Content-Type':source['mime_type'],'Cache-Control':'no-store, no-transform',
                'X-Accel-Buffering':'no','Accept-Ranges':'none','X-Media-Framing':'fragmented-mp4'})
            with path.open('rb') as f:
                # Initialization contains codec/track metadata, no future media samples.
                self.wfile.write(f.read(source['init_length']));self.wfile.flush()
                for fragment in source['fragments']:
                    while not self.service.stop.is_set():
                        with store.lock:
                            try:r=store.get(run_id,owner,generation)
                            except APIError:return
                            if r['transport'].get(source['device_id'],'online')!='online':return
                            ready=r['snapshot']['run']['sim_time_ms']>=fragment['end_ms']
                        if ready:break
                        self.service.stop.wait(.1)
                    if self.service.stop.is_set():return
                    f.seek(fragment['offset']);self.wfile.write(f.read(fragment['length']));self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        finally:self.service.stream_slots.release()

    def media_content(self,run_id,owner,mid,q):
        store=self.service.store
        with store.lock:
            r=store.get(run_id,owner,self.integer(q,'generation',required=True))
            if mid not in r['published_media'] or mid not in store.media:raise APIError(404,'NOT_FOUND','Медиа ещё не опубликовано')
            meta=store.media[mid];path=(store.bundle/meta['file']).resolve()
            if not path.is_relative_to(store.bundle/'assets') or not path.is_file():raise APIError(404,'NOT_FOUND','Медиа недоступно')
            length=path.stat().st_size;etag='"'+meta['sha256']+'"';mime=meta['mime_type']
        start,end,status=0,length-1,200
        headers={'Content-Type':mime,'ETag':etag,'Accept-Ranges':'bytes'}
        byte_range=self.headers.get('Range') if self.command=='GET' else None
        if byte_range and self.headers.get('If-Range',etag)==etag:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',byte_range)
            try:
                if not m or (not m[1] and not m[2]):raise ValueError()
                if m[1]:start=int(m[1]);end=min(length-1,int(m[2])) if m[2] else length-1
                else:
                    size=int(m[2])
                    if size<=0:raise ValueError()
                    start=max(0,length-size)
                if start>=length or start>end:raise ValueError()
            except ValueError:
                self.error(APIError(416,'RANGE_NOT_SATISFIABLE','Недопустимый byte range'),{'Content-Range':f'bytes */{length}'});return
            status=206;headers['Content-Range']=f'bytes {start}-{end}/{length}'
        self.headers_out(status,headers,end-start+1)
        if self.command=='HEAD':return
        with path.open('rb') as f:
            f.seek(start);remaining=end-start+1
            while remaining:
                block=f.read(min(65536,remaining))
                if not block:break
                self.wfile.write(block);remaining-=len(block)
