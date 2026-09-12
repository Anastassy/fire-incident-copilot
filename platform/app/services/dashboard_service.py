from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import DashboardSpec


async def list_dashboards(session: AsyncSession) -> list[DashboardSpec]:
    """Owner: Agent B (REST, dashboard-facing read). Also backs MCP list_dashboards."""
    stmt = select(DashboardSpec).order_by(DashboardSpec.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_dashboard(session: AsyncSession, dashboard_id: UUID | str) -> DashboardSpec | None:
    """Owner: Agent B (REST, dashboard-facing read). Also backs MCP get_dashboard."""
    try:
        parsed_id = dashboard_id if isinstance(dashboard_id, UUID) else UUID(str(dashboard_id))
    except (ValueError, AttributeError, TypeError):
        return None
    result = await session.execute(select(DashboardSpec).where(DashboardSpec.id == parsed_id))
    return result.scalar_one_or_none()
