"""Tests for morning briefing route."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
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


VALID_USER = {
    "username": "brieftest",
    "display_name": "Brief Test User",
    "bio": "Testing briefing",
    "password": "SecureTestPass1!",
}


async def _signup(client):
    resp = await client.post("/api/users", json=VALID_USER)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_briefing_auth_enforcement(client):
    """Can't get briefing for another user."""
    user = await _signup(client)
    resp = await client.get("/api/users/other-user-id/briefing")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_briefing_unauthenticated(client):
    """Unauthenticated request → 401."""
    resp = await client.get("/api/users/any-id/briefing")
    assert resp.status_code == 401


@pytest.mark.asyncio
@patch("src.routes.briefing.generate_briefing", new_callable=AsyncMock)
async def test_briefing_returns_text(mock_gen, client):
    """Briefing endpoint returns generated text."""
    mock_gen.return_value = "Good morning! Here's your daily briefing."
    user = await _signup(client)
    uid = user["id"]

    resp = await client.get(f"/api/users/{uid}/briefing")
    assert resp.status_code == 200
    data = resp.json()
    assert "briefing" in data
    assert data["user_id"] == uid
    assert "Good morning" in data["briefing"]


@pytest.mark.asyncio
@patch("src.routes.briefing.generate_briefing", new_callable=AsyncMock)
async def test_briefing_cache_within_ttl(mock_gen, client):
    """Second request within TTL returns cached briefing."""
    mock_gen.return_value = "Cached briefing text."
    user = await _signup(client)
    uid = user["id"]

    resp1 = await client.get(f"/api/users/{uid}/briefing")
    assert resp1.status_code == 200

    resp2 = await client.get(f"/api/users/{uid}/briefing")
    assert resp2.status_code == 200
    assert resp2.json()["briefing"] == "Cached briefing text."
    # generate_briefing should only be called once (cached on second call)
    assert mock_gen.call_count == 1


@pytest.mark.asyncio
@patch("src.routes.briefing.generate_briefing", new_callable=AsyncMock)
async def test_briefing_response_schema(mock_gen, client):
    """Response matches BriefingResponse schema."""
    mock_gen.return_value = "Schema test briefing."
    user = await _signup(client)
    uid = user["id"]

    resp = await client.get(f"/api/users/{uid}/briefing")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert "briefing" in data
    assert "generated_at" in data
    # Verify generated_at is a valid datetime
    datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_briefing_nonexistent_user(client):
    """Briefing for non-existent user returns error."""
    user = await _signup(client)
    # Use the auth session but request a different user's briefing
    resp = await client.get(f"/api/users/{user['id']}xxx/briefing")
    assert resp.status_code == 403  # Auth check fails first
