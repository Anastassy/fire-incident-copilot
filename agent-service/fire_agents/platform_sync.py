"""Explicit replay scope; re-read the window to include late arrivals."""
import asyncio
import json
import os
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from .platform import Reader, connect
from .store import StaleGeneration


class SyncScope(BaseModel):
    session_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    device_ids: list[str] = Field(min_length=1)
    since: datetime
    until: datetime
    epoch: datetime
    poll_seconds: float = Field(default=5, ge=1, le=300)

    @model_validator(mode='after')
    def validate_window(self):
        if any(t.tzinfo is None for t in (self.since, self.until, self.epoch)):
            raise ValueError('Timezone-aware timestamps are required')
        if not self.epoch <= self.since < self.until:
            raise ValueError('Expected epoch <= since < until')
        if len(set(self.device_ids)) != len(self.device_ids) or not all(self.device_ids):
            raise ValueError('Device IDs must be nonempty and unique')
        return self


class PlatformSync:
    def __init__(self, store, ui, scope, url, api_key, connector=connect):
        self.store, self.ui, self.scope = store, ui, scope
        self.url, self.api_key, self.connector = url, api_key, connector
        self.status = {'configured': True, 'connected': False, 'state': 'starting'}

    async def reconcile(self, tools):
        s = self.scope
        with self.store.tx() as c:
            self.store.require(c, s.session_id, s.generation)
        self.ui.bind_context(s.session_id, s.generation, subject='platform', device_ids=s.device_ids)
        results = []
        for device in s.device_ids:
            results.append(await Reader(tools, self.store).pull(
                session_id=s.session_id, generation=s.generation, device_id=device,
                since=s.since.isoformat(), until=s.until.isoformat(), epoch=s.epoch.isoformat(), limit=500))
        self.status = {'configured': True, 'connected': True, 'state': 'polling',
                       'received': sum(r['received'] for r in results),
                       'inserted': sum(r['inserted'] for r in results),
                       'possibly_truncated': any(r['possibly_truncated'] for r in results),
                       'coverage_complete': False}
        return self.status

    async def run(self):
        while True:
            try:
                async with self.connector(self.url, self.api_key) as tools:
                    while True:
                        await self.reconcile(tools)
                        await asyncio.sleep(self.scope.poll_seconds)
            except StaleGeneration:
                self.status.update(connected=False, state='stopped_stale_generation')
                return
            except Exception as exc:
                # No credentials, URLs or response bodies in public health output.
                self.status.update(connected=False, state='retrying', error=type(exc).__name__)
                await asyncio.sleep(self.scope.poll_seconds)


def from_environment(store, ui):
    raw = os.getenv('FIRE_PLATFORM_SCOPE')
    if not raw:
        return None
    scope = SyncScope.model_validate(json.loads(raw))
    return PlatformSync(store, ui, scope, os.environ['FIRE_PLATFORM_URL'],
                        os.environ['FIRE_PLATFORM_API_KEY'])
