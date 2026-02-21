"""Tests for rate limit middleware (Retry-After headers)."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB and auth state for each test."""
    sessions.clear()
    _login_attempts.clear()
    await drop_db()
    await init_db()
    yield
    await drop_db()


@pytest_asyncio.fixture
async def client():
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_normal_response_no_retry_after(client):
    """Non-429 responses should NOT have Retry-After header."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert "retry-after" not in resp.headers


@pytest.mark.asyncio
async def test_401_no_retry_after(client):
    """401 responses should NOT have Retry-After header."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert "retry-after" not in resp.headers


@pytest.mark.asyncio
async def test_404_no_retry_after(client):
    """404 responses should NOT have Retry-After header."""
    resp = await client.get("/api/nonexistent-path-xyz")
    assert resp.status_code in (404, 405)
    assert "retry-after" not in resp.headers


@pytest.mark.asyncio
async def test_429_includes_retry_after(client):
    """429 responses SHOULD have Retry-After: 60 header.

    We test this by triggering rate-limited login attempts.
    """
    from src.auth import MAX_LOGIN_ATTEMPTS
    from src.rate_limit import reset_rate_limits
    reset_rate_limits()

    # Create a user first
    resp = await client.post("/api/users", json={
        "username": "mwtest",
        "display_name": "Middleware Test",
        "bio": "Testing middleware",
        "password": "SecureTestPass1!",
    })
    assert resp.status_code == 200

    # Burn through rate limit with wrong password attempts
    for _ in range(MAX_LOGIN_ATTEMPTS + 5):
        await client.post("/api/auth/login", json={
            "username": "mwtest",
            "password": "WrongPassword!!!",
        })

    # Next attempt should be rate limited
    resp = await client.post("/api/auth/login", json={
        "username": "mwtest",
        "password": "WrongPassword!!!",
    })
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "60"
