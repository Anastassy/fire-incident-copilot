from fastapi import APIRouter

# Owner: Agent B. GET /dashboards, GET /dashboards/{id} (dashboard-facing read-only).
# Writes (create/update) are MCP-only, implemented by Agent C in app/mcp/dashboard_writer.py.
router = APIRouter(prefix="/dashboards", tags=["dashboards"])
