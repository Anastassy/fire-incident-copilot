"""Conservative, replayable linking of extracted radio-channel facts.

Only a unique recent exchange on the same source can supply missing context.
The model extracts an utterance; this reducer owns correlation and state.
"""
import json
import re
import uuid


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').casefold())


def _new_check(session_id, generation, row, team, *, standalone=False):
    ref = 'channel:' + str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
        [session_id, generation, row['source_id'], row['event_id']])))
    limitations = []
    if not team:
        limitations.append('The requesting or assigned group is unidentified; this label does not establish a shared crew.')
    if standalone:
        limitations.append('This reported assignment is not linked to a preceding request.')
    return dict(task_ref=ref, source_id=row['source_id'], team=team or 'Unidentified group',
                team_identified=bool(team), request_event_id=None if standalone else row['event_id'],
                standalone_assignment=standalone, correlation_limitations=limitations,
                channel=None, assignment=None, acknowledgement=None, evidence=[], last_ms=row['time_ms'])


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
    rebuild(c, event.session_id, event.generation)


def rebuild(c, session_id, generation):
    """Rebuild derived checks from stored extracted facts without rewriting source events."""
    # Rebuild in event order so delayed delivery has the same result as replay.
    checks = []
    rows = c.execute('SELECT * FROM channel_facts WHERE session_id=? AND generation=? ORDER BY time_ms,event_id',
                     (session_id, generation)).fetchall()
    for row in rows:
        fact = json.loads(row['body'])
        action, team, channel = fact['action'], fact['team'], fact['channel']
        team = team.strip() if isinstance(team, str) and team.strip() else None
        candidates = [x for x in checks if x['source_id'] == row['source_id']
                      and 0 <= row['time_ms'] - x['last_ms'] <= 60000
                      and (not team or (x['team_identified'] and normalized(team) == normalized(x['team'])))]
        if action == 'channel_requested':
            # A shared placeholder is never evidence that two callers are the same crew.
            pending = [x for x in candidates if not x['channel']] if team else []
            if len(pending) == 1:
                check = pending[0]
            else:
                check = _new_check(session_id, generation, row, team)
                checks.append(check)
        elif action == 'channel_assigned':
            if not channel:
                continue
            pending = [x for x in candidates if not x['channel']]
            if len(pending) == 1:
                check = pending[0]
            elif not pending or all(not x['team_identified'] for x in pending):
                # Preserve an unattributed assignment as its own report. Do not silently
                # choose one of several anonymous requests or transfer their evidence.
                check = _new_check(session_id, generation, row, team, standalone=True)
                checks.append(check)
            else:
                # Several explicitly named groups remain ambiguous; none receives it.
                continue
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
            check['correlation_limitations'] = list(dict.fromkeys(check['correlation_limitations'] +
                ['Reply linked by channel and timing on this source; speaker identity is not established.']))
        else:
            continue
        check['last_ms'] = row['time_ms']
        check['evidence'] = list(dict.fromkeys(check['evidence'] + fact['claim']['evidence_ids']))
    c.execute("DELETE FROM watches WHERE session_id=? AND generation=? AND task_ref IN (SELECT task_ref FROM channel_checks WHERE session_id=? AND generation=?)",
              (session_id, generation, session_id, generation))
    c.execute('DELETE FROM channel_checks WHERE session_id=? AND generation=?', (session_id, generation))
    for check in checks:
        assessment = 'supported_by_report' if check['acknowledgement'] else 'checking'
        c.execute('INSERT INTO channel_checks VALUES (?,?,?,?)',
                  (session_id, generation, check['task_ref'], json.dumps(check)))
        # Channel checks have no completion deadline and do not use task-completion publication.
        c.execute('INSERT OR REPLACE INTO watches VALUES (?,?,?,?,?,?,?,?,?)',
                  (session_id, generation, check['task_ref'], check['team'], assessment,
                   check['last_ms'], 9223372036854775807, json.dumps(check['evidence']), 0))
