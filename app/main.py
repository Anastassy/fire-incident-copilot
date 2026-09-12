from fastapi import FastAPI

from app.api.dashboards import router as dashboards_router
from app.api.devices import router as devices_router
from app.api.incidents import router as incidents_router
from app.api.streams import router as streams_router
from app.api.telemetry import router as telemetry_router
from app.ingestion.http import router as ingestion_http_router
from app.ingestion.ws import router as ingestion_ws_router

app = FastAPI(title="Safety Telemetry Platform")

app.include_router(ingestion_http_router)
app.include_router(ingestion_ws_router)
app.include_router(devices_router)
app.include_router(telemetry_router)
app.include_router(incidents_router)
app.include_router(dashboards_router)
app.include_router(streams_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
