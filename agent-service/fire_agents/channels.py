"""Conservative, replayable linking of extracted radio-channel facts.

Only a unique recent exchange on the same source can supply missing context.
The model extracts an utterance; this reducer owns correlation and state.
"""
import json
import re
import uuid


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').casefold())


def record(c, event, result):
    if event.kind != 'radio' or not result.claim or event.event_id not in result.claim.evidence_ids:
        raise ValueError('Invalid channel evidence')
    for eid in result.claim.evidence_ids:
        source=c.execute('SELECT body,time_ms FROM events WHERE session_id=? AND generation=? AND event_id=?',
                         (event.session_id,event.generation,eid)).fetchone()
        if not source or json.loads(source['body'])['source_id'] != event.source_id or not 0 <= event.time_ms-source['time_ms'] <= 60000:
            raise ValueError('Channel evidence outside current source/time window')
    c.execute('INSERT OR REPLACE INTO channel_facts VALUES (?,?,?,?,?,?)',
              (event.session_id, event.generation, event.event_id, event.time_ms, event.source_id,
               result.model_dump_json()))
    # Rebuild in event order so delayed delivery has the same result as replay.
    checks = []
    rows = c.execute('SELECT * FROM channel_facts WHERE session_id=? AND generation=? ORDER BY time_ms,event_id',
                     (event.session_id, event.generation)).fetchall()
    for row in rows:
        fact = json.loads(row['body'])
        action, team, channel = fact['action'], fact['team'], fact['channel']
        candidates = [x for x in checks if x['source_id'] == row['source_id']
                      and 0 <= row['time_ms'] - x['last_ms'] <= 60000
                      and (not team or normalized(team) == normalized(x['team']))]
        if action == 'channel_requested':
            if not team:
                continue
            pending = [x for x in candidates if not x['channel']]
            if len(pending) == 1:
                check = pending[0]
            else:
                ref = 'channel:' + str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
                    [event.session_id, event.generation, row['source_id'], row['event_id']])) )
                check = dict(task_ref=ref, source_id=row['source_id'], team=team, channel=None,
                             assignment=None, acknowledgement=None, evidence=[], last_ms=row['time_ms'])
                checks.append(check)
        elif action == 'channel_assigned':
            if not channel:
                continue
            pending = [x for x in candidates if not x['channel']]
            if len(pending) != 1:
                continue
            check = pending[0]
            check['channel'] = channel
            check['assignment'] = row['event_id']
            check['assignment_ms'] = row['time_ms']
        elif action == 'channel_acknowledged':
            if not channel:
                continue
            matching = [x for x in candidates if x['assignment']
                        and normalized(x['channel']) == normalized(channel)
                        and 0 < row['time_ms'] - x['assignment_ms'] <= 30000]
            if len(matching) != 1:
                continue
            check = matching[0]
            check['acknowledgement'] = row['event_id']
        else:
            continue
        check['last_ms'] = row['time_ms']
        check['evidence'] = list(dict.fromkeys(check['evidence'] + fact['claim']['evidence_ids']))
    c.execute("DELETE FROM watches WHERE session_id=? AND generation=? AND task_ref IN (SELECT task_ref FROM channel_checks WHERE session_id=? AND generation=?)",
              (event.session_id, event.generation, event.session_id, event.generation))
    c.execute('DELETE FROM channel_checks WHERE session_id=? AND generation=?', (event.session_id, event.generation))
    for check in checks:
        assessment = 'supported_by_report' if check['acknowledgement'] else 'checking'
        c.execute('INSERT INTO channel_checks VALUES (?,?,?,?)',
                  (event.session_id, event.generation, check['task_ref'], json.dumps(check)))
        # Channel checks have no completion deadline and do not use task-completion publication.
        c.execute('INSERT OR REPLACE INTO watches VALUES (?,?,?,?,?,?,?,?,?)',
                  (event.session_id, event.generation, check['task_ref'], check['team'], assessment,
                   check['last_ms'], 9223372036854775807, json.dumps(check['evidence']), 0))
