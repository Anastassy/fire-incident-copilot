from fastapi import APIRouter

# Owner: Agent A. Implement POST /ingest/telemetry (single event or list[TelemetryIn]):
#   - upsert device via device_service.upsert_from_telemetry
#   - write reading via telemetry_service.write_reading
#   - publish to Redis TELEMETRY_CHANNEL
router = APIRouter(prefix="/ingest", tags=["ingestion"])
