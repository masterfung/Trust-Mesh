"""Security middleware — rate limit headers."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """Add rate limit headers to 429 responses and query endpoints."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Add Retry-After to 429 responses
        if response.status_code == 429:
            response.headers["Retry-After"] = "60"

        return response
