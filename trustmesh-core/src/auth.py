"""Session management: httpOnly cookie auth with rate limiting.

Session tokens are stored in Zig's in-memory SessionStore (libpodos).
FastAPI request handling stays in Python.
"""

import ctypes
import hashlib
import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

SESSION_TTL = 86400  # 24 hours
MAX_LOGIN_ATTEMPTS = 100
LOGIN_WINDOW = 300  # 5 minutes
COOKIE_NAME = "trustmesh_session"

_zig_initialized = False


def _get_lib():
    from src.timeline_bridge import _get_lib as _tl_get_lib
    return _tl_get_lib()


def _ensure_zig():
    """Ensure Zig session store is initialized (lazy init for tests)."""
    global _zig_initialized
    if not _zig_initialized:
        try:
            lib = _get_lib()
            rc = lib.podos_session_init()
            _zig_initialized = (rc == 0)
        except Exception:
            pass


def _compute_fingerprint(request: Request) -> str:
    """Compute session fingerprint from User-Agent + client IP."""
    ua = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(f"{ua}|{ip}".encode()).hexdigest()


def _init_sessions():
    """Initialize the Zig session store. Called once on startup."""
    global _zig_initialized
    lib = _get_lib()
    rc = lib.podos_session_init()
    if rc != 0:
        raise RuntimeError("Failed to initialize session store")
    _zig_initialized = True


def _deinit_sessions():
    """Destroy the Zig session store. Called on shutdown."""
    global _zig_initialized
    lib = _get_lib()
    lib.podos_session_deinit()
    _zig_initialized = False


class _SessionDict(dict):
    """Dict subclass that syncs with Zig session store.

    On __setitem__: invalidate any existing Zig session (so Python dict wins).
    On clear(): reset the entire Zig session store.
    """

    def __setitem__(self, token, value):
        super().__setitem__(token, value)
        # If this token exists in Zig, invalidate it so Python dict becomes authoritative
        if _zig_initialized:
            try:
                lib = _get_lib()
                tok = token.encode("utf-8")
                lib.podos_session_invalidate(tok, len(tok))
            except Exception:
                pass

    def clear(self):
        super().clear()
        try:
            if _zig_initialized:
                lib = _get_lib()
                lib.podos_session_reset()
        except Exception:
            pass


class _LoginAttempts(defaultdict):
    """Backward-compat wrapper. clear() resets Zig login rate limits too."""

    def __init__(self):
        super().__init__(list)

    def clear(self):
        super().clear()
        # Zig login rate limits are part of the session store reset
        try:
            if _zig_initialized:
                lib = _get_lib()
                lib.podos_session_reset()
        except Exception:
            pass


# Backward-compat exports used by test fixtures
sessions: dict[str, tuple[str, float]] = _SessionDict()
_login_attempts: dict[str, list[float]] = _LoginAttempts()


def create_session(user_id: str, fingerprint: str = "") -> str:
    """Create a new session token for a user."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        uid = user_id.encode("utf-8")
        fp = fingerprint.encode("utf-8")
        out_token = ctypes.create_string_buffer(128)
        # Try fingerprint-aware create first, fall back to original
        try:
            length = lib.podos_session_create_fp(uid, len(uid), fp, len(fp), out_token, 128)
        except AttributeError:
            length = lib.podos_session_create(uid, len(uid), out_token, 128)
        if length > 0:
            token = out_token.raw[:length].decode("ascii")
            # Mirror in Python dict (bypassing __setitem__ to avoid double-inject)
            dict.__setitem__(sessions, token, (user_id, time.time()))
            return token
    # Fallback: Python-only session
    import secrets
    token = secrets.token_urlsafe(32)
    dict.__setitem__(sessions, token, (user_id, time.time()))
    return token


def invalidate_session(token: str) -> None:
    """Remove a session."""
    if _zig_initialized:
        try:
            lib = _get_lib()
            tok = token.encode("utf-8")
            lib.podos_session_invalidate(tok, len(tok))
        except Exception:
            pass
    sessions.pop(token, None)


def invalidate_user_sessions(user_id: str) -> None:
    """Remove all sessions for a user."""
    if _zig_initialized:
        try:
            lib = _get_lib()
            uid = user_id.encode("utf-8")
            lib.podos_session_invalidate_user(uid, len(uid))
        except Exception:
            pass
    to_remove = [t for t, (uid_str, _) in sessions.items() if uid_str == user_id]
    for t in to_remove:
        del sessions[t]


def validate_session(token: str, fingerprint: str = "") -> str | None:
    """Validate a session token. Returns user_id if valid, None otherwise."""
    # Check Zig store first
    if _zig_initialized:
        try:
            lib = _get_lib()
            tok = token.encode("utf-8")
            fp = fingerprint.encode("utf-8")
            out_uid = ctypes.create_string_buffer(128)
            # Try fingerprint-aware validate first, fall back to original
            try:
                length = lib.podos_session_validate_fp(tok, len(tok), fp, len(fp), out_uid, 128)
            except AttributeError:
                length = lib.podos_session_validate(tok, len(tok), out_uid, 128)
            if length > 0:
                return out_uid.raw[:length].decode("utf-8")
        except Exception:
            pass

    # Fallback: Python-side dict (for test-injected sessions / pre-init)
    entry = sessions.get(token)
    if entry:
        uid, created = entry
        if time.time() - created <= SESSION_TTL:
            return uid
        del sessions[token]
    return None


def check_rate_limit(client_ip: str) -> None:
    """Rate limit login attempts by IP. Raises 429 if exceeded."""
    if _zig_initialized:
        lib = _get_lib()
        ip = client_ip.encode("utf-8")
        result = lib.podos_session_check_login_rate(ip, len(ip))
        if result == 0:
            raise HTTPException(429, "Too many login attempts. Try again in a few minutes.")
        return

    # Fallback: Python-side rate limiting
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
    fingerprint = _compute_fingerprint(request)
    user_id = validate_session(token, fingerprint)
    if not user_id:
        raise HTTPException(401, "Invalid or expired session")
    return user_id


async def get_optional_user_id(request: Request) -> str | None:
    """FastAPI dependency: optionally extract user_id from cookie."""
    token = get_session_token(request)
    if not token:
        return None
    fingerprint = _compute_fingerprint(request)
    return validate_session(token, fingerprint)


def record_failed_login(ip: str, username: str) -> None:
    """Audit trail for failed login attempts."""
    log.warning(f"Failed login attempt for '{username}' from {ip}")
