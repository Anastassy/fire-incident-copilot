from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.config import settings
from app.core.db import async_session
from app.ingestion.writer import upsert_device_from_telemetry, write_telemetry_reading
from app.schemas.telemetry import TelemetryIn

# Owner: Agent A. Implement WS /ingest/stream: same TelemetryIn payload per message, same write path as http.py.
router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.websocket("/stream")
async def ingest_stream(websocket: WebSocket):
    if websocket.headers.get("x-api-key") != settings.api_key:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                telemetry_in = TelemetryIn.model_validate_json(raw)
            except ValidationError as exc:
                await websocket.send_json({"status": "error", "detail": str(exc)})
                continue
            except ValueError as exc:
                await websocket.send_json({"status": "error", "detail": str(exc)})
                continue

            try:
                async with async_session() as session:
                    device = await upsert_device_from_telemetry(session, telemetry_in.device)
                    await write_telemetry_reading(session, device.id, telemetry_in)
            except Exception as exc:  # keep the loop alive on unexpected errors
                await websocket.send_json({"status": "error", "detail": str(exc)})
                continue

            await websocket.send_json({"status": "ok"})
    except WebSocketDisconnect:
        pass
