from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device


async def list_devices(
    session: AsyncSession,
    type: str | None = None,
    location: dict | None = None,
    status: str | None = None,
) -> list[Device]:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP list_devices."""
    stmt = select(Device)
    if type is not None:
        stmt = stmt.where(Device.type == type)
    if status is not None:
        stmt = stmt.where(Device.status == status)
    if location:
        for key, value in location.items():
            stmt = stmt.where(Device.location[key].astext == str(value))
    stmt = stmt.order_by(Device.first_seen_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_device(session: AsyncSession, device_id: str) -> Device | None:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP get_device."""
    try:
        parsed_id = UUID(str(device_id))
    except (ValueError, AttributeError, TypeError):
        return None
    result = await session.execute(select(Device).where(Device.id == parsed_id))
    return result.scalar_one_or_none()
