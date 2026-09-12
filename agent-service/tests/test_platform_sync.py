import asyncio
import pytest
from fire_agents.platform_sync import PlatformSync, SyncScope
from fire_agents.store import Store, StaleGeneration
from fire_agents.runtime import Runtime
from fire_agents.engines import FixtureEngine
from fire_agents.ui_service import UIService


def test_platform_to_web_and_reset(tmp_path):
    store = Store(tmp_path/'db')
    store.start('integration')
    ui = UIService(Runtime(store, FixtureEngine(), 100))
    scope = SyncScope(session_id='integration', generation=0, device_ids=['radio'],
                      since='2026-01-01T00:00:00Z', until='2026-01-01T00:01:00Z', epoch='2026-01-01T00:00:00Z')
    sync = PlatformSync(store, ui, scope, 'unused', 'unused')
    class Tools:
        async def call(self, name, arguments):
            assert name == 'query_telemetry'
            return [dict(id=i, device_id='radio', ts=f'2026-01-01T00:00:0{i}Z',
                         metric_type='radio_audio', transcript=f'report {i}', audio_url='https://example.invalid/clip',
                         payload={}) for i in (2, 1)]
    async def run():
        assert (await sync.reconcile(Tools()))['inserted'] == 2
        assert (await sync.reconcile(Tools()))['inserted'] == 0
        events = store.events('integration', 0)
        assert [e.description for e in events] == ['report 1', 'report 2']
        assert events[0].media_url == 'https://example.invalid/clip'
        store.tick('integration', 0, 2000)
        ctx = ui.bind_context('integration', 0, subject='platform', device_ids=['radio'])
        assert ui.snapshot(ctx).context == ctx
        store.reset('integration')
        with pytest.raises(StaleGeneration):
            await sync.reconcile(Tools())
    asyncio.run(run())


def test_scope_rejects_naive_dates():
    with pytest.raises(ValueError):
        SyncScope(session_id='x', generation=0, device_ids=['radio'],
                  since='2026-01-01T00:00:00', until='2026-01-01T00:01:00', epoch='2026-01-01T00:00:00')
