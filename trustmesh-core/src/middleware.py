"""Security middleware — rate limit headers + proxy secret validation."""

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# C2: Proxy shared secret — Python rejects direct access when set.
# Must match PODOS_PROXY_SECRET env var set for the Zig server.
PROXY_SECRET = os.getenv("PODOS_PROXY_SECRET", "")

# Paths exempt from proxy secret check (health + well-known)
_PROXY_EXEMPT = ("/health", "/.well-known/")


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """Add rate limit headers to 429 responses and query endpoints."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Add Retry-After to 429 responses
        if response.status_code == 429:
            response.headers["Retry-After"] = "60"

        return response


class ProxySecretMiddleware(BaseHTTPMiddleware):
    """Reject requests that don't include the correct proxy secret header.

    When PODOS_PROXY_SECRET is set, all requests must come through the Zig
    HTTP server (which injects X-Internal-Proxy-Secret). Direct access to
    the Python backend on :9000 is blocked.

    Exempt: /health (monitoring) and /.well-known/* (federation discovery).
    """

    async def dispatch(self, request: Request, call_next):
        if not PROXY_SECRET:
            # No secret configured — allow all (dev mode)
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in _PROXY_EXEMPT):
            return await call_next(request)

        header_secret = request.headers.get("x-internal-proxy-secret", "")
        if not hmac.compare_digest(PROXY_SECRET, header_secret):
            return JSONResponse(
                {"detail": "Direct backend access forbidden"},
                status_code=403,
            )

        return await call_next(request)
