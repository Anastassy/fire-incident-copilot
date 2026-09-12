import asyncio
import hmac
import os
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .models import Event, Question, ClockUpdate
from .store import Store, StaleGeneration
from .engines import FixtureEngine, SDKEngine
from .runtime import Runtime
from .ui_service import UIService, UIError
from .ui_routes import install_ui_routes
from .platform_sync import from_environment

def create_app(db_path=None, engine=None, background=True):
    path=Path(db_path or os.getenv('FIRE_DB_PATH','work/runtime.sqlite3'))
    path.parent.mkdir(parents=True,exist_ok=True)
    store=Store(path)
    mode=os.getenv('FIRE_ENGINE','fixture')
    if mode not in ('fixture','sdk'):raise ValueError('FIRE_ENGINE must be fixture or sdk')
    selected=engine or (FixtureEngine() if mode=='fixture' else SDKEngine(os.environ['FIRE_MODEL']))
    event_workers=int(os.getenv('FIRE_EVENT_WORKERS','1'))
    if not 1 <= event_workers <= 8:raise ValueError('FIRE_EVENT_WORKERS must be between 1 and 8')
    runtime=Runtime(store,selected,int(os.getenv('FIRE_WATCH_TIMEOUT_MS','300000')))
    ui=UIService(runtime)
    platform_sync=from_environment(store,ui)
    async def worker():
        while True:
            worked=await runtime.step()
            with store.tx() as c:
                sessions=[dict(r) for r in c.execute('SELECT * FROM sessions')]
            for session in sessions:
                try:store.tick(session['id'],session['generation'])
                except StaleGeneration:pass
            await asyncio.sleep(.05 if worked else .2)
    async def question_worker():
        while True:
            worked=await ui.process_one()
            await asyncio.sleep(.05 if worked else .2)
    @asynccontextmanager
    async def lifespan(app):
        tasks=([asyncio.create_task(worker()) for _ in range(event_workers)]+[asyncio.create_task(question_worker())]) if background else []
        if background and platform_sync:
            store.start(platform_sync.scope.session_id)
            tasks.append(asyncio.create_task(platform_sync.run()))
        app.state.workers=tasks
        try:yield
        finally:
            for task in tasks:task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):await task
    app=FastAPI(title='Fire agent runtime',version='0.2.0',lifespan=lifespan)
    app.state.runtime=runtime;app.state.ui=ui
    # Protect legacy/demo endpoints as well when the shared demo cookie is configured.
    @app.middleware('http')
    async def guard(request,call_next):
        expected=os.getenv('FIRE_UI_SESSION_TOKEN')
        if expected and request.url.path not in ('/health',) and not hmac.compare_digest(request.cookies.get('fire_ui_session',''),expected):
            return JSONResponse(status_code=401,content={'code':'UNAUTHORIZED','message':'A valid UI session is required.','retryable':False,'request_id':str(uuid.uuid4())})
        return await call_next(request)
    @app.exception_handler(UIError)
    async def ui_error(request,exc):return JSONResponse(status_code=exc.status,content=exc.body.model_dump())
    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):
        if request.url.path.startswith('/agent/v1'):
            return JSONResponse(status_code=422,content={'code':'INVALID_REQUEST','message':'Request does not match the UI contract.','retryable':False,'request_id':str(uuid.uuid4())})
        return JSONResponse(status_code=422,content={'detail':'Invalid request'})
    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        if request.url.path.startswith('/agent/v1'):
            return JSONResponse(status_code=422,content={'code':'INVALID_REQUEST','message':'Invalid request.','retryable':False,'request_id':str(uuid.uuid4())})
        return JSONResponse(status_code=409 if isinstance(exc,StaleGeneration) else 422,content={'detail':str(exc)})
    @app.get('/health')
    def health():
        failed=[t for t in getattr(app.state,'workers',[]) if t.done() and not t.cancelled() and t.exception()]
        result={'status':'degraded' if failed else 'ok','engine':type(selected).__name__,'platform_connected':bool(platform_sync and platform_sync.status['connected']),
                'platform':platform_sync.status if platform_sync else {'configured':False},
                'ui_api_version':'v1','authentication':'shared-demo-cookie' if os.getenv('FIRE_UI_SESSION_TOKEN') else 'local-only-no-auth'}
        if isinstance(selected,SDKEngine):
            # Report the selected engine, never environment values or client objects.
            result['model_configuration']={
                'provider':selected.provider,
                'primary_model':selected.primary_model,
                'fallback_model':selected.fallback_model,
            }
        return result
    @app.post('/sessions/{sid}')
    def start(sid:str):
        result=store.start(sid);ui.bind_context(sid,result['generation']);return result
    @app.post('/sessions/{sid}/reset')
    def reset(sid:str):
        result=store.reset(sid);ui.bind_context(sid,result['generation']);return result
    @app.post('/events')
    def ingest(event:Event):return {'inserted':store.ingest(event)}
    @app.post('/sessions/{sid}/{generation}/clock')
    def clock(sid:str,generation:int,body:ClockUpdate):
        store.tick(sid,generation,body.time_ms);return store.state(sid,generation)
    @app.get('/sessions/{sid}/{generation}')
    def state(sid:str,generation:int):return store.state(sid,generation)
    @app.post('/agent/questions',deprecated=True)
    async def question(body:Question):
        try:return await runtime.answer(body.session_id,body.generation,body.text)
        except (ValueError,StaleGeneration):raise
        except Exception:raise HTTPException(503,'Model execution unavailable')
    install_ui_routes(app,ui)
    return app
