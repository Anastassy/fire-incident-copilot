from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.ingestion.writer import upsert_device_from_telemetry, write_telemetry_reading
from app.schemas.telemetry import TelemetryIn

# Owner: Agent A. Implement POST /ingest/telemetry (single event or list[TelemetryIn]):
#   - upsert device via device_service.upsert_from_telemetry
#   - write reading via telemetry_service.write_reading
#   - publish to Redis TELEMETRY_CHANNEL
router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("/telemetry")
async def ingest_telemetry(
    body: TelemetryIn | list[TelemetryIn],
    session: AsyncSession = Depends(get_session),
):
    items = body if isinstance(body, list) else [body]

    count = 0
    for item in items:
        device = await upsert_device_from_telemetry(session, item.device)
        await write_telemetry_reading(session, device.id, item)
        count += 1

    return {"ingested": count}
