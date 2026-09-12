from fastapi import APIRouter

# Owner: Agent B. GET /telemetry (filters: device_id, metric_type, since, until, limit), GET /telemetry/latest.
router = APIRouter(prefix="/telemetry", tags=["telemetry"])
