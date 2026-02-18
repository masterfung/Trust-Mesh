"""Tests for session management, rate limiting, and auth flow."""

import time

from src.auth import (
    MAX_LOGIN_ATTEMPTS,
    SESSION_TTL,
    check_rate_limit,
    create_session,
    invalidate_session,
    invalidate_user_sessions,
    sessions,
    validate_session,
    _login_attempts,
)


def setup_function():
    """Clear session and rate limit state before each test."""
    sessions.clear()
    _login_attempts.clear()


def test_create_session_returns_token():
    token = create_session("user-1")
    assert isinstance(token, str)
    assert len(token) > 20  # urlsafe base64, at least 32 bytes


def test_create_session_stores_entry():
    token = create_session("user-1")
    assert token in sessions
    user_id, created_at = sessions[token]
    assert user_id == "user-1"
    assert isinstance(created_at, float)


def test_validate_session_valid():
    token = create_session("user-1")
    result = validate_session(token)
    assert result == "user-1"


def test_validate_session_invalid_token():
    result = validate_session("nonexistent-token")
    assert result is None


def test_validate_session_expired():
    token = create_session("user-1")
    # Backdate the session past TTL
    sessions[token] = ("user-1", time.time() - SESSION_TTL - 1)
    result = validate_session(token)
    assert result is None
    assert token not in sessions  # Expired session cleaned up


def test_invalidate_session():
    token = create_session("user-1")
    invalidate_session(token)
    assert token not in sessions
    assert validate_session(token) is None


def test_invalidate_session_nonexistent():
    # Should not raise
    invalidate_session("nonexistent-token")


def test_invalidate_user_sessions():
    t1 = create_session("user-1")
    t2 = create_session("user-1")
    t3 = create_session("user-2")
    invalidate_user_sessions("user-1")
    assert t1 not in sessions
    assert t2 not in sessions
    assert t3 in sessions  # Other user's session unaffected


def test_unique_tokens():
    tokens = {create_session("user-1") for _ in range(100)}
    assert len(tokens) == 100  # All unique


def test_rate_limit_allows_normal_usage():
    for _ in range(MAX_LOGIN_ATTEMPTS - 1):
        check_rate_limit("192.168.1.1")  # Should not raise


def test_rate_limit_blocks_excessive_attempts():
    for _ in range(MAX_LOGIN_ATTEMPTS):
        check_rate_limit("192.168.1.2")
    try:
        check_rate_limit("192.168.1.2")
        assert False, "Should have raised HTTPException"
    except Exception as e:
        assert "429" in str(e) or "Too many" in str(e)


def test_rate_limit_per_ip():
    """Different IPs have independent limits."""
    for _ in range(MAX_LOGIN_ATTEMPTS):
        check_rate_limit("10.0.0.1")
    # Different IP should still be fine
    check_rate_limit("10.0.0.2")  # Should not raise
