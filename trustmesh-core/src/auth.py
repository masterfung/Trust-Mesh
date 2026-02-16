"""Session management: httpOnly cookie auth with rate limiting.

Session tokens are stored in httpOnly, SameSite=Lax cookies — never
accessible to JavaScript, preventing XSS token theft.
"""

import secrets
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request

# In-memory session store: token → (user_id, created_at)
sessions: dict[str, tuple[str, float]] = {}

# Rate limiting: ip → list of attempt timestamps
_login_attempts: dict[str, list[float]] = defaultdict(list)

SESSION_TTL = 86400  # 24 hours
MAX_LOGIN_ATTEMPTS = 100  # per window (generous for demo scripts)
LOGIN_WINDOW = 300  # 5 minutes

COOKIE_NAME = "trustmesh_session"


def create_session(user_id: str) -> str:
    """Create a new session token for a user."""
    token = secrets.token_urlsafe(32)
    sessions[token] = (user_id, time.time())
    return token


def invalidate_session(token: str) -> None:
    """Remove a session."""
    sessions.pop(token, None)


def invalidate_user_sessions(user_id: str) -> None:
    """Remove all sessions for a user."""
    to_remove = [t for t, (uid, _) in sessions.items() if uid == user_id]
    for t in to_remove:
        del sessions[t]


def validate_session(token: str) -> str | None:
    """Validate a session token. Returns user_id if valid, None otherwise."""
    entry = sessions.get(token)
    if not entry:
        return None
    user_id, created_at = entry
    if time.time() - created_at > SESSION_TTL:
        del sessions[token]
        return None
    return user_id


def check_rate_limit(client_ip: str) -> None:
    """Rate limit login attempts by IP. Raises 429 if exceeded."""
    now = time.time()
    window_start = now - LOGIN_WINDOW
    _login_attempts[client_ip] = [
        t for t in _login_attempts[client_ip] if t > window_start
    ]
    if len(_login_attempts[client_ip]) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(429, "Too many login attempts. Try again in a few minutes.")
    _login_attempts[client_ip].append(now)


def get_session_token(request: Request) -> str | None:
    """Extract session token from httpOnly cookie."""
    return request.cookies.get(COOKIE_NAME)


async def get_current_user_id(request: Request) -> str:
    """FastAPI dependency: extract and validate session from httpOnly cookie."""
    token = get_session_token(request)
    if not token:
        raise HTTPException(401, "Authentication required")
    user_id = validate_session(token)
    if not user_id:
        raise HTTPException(401, "Invalid or expired session")
    return user_id


async def get_optional_user_id(request: Request) -> str | None:
    """FastAPI dependency: optionally extract user_id from cookie."""
    token = get_session_token(request)
    if not token:
        return None
    return validate_session(token)
