"""Durable questions and projections for UI. Single API/worker process in this MVP."""
import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from .models import Event, Answer as EngineAnswer
from . import ui_models as m

TERMINAL = {'ready','insufficient_data','error','cancelled'}

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def compact(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def stable(*parts): return str(uuid.uuid5(uuid.NAMESPACE_URL,compact(parts)))

class UIError(Exception):
    def __init__(self,status,code,message,retryable=False,request_id=None):
        self.status=status
        self.body=m.Error(code=code,message=message,retryable=retryable,request_id=request_id or str(uuid.uuid4()))
        super().__init__(message)

class UIService:
    def __init__(self,runtime):
        self.runtime=runtime; self.store=runtime.store
        with self.store.tx() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS ui_contexts(
              session_id TEXT,generation INTEGER,subject_id TEXT,devices TEXT,
              revision INTEGER NOT NULL DEFAULT 0,updated_at TEXT,
              PRIMARY KEY(session_id,generation,subject_id));
            CREATE TABLE IF NOT EXISTS ui_questions(
              id TEXT PRIMARY KEY,session_id TEXT,generation INTEGER,subject_id TEXT,
              client_id TEXT,fingerprint TEXT,body TEXT,status TEXT,lease REAL DEFAULT 0,token TEXT,
              UNIQUE(session_id,generation,subject_id,client_id));
            CREATE TABLE IF NOT EXISTS ui_cards(
              id TEXT PRIMARY KEY,session_id TEXT,generation INTEGER,subject_id TEXT,body TEXT,fingerprint TEXT);
            CREATE TABLE IF NOT EXISTS ui_evidence(
              id TEXT PRIMARY KEY,session_id TEXT,generation INTEGER,subject_id TEXT,event_id TEXT,
              UNIQUE(session_id,generation,subject_id,event_id));
            ''')
    @staticmethod
    def scope(ctx): return (ctx.demo_context_id,ctx.generation,ctx.subject_id)
    def bind_context(self,sid,generation,subject='all',device_ids=None):
        """Internal/demo setup only. Scope never changes after registration."""
        ctx=m.Context(demo_context_id=sid,generation=generation,subject_id=subject)
        devices=compact(sorted(set(device_ids)) if device_ids is not None else None)
        with self.store.tx() as c:
            self.store.require(c,sid,generation)
            old=c.execute('SELECT devices FROM ui_contexts WHERE session_id=? AND generation=? AND subject_id=?',self.scope(ctx)).fetchone()
            if old and old['devices']!=devices: raise UIError(409,'CONTEXT_SCOPE_CONFLICT','Create a new subject or generation for a different source scope.')
            c.execute('INSERT OR IGNORE INTO ui_contexts(session_id,generation,subject_id,devices,updated_at) VALUES (?,?,?,?,?)',(*self.scope(ctx),devices,now()))
        return ctx
    def require(self,c,ctx):
        session=c.execute('SELECT * FROM sessions WHERE id=?',(ctx.demo_context_id,)).fetchone()
        if not session: raise UIError(404,'NOT_FOUND','Unknown demo context.')
        if session['generation']!=ctx.generation: raise UIError(409,'CONTEXT_STALE','The replay context has changed.')
        row=c.execute('SELECT * FROM ui_contexts WHERE session_id=? AND generation=? AND subject_id=?',self.scope(ctx)).fetchone()
        if not row: raise UIError(403,'FORBIDDEN','Subject is not bound to this context.')
        return session,row
    def bump(self,c,ctx):
        c.execute('UPDATE ui_contexts SET revision=revision+1,updated_at=? WHERE session_id=? AND generation=? AND subject_id=?',(now(),*self.scope(ctx)))
    def save_answer(self,c,answer,**fields):
        validated=m.Answer.model_validate(answer).model_dump()
        c.execute('UPDATE ui_questions SET body=?,status=? WHERE id=?',(compact(validated),validated['status'],validated['request_id']))
        if fields:
            c.execute('UPDATE ui_questions SET lease=?,token=? WHERE id=?',(fields['lease'],fields['token'],validated['request_id']))
        self.bump(c,m.Context.model_validate(validated['context']))
    def coverage(self,as_of,language='en'):
        text='Полнота входной истории не подтверждена; поиск ограничен.' if language=='ru' else 'Source history completeness is not established; retrieval is bounded.'
        return dict(as_of_ms=as_of,checked_from_ms=0,checked_until_ms=as_of,completeness='unknown',limitations=[text])
    def submit(self,body:m.QuestionCreate):
        with self.store.tx() as c:
            session,_=self.require(c,body.context)
            fp=compact(body.model_dump())
            old=c.execute('SELECT * FROM ui_questions WHERE session_id=? AND generation=? AND subject_id=? AND client_id=?',(*self.scope(body.context),body.client_request_id)).fetchone()
            if old:
                if old['fingerprint']!=fp: raise UIError(409,'IDEMPOTENCY_CONFLICT','This request key was used for a different question.')
                return m.Answer.model_validate_json(old['body'])
            answer=m.Answer(request_id=str(uuid.uuid4()),context=body.context,revision=0,status='queued',question=body.question,
                language=body.language,claims=[],unknowns=[],coverage=self.coverage(session['time_ms'],body.language),queries=[],evidence_ids=[],created_at=now(),completed_at=None,error=None)
            c.execute('INSERT INTO ui_questions(id,session_id,generation,subject_id,client_id,fingerprint,body,status) VALUES (?,?,?,?,?,?,?,?)',
                      (answer.request_id,*self.scope(body.context),body.client_request_id,fp,answer.model_dump_json(),answer.status))
            self.bump(c,body.context)
            return answer
    def get_answer(self,ctx,rid):
        with self.store.tx() as c:
            self.require(c,ctx)
            row=c.execute('SELECT body FROM ui_questions WHERE id=? AND session_id=? AND generation=? AND subject_id=?',(rid,*self.scope(ctx))).fetchone()
            if not row: raise UIError(404,'NOT_FOUND','Question not found in this context.')
            return m.Answer.model_validate_json(row['body'])
    def cancel(self,ctx,rid):
        with self.store.tx() as c:
            self.require(c,ctx)
            row=c.execute('SELECT body FROM ui_questions WHERE id=? AND session_id=? AND generation=? AND subject_id=?',(rid,*self.scope(ctx))).fetchone()
            if not row:raise UIError(404,'NOT_FOUND','Question not found in this context.')
            answer=json.loads(row['body'])
            if answer['status'] not in TERMINAL:
                answer.update(status='cancelled',revision=answer['revision']+1,completed_at=now())
                self.save_answer(c,answer,lease=0,token=None)
            return m.Answer.model_validate(answer)
    def _claim_question(self):
        with self.store.tx() as c:
            # Invalidate unfinished questions belonging to previous replay generations.
            for row in c.execute("SELECT q.* FROM ui_questions q JOIN sessions s ON s.id=q.session_id WHERE q.generation!=s.generation AND q.status IN ('queued','running')").fetchall():
                answer=json.loads(row['body']);answer.update(status='cancelled',revision=answer['revision']+1,completed_at=now())
                self.save_answer(c,answer,lease=0,token=None)
            row=c.execute("SELECT q.* FROM ui_questions q JOIN sessions s ON s.id=q.session_id AND s.generation=q.generation WHERE q.status='queued' OR (q.status='running' AND q.lease<?) ORDER BY q.rowid LIMIT 1",(time.time(),)).fetchone()
            if not row:return None
            answer=json.loads(row['body']);answer.update(status='running',revision=answer['revision']+1)
            token=str(uuid.uuid4())
            self.save_answer(c,answer,lease=time.time()+40,token=token)
            return answer,token
    def _events(self,c,ctx,as_of,limit=20):
        _,binding=self.require(c,ctx)
        devices=json.loads(binding['devices'])
        sql='SELECT body FROM events WHERE session_id=? AND generation=? AND time_ms<=?'
        args=[ctx.demo_context_id,ctx.generation,as_of]
        if devices is not None:
            if not devices:return []
            sql+=' AND json_extract(body,\'$.source_id\') IN ('+','.join('?' for _ in devices)+')';args+=devices
        sql+=' ORDER BY time_ms DESC,event_id LIMIT ?';args.append(limit)
        events=[];size=0
        for row in c.execute(sql,args):
            if size+len(row['body'])>24000:break
            size+=len(row['body']);events.append(Event.model_validate_json(row['body']))
        return list(reversed(events))
    def _evidence_id(self,c,ctx,event):
        if event.reading_id is None or event.reading_id<=0:return None
        eid=stable('evidence',*self.scope(ctx),event.event_id)
        c.execute('INSERT OR IGNORE INTO ui_evidence VALUES (?,?,?,?,?)',(eid,*self.scope(ctx),event.event_id))
        return eid
    async def process_one(self):
        claimed=self._claim_question()
        if not claimed:return False
        answer,token=claimed;ctx=m.Context.model_validate(answer['context'])
        query={'query_id':str(uuid.uuid4()),'tool':'local_event_query','filters':{'context':ctx.model_dump(),'as_of_ms':answer['coverage']['as_of_ms'],'limit':20,'max_characters':24000},
               'started_at':now(),'completed_at':None,'status':'running','completeness':'unknown','error_code':None}
        try:
            with self.store.tx() as c:
                events=self._events(c,ctx,answer['coverage']['as_of_ms'])
                by_id={e.event_id:e for e in events}
                refs={e.event_id:self._evidence_id(c,ctx,e) for e in events}
            query.update(status='succeeded',completed_at=now(),completeness='partial')
            # Persist actual retrieval before the model call so GET can show tool progress.
            with self.store.tx() as c:
                current=c.execute("SELECT body FROM ui_questions WHERE id=? AND status='running' AND token=?",(answer['request_id'],token)).fetchone()
                if not current:return True
                answer=json.loads(current['body']);answer['queries']=[query];answer['revision']+=1
                self.save_answer(c,answer)
            result=EngineAnswer.model_validate(await asyncio.wait_for(self.runtime.engine.answer(answer['question'],events,language=answer['language']),30))
            if any(not set(cl.evidence_ids)<=set(by_id) for cl in result.claims): raise ValueError('Unknown evidence')
            claims=[];unknowns=list(result.limitations)
            for i,cl in enumerate(result.claims):
                evidence=[refs[x] for x in cl.evidence_ids]
                if not all(evidence):
                    unknowns.append('Some claims were withheld because a platform reading ID is unavailable.');continue
                claims.append(dict(claim_id=stable(answer['request_id'],i),text=cl.text,kind='inference',evidence_ids=evidence))
            answer.update(status='ready' if claims else 'insufficient_data',claims=claims,unknowns=unknowns,
                          evidence_ids=list(dict.fromkeys(e for cl in claims for e in cl['evidence_ids'])),error=None)
            answer['coverage']['completeness']='partial'
        except Exception:
            if query['status']=='running':query.update(status='failed',completed_at=now(),error_code='SOURCE_QUERY_FAILED')
            answer.update(status='error',claims=[],evidence_ids=[],unknowns=[],error=m.Error(code='UPSTREAM_UNAVAILABLE',message='Could not complete the evidence-backed answer.',retryable=True,request_id=answer['request_id']).model_dump())
        answer['queries']=[query];answer['completed_at']=now()
        with self.store.tx() as c:
            row=c.execute("SELECT body FROM ui_questions WHERE id=? AND token=? AND status='running' AND lease>?",(answer['request_id'],token,time.time())).fetchone()
            if not row:return True # cancellation or another worker supersedes this result
            session=c.execute('SELECT generation FROM sessions WHERE id=?',(ctx.demo_context_id,)).fetchone()
            if not session or session['generation']!=ctx.generation:
                answer.update(status='cancelled',claims=[],evidence_ids=[],error=None)
            answer['revision']=json.loads(row['body'])['revision']+1
            self.save_answer(c,answer,lease=0,token=None)
        return True
    def _refresh_cards(self,c,ctx):
        session,binding=self.require(c,ctx);as_of=session['time_ms']
        device_ids=json.loads(binding['devices'])
        watches=c.execute('SELECT * FROM watches WHERE session_id=? AND generation=?',(ctx.demo_context_id,ctx.generation)).fetchall()
        tables={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for watch in watches:
            raw=[]
            for event_id in json.loads(watch['evidence']):
                row=c.execute('SELECT body FROM events WHERE session_id=? AND generation=? AND event_id=?',(ctx.demo_context_id,ctx.generation,event_id)).fetchone()
                if row:raw.append(Event.model_validate_json(row['body']))
            # Do not project a global watch into a narrower subject or expose future evidence.
            if not raw or any(e.time_ms>as_of or (device_ids is not None and e.source_id not in device_ids) for e in raw):continue
            refs=[self._evidence_id(c,ctx,e) for e in raw]
            claims=[dict(claim_id=stable('card-claim',*self.scope(ctx),e.event_id),text=e.description or 'Source observation',kind='source_report',evidence_ids=[ref]) for e,ref in zip(raw,refs) if ref]
            assessments={'checking':'checking','accepted':'checking','no_confirmation':'insufficient_data','supported_by_report':'supported','no_longer_relevant':'insufficient_data'}
            assessment=assessments[watch['assessment']]
            if not all(refs):assessment='insufficient_data'
            linked=None
            if 'platform_links' in tables:
                linked=c.execute('SELECT incident_id FROM platform_links WHERE session_id=? AND generation=? AND task_ref=?',(ctx.demo_context_id,ctx.generation,watch['task_ref'])).fetchone()
            pubs=[r for r in c.execute('SELECT body,status FROM outbox WHERE session_id=? AND generation=? ORDER BY rowid',(ctx.demo_context_id,ctx.generation)) if json.loads(r['body'])['task_ref']==watch['task_ref']]
            status=pubs[-1]['status'] if pubs else 'pending'
            publication='uncertain' if any(r['status']=='uncertain' for r in pubs) else {'sent':'synced','blocked':'error','sending':'pending'}.get(status,'pending')
            hypothesis_id=stable('watch',*self.scope(ctx),watch['task_ref'])
            old=c.execute('SELECT * FROM ui_cards WHERE id=?',(hypothesis_id,)).fetchone()
            value=dict(hypothesis_id=hypothesis_id,platform_incident_id=linked['incident_id'] if linked else None,context=ctx.model_dump(),revision=0,
                       statement=f"Check whether task {watch['task_ref']} has a completion report.",assessment=assessment,
                       lifecycle='closed' if watch['assessment']=='no_longer_relevant' else 'active',platform_status=None,publication_status=publication,
                       claims=claims,unknowns=['A source report does not independently prove execution.'],coverage=self.coverage(as_of),queries=[],
                       evidence_ids=[r for r in refs if r],checked_at=now(),closure_reason='Cancellation reported.' if watch['assessment']=='no_longer_relevant' else None)
            # Only a fetched platform status may be displayed; do not infer it from outbox intent.
            if 'ui_platform_status' in tables and linked:
                ps=c.execute('SELECT status FROM ui_platform_status WHERE incident_id=?',(linked['incident_id'],)).fetchone()
                if ps:value['platform_status']=ps['status']
            if watch['assessment']=='no_confirmation':value['unknowns'].append('No completion report found in processed inputs; source coverage is not guaranteed.')
            if not all(refs):value['unknowns'].append('Platform reading IDs are missing for some source events.')
            comparison={k:v for k,v in value.items() if k not in ('revision','checked_at')}
            fp=compact(comparison)
            if old and old['fingerprint']==fp:continue
            value['revision']=json.loads(old['body'])['revision']+1 if old else 0
            validated=m.Card.model_validate(value).model_dump()
            c.execute('INSERT OR REPLACE INTO ui_cards VALUES (?,?,?,?,?,?)',(hypothesis_id,*self.scope(ctx),compact(validated),fp))
            self.bump(c,ctx)
    def snapshot(self,ctx):
        with self.store.tx() as c:
            self._refresh_cards(c,ctx)
            _,binding=self.require(c,ctx)
            answers=[m.Answer.model_validate_json(r['body']) for r in c.execute('SELECT body FROM ui_questions WHERE session_id=? AND generation=? AND subject_id=? ORDER BY rowid',self.scope(ctx))]
            cards=[m.Card.model_validate_json(r['body']) for r in c.execute('SELECT body FROM ui_cards WHERE session_id=? AND generation=? AND subject_id=? ORDER BY rowid',self.scope(ctx))]
            return m.Snapshot(context=ctx,snapshot_revision=binding['revision'],answers=answers,cards=cards,updated_at=binding['updated_at'])
    def get_card(self,ctx,hid):
        for card in self.snapshot(ctx).cards:
            if card.hypothesis_id==hid:return card
        raise UIError(404,'NOT_FOUND','Card not found in this context.')
    def evidence(self,ctx,eid):
        with self.store.tx() as c:
            session,binding=self.require(c,ctx)
            row=c.execute('SELECT event_id FROM ui_evidence WHERE id=? AND session_id=? AND generation=? AND subject_id=?',(eid,*self.scope(ctx))).fetchone()
            if not row:raise UIError(404,'NOT_FOUND','Evidence not found in this context.')
            source=c.execute('SELECT body FROM events WHERE session_id=? AND generation=? AND event_id=?',(ctx.demo_context_id,ctx.generation,row['event_id'])).fetchone()
            if not source:raise UIError(404,'NOT_FOUND','Source reading unavailable.')
            e=Event.model_validate_json(source['body']);devices=json.loads(binding['devices'])
            if e.time_ms>session['time_ms'] or (devices is not None and e.source_id not in devices):raise UIError(404,'NOT_FOUND','Evidence is not published in this context.')
            payload=e.payload;platform=payload.get('platform',{})
            origin=platform.get('provenance',{}).get('origin','synthetic' if 'fixture' in payload else 'unknown')
            if origin not in ('recorded','synthetic','derived','human_report'):origin='unknown'
            audio=None
            if e.kind=='radio':
                audio=m.Audio(media_id=str(payload.get('media_id') or stable('unresolved-media',eid)),availability='pending' if e.media_url else 'missing',
                    playback_url=None,expires_at=None,start_ms=e.media_start_ms or 0,end_ms=e.media_end_ms or e.media_start_ms or 0,time_basis='returned_media',mime_type=None)
            # No external URL is exposed until a trusted resolver is configured.
            return m.Evidence(evidence_id=eid,context=ctx,reading_id=e.reading_id,device_id=e.source_id,event_from_ms=e.time_ms,event_until_ms=e.time_ms,
                source_label=e.source_id,text=e.description,text_kind='description',verification='not_human_verified',origin=origin,audio=audio,
                raw_reading=sanitize(platform or {'id':e.reading_id,'description':e.description,'payload':payload}))
    async def notifications(self,ctx,disconnected):
        seen={};last_ping=time.monotonic()
        while not await disconnected():
            try:snapshot=self.snapshot(ctx)
            except UIError as exc:
                if exc.body.code=='CONTEXT_STALE':
                    data=m.Changed(type='context.invalidated',context=ctx,entity_id=None,revision=0)
                    yield 'event: context.invalidated\ndata: '+data.model_dump_json()+'\n\n'
                    return
                raise
            for kind,items,idfield in [('answer',snapshot.answers,'request_id'),('card',snapshot.cards,'hypothesis_id')]:
                for entity in items:
                    eid=getattr(entity,idfield);key=(kind,eid)
                    if seen.get(key,-1)<entity.revision:
                        seen[key]=entity.revision
                        data=m.Changed(type=kind+'.changed',context=ctx,entity_id=eid,revision=entity.revision)
                        yield f'event: {data.type}\ndata: {data.model_dump_json()}\n\n'
            if time.monotonic()-last_ping>10:
                yield ': keepalive\n\n';last_ping=time.monotonic()
            await asyncio.sleep(.25)

def sanitize(value):
    """The browser never receives credentials or signed URLs from a raw source payload."""
    if isinstance(value,dict):
        return {k:sanitize(v) for k,v in value.items() if not any(word in k.lower() for word in ('key','token','secret','ticket','authorization','cookie','url','password'))}
    if isinstance(value,list):return [sanitize(x) for x in value]
    if isinstance(value,str) and ('http://' in value or 'https://' in value):return '[URL redacted]'
    return value
