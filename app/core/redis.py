import redis.asyncio as redis

from app.core.config import settings

redis_client = redis.from_url(settings.redis_url, decode_responses=True)

TELEMETRY_CHANNEL = "telemetry:events"
INCIDENTS_CHANNEL = "incidents:events"
DASHBOARDS_CHANNEL = "dashboards:events"
