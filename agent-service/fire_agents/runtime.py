from .models import Answer
from .store import StaleGeneration

class Runtime:
    def __init__(self, store, engine, timeout_ms=300000):
        self.store, self.engine, self.timeout_ms = store, engine, timeout_ms
    async def step(self):
        job = self.store.claim_job()
        if not job: return False
        try:
            event = job['event']
            if hasattr(self.engine, 'extract_with_context'):
                context = self.store.recent_context(event)
                result = await self.engine.extract_with_context(event, context)
            else:
                result = await self.engine.extract(event)
            self.store.finish(job, result, self.timeout_ms)
        except StaleGeneration:
            pass  # reset has already cancelled the old task
        except Exception as exc:
            self.store.fail(job, exc)
        return True
    async def answer(self, sid, generation, question):
        events=self.store.events(sid,generation)
        result=Answer.model_validate(await self.engine.answer(question,events))
        allowed={e.event_id for e in events}
        if any(not set(c.evidence_ids)<=allowed for c in result.claims):
            raise ValueError('Answer references unknown evidence')
        # Recheck generation after an asynchronous model invocation.
        self.store.state(sid,generation)
        result.limitations.append('Ответ основан на ограниченной выборке до 20 событий; полнота истории не гарантирована.')
        return {'answer':result.model_dump(),'sources':[e.model_dump() for e in events]}
