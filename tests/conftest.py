from app.core.config import settings

# Shared-secret auth header required by app.core.security.ApiKeyMiddleware for every
# non-exempt HTTP request. Import this into any test module that builds an AsyncClient
# against `app.main.app`.
AUTH_HEADERS = {"X-API-Key": settings.api_key}
