from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import DashboardSpec
from app.schemas.dashboard import DashboardCreate, DashboardUpdate


async def create_dashboard(session: AsyncSession, dashboard_in: DashboardCreate) -> DashboardSpec:
    """Owner: Agent C. Persist dashboard spec, commit, publish to Redis DASHBOARDS_CHANNEL."""
    raise NotImplementedError


async def update_dashboard(session: AsyncSession, dashboard_id: UUID, dashboard_update: DashboardUpdate) -> DashboardSpec:
    """Owner: Agent C. Apply partial update, bump version, commit, publish to Redis DASHBOARDS_CHANNEL."""
    raise NotImplementedError
