from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from app.core.redis import (
    DASHBOARDS_CHANNEL,
    INCIDENTS_CHANNEL,
    TELEMETRY_CHANNEL,
    redis_client,
)

# Owner: Agent B. SSE endpoints bridging Redis pub/sub to the dashboard app:
#   GET /stream/telemetry, GET /stream/incidents, GET /stream/dashboards/{id}
router = APIRouter(prefix="/stream", tags=["streams"])


async def _event_stream(channel: str, request: Request) -> AsyncGenerator[str, None]:
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if await request.is_disconnected():
                break
            if message["type"] != "message":
                # skip the initial subscribe-confirmation message
                continue
            yield f"data: {message['data']}\n\n"
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@router.get("/telemetry")
async def stream_telemetry(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(TELEMETRY_CHANNEL, request), media_type="text/event-stream"
    )


@router.get("/incidents")
async def stream_incidents(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(INCIDENTS_CHANNEL, request), media_type="text/event-stream"
    )


@router.get("/dashboards/{dashboard_id}")
async def stream_dashboard(dashboard_id: str, request: Request) -> StreamingResponse:
    # MVP simplification: DASHBOARDS_CHANNEL is not partitioned per-dashboard, so this
    # subscribes to the shared channel and relays every dashboard event as-is; the
    # dashboard_id path segment is accepted for a stable per-dashboard URL but filtering
    # to events relevant to this dashboard_id is left to the client.
    return StreamingResponse(
        _event_stream(DASHBOARDS_CHANNEL, request), media_type="text/event-stream"
    )
