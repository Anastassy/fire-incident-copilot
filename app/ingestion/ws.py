from fastapi import APIRouter

# Owner: Agent A. Implement WS /ingest/stream: same TelemetryIn payload per message, same write path as http.py.
router = APIRouter(prefix="/ingest", tags=["ingestion"])
