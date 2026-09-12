"""Data Platform v1 boundary. Network access is explicit and never enabled by default."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Protocol
from .adapters import from_platform

class PlatformError(RuntimeError): pass

class Tools(Protocol):
    async def call(self, name: str, arguments: dict): ...

class MCPTools:
    def __init__(self, server): self.server = server
    async def call(self, name, arguments):
        result = await self.server.call_tool(name, arguments)
        if getattr(result, 'is_error', getattr(result, 'isError', False)): raise PlatformError(f'MCP tool failed: {name}')
        value = getattr(result, 'structured_content', getattr(result, 'structuredContent', None))
        if value is None:
            blocks = [block.text for block in result.content if getattr(block, 'type', None) == 'text']
            if len(blocks) != 1: raise PlatformError('Expected one JSON result')
            value = json.loads(blocks[0])
        if isinstance(value, dict) and set(value) == {'result'}: value = value['result']
        return value

@asynccontextmanager
async def connect(url, api_key):
    from agents.mcp import MCPServerStreamableHttp
    # Retrying non-idempotent writes at transport level can duplicate incidents/notes.
    server = MCPServerStreamableHttp(params={'url':url,'headers':{'X-API-Key':api_key}},
        max_retry_attempts=0, client_session_timeout_seconds=15)
    async with server:
        yield MCPTools(server)

class Reader:
    def __init__(self, tools, store): self.tools, self.store = tools, store
    async def pull(self, *, session_id, generation, since, until, epoch,
                   device_id, description_field='description', media_field='audio_url', limit=100):
        """Explicit device/window/epoch; do not infer simulation membership from receive time."""
        if not 1 <= limit <= 500: raise ValueError('limit must be 1..500')
        start, end, origin = (datetime.fromisoformat(x.replace('Z','+00:00')) for x in (since,until,epoch))
        if any(x.tzinfo is None for x in (start,end,origin)) or start >= end:
            raise ValueError('Use timezone-aware dates and a nonempty interval')
        rows=await self.tools.call('query_telemetry',{'device_id':device_id,'since':since,'until':until,'limit':limit})
        if not isinstance(rows,list): raise PlatformError('Telemetry response must be a list')
        events=[]
        for row in rows:
            if row['device_id'] != device_id: raise PlatformError('Unexpected device in result')
            ts=datetime.fromisoformat(row['ts'].replace('Z','+00:00'))
            if ts.tzinfo is None or not start <= ts <= end: raise PlatformError('Unexpected event time')
            payload=row.get('payload') or {}
            description=(row.get('transcript') if description_field == 'description' else None)
            if description is None: description=payload.get(description_field,'')
            url=row.get('audio_url') if media_field == 'audio_url' else None
            if url is None: url=payload.get(media_field)
            if not isinstance(description,str) or (url is not None and not isinstance(url,str)):
                raise PlatformError('Description/media mapping requires strings')
            events.append(from_platform(row,session_id=session_id,generation=generation,
                scenario_time_ms=int((ts-origin).total_seconds()*1000),description=description,media_url=url))
        inserted=sum(self.store.ingest(event) for event in sorted(events, key=lambda e: (e.time_ms, e.event_id)))
        return {'received':len(rows),'inserted':inserted,'possibly_truncated':len(rows)>=limit,
                'coverage_complete':False,
                'limitations':['Platform v1 has no stable pagination or late-arrival cursor.']}

class Publisher:
    """One publisher per database. Ambiguous writes stop that watch until reconciliation."""
    def __init__(self, tools, store):
        self.tools,self.store=tools,store
        with store.tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS platform_links(session_id TEXT,generation INTEGER,task_ref TEXT,incident_id TEXT,PRIMARY KEY(session_id,generation,task_ref))')
            # An interrupted write may have reached the remote service. Never blindly replay.
            c.execute("UPDATE outbox SET status='uncertain' WHERE status='sending'")
    async def step(self):
        with self.store.tx() as c:
            candidates=c.execute("SELECT o.* FROM outbox o JOIN sessions s ON s.id=o.session_id AND s.generation=o.generation WHERE o.status='pending' ORDER BY o.rowid").fetchall()
            row=None
            for candidate in candidates:
                body=json.loads(candidate['body'])
                blocked=any(json.loads(r['body'])['task_ref']==body['task_ref'] for r in c.execute(
                    "SELECT body FROM outbox WHERE session_id=? AND generation=? AND status IN ('uncertain','sending','blocked')",
                    (candidate['session_id'],candidate['generation'])))
                if not blocked: row=dict(candidate);break
            if row is None:return False
            body=json.loads(row['body']);scope=(row['session_id'],row['generation'],body['task_ref'])
            link=c.execute('SELECT incident_id FROM platform_links WHERE session_id=? AND generation=? AND task_ref=?',scope).fetchone()
            incident_id=link['incident_id'] if link else None
            evidence=[]
            for eid in body['evidence_ids']:
                source=c.execute('SELECT body FROM events WHERE session_id=? AND generation=? AND event_id=?',(*scope[:2],eid)).fetchone()
                event=json.loads(source['body']) if source else {}
                if event.get('reading_id') is None:
                    c.execute("UPDATE outbox SET status='blocked' WHERE id=?",(row['id'],));return True
                evidence.append({'reading_id':event['reading_id'],'note':f'event_id={eid}'})
            c.execute("UPDATE outbox SET status='sending' WHERE id=?",(row['id'],))
        try:
            note=json.dumps({'kind':'agent_observation_update','publication_id':row['id'],
                **{k:v for k,v in body.items() if k!='destination'}},ensure_ascii=False)
            if incident_id is None:
                result=await self.tools.call('create_incident',{'type':'other','severity':'low','location':{},
                    'summary':f"Наблюдение за поручением {body['task_ref']}: {body['assessment']}",
                    'evidence':evidence+[{'note':note}]})
                if not isinstance(result,dict) or not result.get('id'):raise PlatformError('Missing created incident ID')
                incident_id=result['id']
                with self.store.tx() as c:
                    c.execute('INSERT INTO platform_links VALUES (?,?,?,?)',(*scope,incident_id))
                # create_incident only supports initial open status.
                if body['platform_status']=='resolved':
                    await self.tools.call('update_incident',{'incident_id':incident_id,'status':'resolved','note':note})
            else:
                current=await self.tools.call('get_incident',{'incident_id':incident_id})
                if not current:raise PlatformError('Linked incident unavailable')
                existing={e.get('reading_id') for e in current.get('evidence',[])}
                for item in evidence:
                    if item['reading_id'] not in existing:
                        await self.tools.call('link_evidence',{'incident_id':incident_id,**item})
                # Keep operator status; only append observations. UI/operator owns closing here.
                await self.tools.call('update_incident',{'incident_id':incident_id,'note':note})
        except Exception:
            with self.store.tx() as c:c.execute("UPDATE outbox SET status='uncertain' WHERE id=?",(row['id'],))
            return True
        with self.store.tx() as c:
            # A reset during the request cannot undo a remote side effect; record it explicitly.
            current=c.execute('SELECT generation FROM sessions WHERE id=?',(row['session_id'],)).fetchone()
            status='sent' if current and current['generation']==row['generation'] else 'sent_obsolete'
            c.execute('UPDATE outbox SET status=? WHERE id=?',(status,row['id']))
        return True
