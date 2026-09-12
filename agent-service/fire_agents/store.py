import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .models import Event
from .model_input import compact_event

class StaleGeneration(ValueError): pass

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.tx() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, generation INTEGER NOT NULL, time_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events(session_id TEXT, generation INTEGER, event_id TEXT, time_ms INTEGER, body TEXT,
              PRIMARY KEY(session_id,generation,event_id));
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, session_id TEXT, generation INTEGER, event_id TEXT,
              status TEXT, attempts INTEGER DEFAULT 0, lease_until REAL DEFAULT 0, token TEXT, error TEXT,
              UNIQUE(session_id,generation,event_id));
            CREATE TABLE IF NOT EXISTS watches(session_id TEXT, generation INTEGER, task_ref TEXT, team TEXT,
              assessment TEXT, last_ms INTEGER, due_ms INTEGER, evidence TEXT, published INTEGER DEFAULT 0,
              PRIMARY KEY(session_id,generation,task_ref));
            CREATE TABLE IF NOT EXISTS channel_facts(session_id TEXT,generation INTEGER,event_id TEXT,time_ms INTEGER,source_id TEXT,body TEXT,PRIMARY KEY(session_id,generation,event_id));
            CREATE TABLE IF NOT EXISTS channel_checks(session_id TEXT,generation INTEGER,task_ref TEXT,body TEXT,PRIMARY KEY(session_id,generation,task_ref));
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, session_id TEXT, generation INTEGER, body TEXT, status TEXT);
            ''')
    @contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally: c.close()
    def require(self, c, sid, generation):
        row = c.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row or row['generation'] != generation: raise StaleGeneration('Unknown session or obsolete generation')
        return row
    def start(self, sid):
        with self.tx() as c:
            c.execute('INSERT OR IGNORE INTO sessions VALUES (?,0,0)', (sid,))
            return dict(c.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone())
    def reset(self, sid):
        with self.tx() as c:
            if not c.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone(): raise ValueError('Unknown session')
            c.execute('UPDATE sessions SET generation=generation+1,time_ms=0 WHERE id=?', (sid,))
            c.execute("UPDATE jobs SET status='cancelled' WHERE session_id=? AND status IN ('pending','running')", (sid,))
            c.execute("UPDATE outbox SET status='cancelled' WHERE session_id=? AND status='pending'", (sid,))
            return dict(c.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone())
    def ingest(self, event: Event):
        if len(event.model_dump_json()) > 20000: raise ValueError('Event exceeds input budget')
        with self.tx() as c:
            self.require(c, event.session_id, event.generation)
            old = c.execute('SELECT body FROM events WHERE session_id=? AND generation=? AND event_id=?',
                            (event.session_id,event.generation,event.event_id)).fetchone()
            if old:
                if old['body'] != event.model_dump_json(): raise ValueError('Immutable event ID reused with different content')
                return False
            c.execute('INSERT INTO events VALUES (?,?,?,?,?)', (event.session_id,event.generation,event.event_id,event.time_ms,event.model_dump_json()))
            c.execute("INSERT INTO jobs(id,session_id,generation,event_id,status) VALUES (?,?,?,?,'pending')",
                      (str(uuid.uuid4()),event.session_id,event.generation,event.event_id))
            return True
    def claim_job(self):
        with self.tx() as c:
            row = c.execute("SELECT j.* FROM jobs j JOIN sessions s ON s.id=j.session_id AND s.generation=j.generation JOIN events e ON e.session_id=j.session_id AND e.generation=j.generation AND e.event_id=j.event_id WHERE e.time_ms<=s.time_ms AND (j.status='pending' OR (j.status='running' AND j.lease_until<?)) ORDER BY e.time_ms,j.rowid LIMIT 1", (time.time(),)).fetchone()
            if not row: return None
            token = str(uuid.uuid4())
            c.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease_until=?,token=? WHERE id=?", (time.time()+45,token,row['id']))
            body = c.execute('SELECT body FROM events WHERE session_id=? AND generation=? AND event_id=?', (row['session_id'],row['generation'],row['event_id'])).fetchone()['body']
            return dict(row) | {'token':token, 'event':Event.model_validate_json(body)}
    def fail(self, job, error):
        with self.tx() as c:
            c.execute("UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,error=? WHERE id=? AND token=? AND status='running'",
                      (type(error).__name__,job['id'],job['token']))
    def finish(self, job, result, timeout_ms):
        e = job['event']
        with self.tx() as c:
            self.require(c,e.session_id,e.generation)
            active = c.execute("SELECT 1 FROM jobs WHERE id=? AND token=? AND status='running' AND lease_until>?",(job['id'],job['token'],time.time())).fetchone()
            if not active: raise ValueError('Job lease lost')
            if result.action.startswith('channel_'):
                from .channels import record
                record(c, e, result)
                c.execute("UPDATE jobs SET status='done' WHERE id=?", (job['id'],))
                return
            if result.action != 'none':
                if not result.claim or set(result.claim.evidence_ids) != {e.event_id}: raise ValueError('Invalid evidence')
                if result.task_ref:
                    old = c.execute('SELECT * FROM watches WHERE session_id=? AND generation=? AND task_ref=?',(e.session_id,e.generation,result.task_ref)).fetchone()
                    if old and old['team'] and result.team and old['team'] != result.team: raise ValueError('Conflicting task team')
                    evidence = list(dict.fromkeys((json.loads(old['evidence']) if old else []) + [e.event_id]))
                    if not old or e.time_ms >= old['last_ms']:
                        assessment = {'assigned':'checking','accepted':'accepted','completed':'supported_by_report','cancelled':'no_longer_relevant'}[result.action]
                        # Terminal reports remain terminal unless a new explicit assignment is received.
                        if old and old['assessment'] in ('supported_by_report','no_longer_relevant') and result.action=='accepted':
                            assessment = old['assessment']
                        due = old['due_ms'] if old else e.time_ms+timeout_ms
                        published = old['published'] if old else 0
                        c.execute('INSERT OR REPLACE INTO watches VALUES (?,?,?,?,?,?,?,?,?)',
                                  (e.session_id,e.generation,result.task_ref,result.team or (old['team'] if old else None),assessment,e.time_ms,due,json.dumps(evidence),published))
                        if published:
                            self.publish(c,e.session_id,e.generation,result.task_ref,assessment,evidence)
            c.execute("UPDATE jobs SET status='done' WHERE id=?",(job['id'],))
    def publish(self,c,sid,gen,ref,assessment,evidence):
        body={'task_ref':ref,'assessment':assessment,'evidence_ids':evidence,
              'platform_status':'resolved' if assessment in ('supported_by_report','no_longer_relevant') else 'open',
              'limitations':['Полнота входного потока пока не подтверждена.'], 'destination':'mock'}
        key=f'{sid}:{gen}:{ref}:{assessment}:{",".join(evidence)}'
        c.execute("INSERT OR IGNORE INTO outbox VALUES (?,?,?,?, 'pending')",(key,sid,gen,json.dumps(body,ensure_ascii=False)))
    def tick(self,sid,gen,ms=None):
        with self.tx() as c:
            session=self.require(c,sid,gen)
            if ms is None:ms=session['time_ms']
            if ms < session['time_ms']: raise ValueError('Clock cannot move backwards; reset first')
            c.execute('UPDATE sessions SET time_ms=? WHERE id=?',(ms,sid))
            # Do not evaluate missing confirmation while relevant input jobs are unfinished.
            busy=c.execute("SELECT 1 FROM jobs j JOIN events e ON e.session_id=j.session_id AND e.generation=j.generation AND e.event_id=j.event_id JOIN sessions s ON s.id=j.session_id WHERE j.session_id=? AND j.generation=? AND e.time_ms<=s.time_ms AND j.status NOT IN ('done','cancelled') LIMIT 1",(sid,gen)).fetchone()
            if busy: return
            for w in c.execute("SELECT * FROM watches WHERE session_id=? AND generation=? AND due_ms<=? AND assessment IN ('checking','accepted')",(sid,gen,ms)).fetchall():
                self.publish(c,sid,gen,w['task_ref'],'no_confirmation',json.loads(w['evidence']))
                c.execute("UPDATE watches SET assessment='no_confirmation',published=1 WHERE session_id=? AND generation=? AND task_ref=?",(sid,gen,w['task_ref']))
    def recent_context(self, event):
        with self.tx() as c:
            rows = c.execute("SELECT body FROM events WHERE session_id=? AND generation=? AND time_ms>=? AND time_ms<? AND json_extract(body,'$.source_id')=? ORDER BY time_ms DESC,event_id LIMIT 20",
                             (event.session_id,event.generation,max(0,event.time_ms-60000),event.time_ms,event.source_id)).fetchall()
            result=[];size=0
            for row in rows:
                item=compact_event(Event.model_validate_json(row['body']))
                if item.source_id != event.source_id:continue
                size+=len(item.model_dump_json())
                if size>24000:break
                result.append(item)
            return list(reversed(result))

    def events(self,sid,gen,limit=20):
        with self.tx() as c:
            self.require(c,sid,gen)
            rows=c.execute('SELECT body FROM events WHERE session_id=? AND generation=? ORDER BY time_ms DESC,event_id LIMIT ?',(sid,gen,limit)).fetchall()
            result=[]; size=0
            for row in reversed(rows):
                size+=len(row['body'])
                if size>24000: break
                result.append(Event.model_validate_json(row['body']))
            return result
    def state(self,sid,gen):
        with self.tx() as c:
            session=dict(self.require(c,sid,gen))
            data={name:[dict(r) for r in c.execute(f'SELECT * FROM {name} WHERE session_id=? AND generation=?',(sid,gen))] for name in ('watches','jobs','outbox')}
            return {'session':session,**data}
