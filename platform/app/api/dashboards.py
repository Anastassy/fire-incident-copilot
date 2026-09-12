from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.dashboard import DashboardSpec
from app.schemas.dashboard import DashboardOut
from app.services.dashboard_service import get_dashboard, list_dashboards

# Owner: Agent B. GET /dashboards, GET /dashboards/{id} (dashboard-facing read-only).
# Writes (create/update) are MCP-only, implemented by Agent C in app/mcp/dashboard_writer.py.
router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _to_out(dashboard: DashboardSpec) -> DashboardOut:
    row = {
        c.key: (str(value) if isinstance(value := getattr(dashboard, c.key), UUID) else value)
        for c in inspect(dashboard).mapper.column_attrs
    }
    return DashboardOut.model_validate(row)


@router.get("", response_model=list[DashboardOut])
async def get_dashboards(
    session: AsyncSession = Depends(get_session),
) -> list[DashboardOut]:
    dashboards = await list_dashboards(session)
    return [_to_out(dashboard) for dashboard in dashboards]


@router.get("/{dashboard_id}", response_model=DashboardOut)
async def get_dashboard_by_id(
    dashboard_id: str,
    session: AsyncSession = Depends(get_session),
) -> DashboardOut:
    dashboard = await get_dashboard(session, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return _to_out(dashboard)
