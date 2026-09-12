from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.device import Device
from app.schemas.device import DeviceOut
from app.services.device_service import get_device, list_devices

# Owner: Agent B. GET /devices (filters: type, location, status), GET /devices/{id}.
router = APIRouter(prefix="/devices", tags=["devices"])


def _to_out(device: Device) -> DeviceOut:
    row = {
        c.key: (str(value) if isinstance(value := getattr(device, c.key), UUID) else value)
        for c in inspect(device).mapper.column_attrs
    }
    return DeviceOut.model_validate(row)


@router.get("", response_model=list[DeviceOut])
async def get_devices(
    type: Optional[str] = None,
    status: Optional[str] = None,
    building: Optional[str] = None,
    floor: Optional[int] = None,
    zone: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
) -> list[DeviceOut]:
    location: dict = {}
    if building is not None:
        location["building"] = building
    if floor is not None:
        location["floor"] = floor
    if zone is not None:
        location["zone"] = zone

    devices = await list_devices(session, type=type, location=location or None, status=status)
    return [_to_out(device) for device in devices]


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device_by_id(
    device_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeviceOut:
    device = await get_device(session, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return _to_out(device)
