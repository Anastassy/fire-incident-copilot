from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import DashboardSpec


async def list_dashboards(session: AsyncSession) -> list[DashboardSpec]:
    """Owner: Agent B (REST, dashboard-facing read). Also backs MCP list_dashboards."""
    raise NotImplementedError


async def get_dashboard(session: AsyncSession, dashboard_id: UUID) -> DashboardSpec | None:
    """Owner: Agent B (REST, dashboard-facing read). Also backs MCP get_dashboard."""
    raise NotImplementedError
