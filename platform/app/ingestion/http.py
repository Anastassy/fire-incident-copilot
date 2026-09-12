from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telemetry import _to_out
from app.core.db import get_session
from app.ingestion.writer import upsert_device_from_telemetry, write_telemetry_reading
from app.schemas.telemetry import TelemetryIn, TelemetryOut

# Owner: Agent A. Implement POST /ingest/telemetry (single event or list[TelemetryIn]):
#   - upsert device via device_service.upsert_from_telemetry
#   - write reading via telemetry_service.write_reading
#   - publish to Redis TELEMETRY_CHANNEL
router = APIRouter(prefix="/ingest", tags=["ingestion"])


class TelemetryIngestResult(BaseModel):
    ingested: int
    readings: list[TelemetryOut]


@router.post("/telemetry", response_model=TelemetryIngestResult)
async def ingest_telemetry(
    body: TelemetryIn | list[TelemetryIn],
    session: AsyncSession = Depends(get_session),
):
    items = body if isinstance(body, list) else [body]

    readings = []
    for item in items:
        device = await upsert_device_from_telemetry(session, item.device)
        reading = await write_telemetry_reading(session, device.id, item)
        # Use the same persisted IDs and serialization as GET /telemetry.
        readings.append(_to_out(reading))

    return {"ingested": len(readings), "readings": readings}
