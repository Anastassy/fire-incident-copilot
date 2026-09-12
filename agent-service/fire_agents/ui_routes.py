import asyncio
import hmac
import os
import uuid
from fastapi import APIRouter, Depends, Query as QueryParam, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyCookie
from . import ui_models as m
from .ui_service import UIError

def install_ui_routes(app,service):
    cookie = APIKeyCookie(name='fire_ui_session',scheme_name='UiSession',auto_error=False)
    def authorize(request:Request,session_cookie:str|None=Depends(cookie)):
        expected=os.getenv('FIRE_UI_SESSION_TOKEN')
        if expected and not hmac.compare_digest(session_cookie or '',expected):
            raise UIError(401,'UNAUTHORIZED','A valid UI session is required.')
    def context(demo_context_id:str,generation:int=QueryParam(ge=0),subject_id:str=QueryParam(min_length=1)):
        return m.Context(demo_context_id=demo_context_id,generation=generation,subject_id=subject_id)
    router=APIRouter(prefix='/agent/v1',dependencies=[Depends(authorize)],responses={code:{'model':m.Error} for code in (401,403,404,409,422,503)})
    @router.post('/questions',response_model=m.Answer,status_code=202)
    def create(body:m.QuestionCreate):return service.submit(body)
    @router.get('/questions/{request_id}',response_model=m.Answer)
    def answer(request_id:str,ctx:m.Context=Depends(context)):return service.get_answer(ctx,request_id)
    @router.post('/questions/{request_id}/cancel',response_model=m.Answer)
    def cancel(request_id:str,ctx:m.Context=Depends(context)):return service.cancel(ctx,request_id)
    @router.get('/cards/{hypothesis_id}',response_model=m.Card)
    def card(hypothesis_id:str,ctx:m.Context=Depends(context)):return service.get_card(ctx,hypothesis_id)
    @router.get('/evidence/{evidence_id}',response_model=m.Evidence)
    def evidence(evidence_id:str,ctx:m.Context=Depends(context)):return service.evidence(ctx,evidence_id)
    @router.get('/state',response_model=m.Snapshot)
    def state(ctx:m.Context=Depends(context)):return service.snapshot(ctx)
    @router.get('/events',responses={200:{'content':{'text/event-stream':{}}}})
    async def events(request:Request,ctx:m.Context=Depends(context)):
        # Reject stale/forbidden contexts before HTTP 200 begins.
        service.snapshot(ctx)
        return StreamingResponse(service.notifications(ctx,request.is_disconnected),media_type='text/event-stream',
                                 headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    app.include_router(router)
