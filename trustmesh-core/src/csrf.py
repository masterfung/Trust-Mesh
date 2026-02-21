"""CSRF protection middleware — double-submit cookie pattern."""

import hmac
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CSRF_COOKIE_NAME = "trustmesh_csrf"
CSRF_HEADER_NAME = "x-csrf-token"

# Paths exempt from CSRF (login, signup, logout, federation, emergency token auth)
CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/users",
    "/api/emergency/access",
}
CSRF_EXEMPT_PREFIXES = (
    "/api/pod/",
    "/.well-known/",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip if dev mode explicitly disables CSRF
        if os.getenv("TRUSTMESH_DISABLE_CSRF"):
            return await call_next(request)

        # Check CSRF on state-mutating methods
        if request.method in ("POST", "PUT", "DELETE"):
            path = request.url.path
            if not self._is_exempt(path):
                cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
                header_token = request.headers.get(CSRF_HEADER_NAME)
                if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
                    return Response(
                        content='{"detail":"CSRF token missing or mismatch"}',
                        status_code=403,
                        media_type="application/json",
                    )

        response = await call_next(request)

        # Set CSRF cookie if not present
        if CSRF_COOKIE_NAME not in request.cookies:
            token = secrets.token_urlsafe(32)
            # Detect dev mode: explicit env var OR localhost request
            is_dev = bool(os.getenv("TRUSTMESH_DEV_MODE")) or "localhost" in request.url.hostname
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=token,
                httponly=False,  # JS must be able to read this
                samesite="lax",  # lax allows same-site cross-port (3050→8000)
                secure=not is_dev,
                max_age=86400,
                path="/",
            )

        return response

    def _is_exempt(self, path: str) -> bool:
        if path in CSRF_EXEMPT_PATHS:
            return True
        for prefix in CSRF_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return True
        return False
