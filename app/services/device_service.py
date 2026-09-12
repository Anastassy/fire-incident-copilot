from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device


async def list_devices(
    session: AsyncSession,
    type: str | None = None,
    location: dict | None = None,
    status: str | None = None,
) -> list[Device]:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP list_devices."""
    raise NotImplementedError


async def get_device(session: AsyncSession, device_id: str) -> Device | None:
    """Owner: Agent B (REST, dashboard-facing). Also backs MCP get_device."""
    raise NotImplementedError
