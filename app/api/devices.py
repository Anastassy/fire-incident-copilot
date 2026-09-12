from fastapi import APIRouter

# Owner: Agent B. GET /devices (filters: type, location, status), GET /devices/{id}.
router = APIRouter(prefix="/devices", tags=["devices"])
