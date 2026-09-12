from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.telemetry import TelemetryReading
from app.schemas.telemetry import TelemetryOut
from app.services.telemetry_service import get_latest_readings, query_telemetry

# Owner: Agent B. GET /telemetry (filters: device_id, metric_type, since, until, limit), GET /telemetry/latest.
router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _to_out(reading: TelemetryReading) -> TelemetryOut:
    row = {
        c.key: (str(value) if isinstance(value := getattr(reading, c.key), UUID) else value)
        for c in inspect(reading).mapper.column_attrs
    }
    return TelemetryOut.model_validate(row)


@router.get("", response_model=list[TelemetryOut])
async def get_telemetry(
    device_id: Optional[UUID] = None,
    metric_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[TelemetryOut]:
    readings = await query_telemetry(
        session,
        device_id=device_id,
        metric_type=metric_type,
        since=since,
        until=until,
        limit=limit,
    )
    return [_to_out(reading) for reading in readings]


@router.get("/latest", response_model=list[TelemetryOut])
async def get_latest_telemetry(
    device_id: Optional[list[UUID]] = Query(default=None),
    type: Optional[str] = None,
    building: Optional[str] = None,
    floor: Optional[int] = None,
    zone: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
) -> list[TelemetryOut]:
    location: dict = {}
    if building is not None:
        location["building"] = building
    if floor is not None:
        location["floor"] = floor
    if zone is not None:
        location["zone"] = zone

    readings = await get_latest_readings(
        session,
        device_ids=device_id,
        type=type,
        location=location or None,
    )
    return [_to_out(reading) for reading in readings]
