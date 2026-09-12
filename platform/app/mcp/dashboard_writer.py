import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import DASHBOARDS_CHANNEL, redis_client
from app.models.dashboard import DashboardSpec
from app.schemas.dashboard import DashboardCreate, DashboardUpdate


def _dashboard_event(dashboard: DashboardSpec) -> str:
    """Full dashboard shape (matches DashboardOut / _dashboard_to_dict in app/mcp/server.py) so
    SSE consumers relaying this verbatim (see app/api/streams.py) get a complete object."""
    return json.dumps(
        {
            "id": dashboard.id,
            "title": dashboard.title,
            "created_by": dashboard.created_by,
            "spec": dashboard.spec,
            "version": dashboard.version,
            "created_at": dashboard.created_at,
            "updated_at": dashboard.updated_at,
        },
        default=str,
    )


async def create_dashboard(session: AsyncSession, dashboard_in: DashboardCreate) -> DashboardSpec:
    """Owner: Agent C. Persist dashboard spec, commit, publish to Redis DASHBOARDS_CHANNEL."""
    dashboard = DashboardSpec(
        title=dashboard_in.title,
        created_by=dashboard_in.created_by,
        spec=dashboard_in.spec,
        version=1,
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)

    await redis_client.publish(DASHBOARDS_CHANNEL, _dashboard_event(dashboard))

    return dashboard


async def update_dashboard(session: AsyncSession, dashboard_id: UUID, dashboard_update: DashboardUpdate) -> DashboardSpec:
    """Owner: Agent C. Apply partial update, bump version, commit, publish to Redis DASHBOARDS_CHANNEL."""
    result = await session.execute(select(DashboardSpec).where(DashboardSpec.id == dashboard_id))
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise ValueError(f"Dashboard {dashboard_id} not found")

    if dashboard_update.title is not None:
        dashboard.title = dashboard_update.title

    if dashboard_update.spec is not None:
        dashboard.spec = dashboard_update.spec

    dashboard.version += 1

    await session.commit()
    await session.refresh(dashboard)

    await redis_client.publish(DASHBOARDS_CHANNEL, _dashboard_event(dashboard))

    return dashboard
