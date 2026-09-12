"""Explicit extraction doubles test correlation, not live model accuracy."""
import asyncio
import json
import pytest
from fire_agents.models import Event
from fire_agents.engines import FixtureEngine
from fire_agents.runtime import Runtime
from fire_agents.store import Store
from fire_agents.ui_service import UIService
from test_ui import validate


def setup(tmp_path):
    s=Store(tmp_path/'channels.db');s.start('demo')
    r=Runtime(s,FixtureEngine());ui=UIService(r)
    return s,r,ui,ui.bind_context('demo',0)


def event(eid,ms,action,channel=None,team=None,source='radio',reading=True):
    return Event(session_id='demo',generation=0,event_id=eid,time_ms=ms,source_id=source,
        kind='radio',reading_id=int(eid) if reading else None,description=f'Synthetic {action}: {channel or team}',
        payload={'fixture':dict(action=action,channel=channel,team=team)})


def drain(r):
    async def run():
        while await r.step():pass
    asyncio.run(run())


def test_three_phases_and_no_future_extraction(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    for e in [event('1',130420,'channel_requested',team='Coastline'),
              event('2',135760,'channel_assigned','V-Fire 25'),
              event('3',140260,'channel_acknowledged','V-Fire 25')]:s.ingest(e)
    drain(r);assert not s.state('demo',0)['watches']
    cards=[]
    for ms in [130420,135760,140260]:
        s.tick('demo',0,ms);drain(r)
        snapshot=ui.snapshot(ctx);assert len(snapshot.cards)==1
        card=snapshot.cards[0];validate(card.model_dump(),'Card');cards.append(card)
    assert [c.assessment for c in cards]==['insufficient_data','insufficient_data','supported']
    assert len({c.hypothesis_id for c in cards})==1
    assert cards[0].revision<cards[1].revision<cards[2].revision
    assert [ui.evidence(ctx,e).reading_id for e in cards[2].evidence_ids]==[1,2,3]
    assert any('every group member' in x for x in cards[2].unknowns)
    assert not s.state('demo',0)['outbox']


@pytest.mark.parametrize('variant',['omitted','wrong_channel','other_source','too_late','before_assignment','missing_reading'])
def test_unconfirmed_controls(tmp_path,variant):
    s,r,ui,ctx=setup(tmp_path)
    s.ingest(event('1',1000,'channel_requested',team='Coastline'))
    s.ingest(event('2',2000,'channel_assigned','V-Fire 25'))
    if variant!='omitted':
        s.ingest(event('3',40000 if variant=='too_late' else 1500 if variant=='before_assignment' else 3000,
            'channel_acknowledged','V-Fire 26' if variant=='wrong_channel' else 'V-Fire 25',
            source='other' if variant=='other_source' else 'radio',reading=variant!='missing_reading'))
    s.tick('demo',0,50000);drain(r)
    assert ui.snapshot(ctx).cards[0].assessment=='insufficient_data'


def test_ambiguous_exchange_is_not_linked(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    for e in [event('1',1000,'channel_requested',team='Coastline'),
              event('2',1100,'channel_requested',team='Other Group'),
              event('3',2000,'channel_assigned','V-Fire 25'),
              event('4',3000,'channel_acknowledged','V-Fire 25')]:s.ingest(e)
    s.tick('demo',0,3000);drain(r)
    assert len(ui.snapshot(ctx).cards)==2
    assert all(c.assessment=='insufficient_data' for c in ui.snapshot(ctx).cards)


def test_late_delivery_restart_and_reset(tmp_path):
    s,r,ui,ctx=setup(tmp_path);s.tick('demo',0,5000)
    s.ingest(event('1',1000,'channel_requested',team='Coastline'));drain(r)
    first=ui.snapshot(ctx).cards[0]
    s.ingest(event('3',3000,'channel_acknowledged','V-Fire 25'));drain(r)
    assert ui.snapshot(ctx).cards[0].assessment=='insufficient_data'
    restored=Runtime(Store(s.path),FixtureEngine())
    s.ingest(event('2',2000,'channel_assigned','V-Fire 25'));drain(restored)
    final=ui.snapshot(ctx).cards[0]
    assert final.assessment=='supported' and final.hypothesis_id==first.hypothesis_id
    s.reset('demo');assert ui.snapshot(ui.bind_context('demo',1)).cards==[]


def test_context_excludes_future_and_other_source(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    for e in [event('1',1000,'channel_requested',team='Coastline'),
              event('2',1100,'channel_requested',team='Other',source='other'),
              event('3',3000,'channel_acknowledged','V-Fire 25')]:s.ingest(e)
    current=event('4',2000,'channel_assigned','V-Fire 25')
    assert [e.event_id for e in s.recent_context(current)]==['1']


def channel_checks(store):
    with store.tx() as connection:
        return [json.loads(row['body']) for row in connection.execute(
            'SELECT body FROM channel_checks ORDER BY task_ref')]


def test_unidentified_request_remains_visible_without_inventing_identity(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    s.ingest(event('1',1000,'channel_requested'))
    s.tick('demo',0,1000);drain(r)
    card=ui.snapshot(ctx).cards[0]
    assert card.statement.startswith('Unidentified group:')
    assert card.assessment=='insufficient_data'
    assert [ui.evidence(ctx,e).reading_id for e in card.evidence_ids]==[1]
    check=channel_checks(s)[0]
    assert check['team_identified'] is False
    assert check['request_event_id']=='1'
    assert any('does not establish a shared crew' in text for text in check['correlation_limitations'])


def test_unknown_requests_are_never_merged_or_attached_to_ambiguous_assignment(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    for e in [event('1',1000,'channel_requested'), event('2',1500,'channel_requested'),
              event('3',2000,'channel_assigned','V-Fire 25'),
              event('4',3000,'channel_acknowledged','V-Fire 25')]:s.ingest(e)
    s.tick('demo',0,3000);drain(r)
    checks=channel_checks(s)
    assert len(checks)==3
    requests=[check for check in checks if not check['standalone_assignment']]
    assert sorted(check['evidence'] for check in requests)==[['1'],['2']]
    assert all(check['assignment'] is None and check['acknowledgement'] is None for check in requests)
    assignment=next(check for check in checks if check['standalone_assignment'])
    assert assignment['request_event_id'] is None
    assert assignment['evidence']==['3','4']
    assert assignment['team']=='Unidentified group'
    assert any('not linked to a preceding request' in text for text in assignment['correlation_limitations'])
    cards=ui.snapshot(ctx).cards
    assert sorted(card.assessment for card in cards)==['insufficient_data','insufficient_data','supported']
    supported=next(card for card in cards if card.assessment=='supported')
    assert [ui.evidence(ctx,e).reading_id for e in supported.evidence_ids]==[3,4]
    assert any('speaker identity is not established' in text for text in supported.unknowns)


@pytest.mark.parametrize('variant',['matched','wrong_channel','other_source','too_late','same_time'])
def test_standalone_assignment_acknowledgement_keeps_source_channel_and_time_guards(tmp_path,variant):
    s,r,ui,ctx=setup(tmp_path)
    s.ingest(event('1',1000,'channel_assigned','V-Fire 25'))
    s.ingest(event('2',32000 if variant=='too_late' else 1000 if variant=='same_time' else 2000,
        'channel_acknowledged','V-Fire 26' if variant=='wrong_channel' else 'V-Fire 25',
        source='other' if variant=='other_source' else 'radio'))
    s.tick('demo',0,32000);drain(r)
    cards=ui.snapshot(ctx).cards
    assert len(cards)==1
    assert cards[0].statement.startswith('Unidentified group: V-Fire 25 assigned;')
    assert cards[0].assessment==('supported' if variant=='matched' else 'insufficient_data')


def test_two_standalone_assignments_cannot_share_one_acknowledgement(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    for e in [event('1',1000,'channel_assigned','V-Fire 25'),
              event('2',1500,'channel_assigned','V-Fire 25'),
              event('3',2000,'channel_acknowledged','V-Fire 25')]:s.ingest(e)
    s.tick('demo',0,2000);drain(r)
    assert len(ui.snapshot(ctx).cards)==2
    assert all(card.assessment=='insufficient_data' for card in ui.snapshot(ctx).cards)
    assert all(check['acknowledgement'] is None for check in channel_checks(s))


def test_named_reply_does_not_supply_identity_to_an_unknown_assignment(tmp_path):
    s,r,ui,ctx=setup(tmp_path)
    s.ingest(event('1',1000,'channel_assigned','V-Fire 25'))
    s.ingest(event('2',2000,'channel_acknowledged','V-Fire 25',team='Named Crew'))
    s.tick('demo',0,2000);drain(r)
    check=channel_checks(s)[0]
    assert check['team']=='Unidentified group' and check['acknowledgement'] is None


def test_rebuilding_stored_facts_changes_no_events_jobs_or_extractions(tmp_path):
    from fire_agents.channels import rebuild
    s,r,ui,ctx=setup(tmp_path)
    for e in [event('1',1000,'channel_requested'),
              event('2',2000,'channel_assigned','V-Fire 25')]:s.ingest(e)
    s.tick('demo',0,2000);drain(r)
    def original_rows(connection):
        return {table:[tuple(row) for row in connection.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                for table in ('events','jobs','channel_facts')}
    before_checks=channel_checks(s)
    with s.tx() as connection:
        before=original_rows(connection)
        rebuild(connection,'demo',0)
        rebuild(connection,'demo',0)
        assert original_rows(connection)==before
    assert channel_checks(s)==before_checks
