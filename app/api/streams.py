from fastapi import APIRouter

# Owner: Agent B. SSE endpoints bridging Redis pub/sub to the dashboard app:
#   GET /stream/telemetry, GET /stream/incidents, GET /stream/dashboards/{id}
router = APIRouter(prefix="/stream", tags=["streams"])
