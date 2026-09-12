from fastapi import APIRouter

# Owner: Agent B. GET /incidents, GET /incidents/{id} (dashboard-facing read-only).
# Writes (create/update/evidence) are MCP-only, implemented by Agent C in app/mcp/incident_writer.py.
router = APIRouter(prefix="/incidents", tags=["incidents"])
