from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Shared-secret auth for the dashboard (REST/SSE) and agent (MCP) interfaces.

    Hackathon-scope: one static key for every caller, checked via the `X-API-Key` header.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        if request.headers.get("x-api-key") != settings.api_key:
            return JSONResponse({"detail": "Invalid or missing X-API-Key"}, status_code=401)

        return await call_next(request)
