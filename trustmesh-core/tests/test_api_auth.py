"""Tests for the API auth endpoints (login, logout, me) using FastAPI TestClient."""

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
    """Create an async test client."""
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


VALID_USER = {
    "username": "testauth",
    "display_name": "Test Auth User",
    "bio": "Testing auth",
    "password": "SecureTestPass1!",
}


@pytest.mark.asyncio
async def test_signup_sets_cookie(client):
    resp = await client.post("/api/users", json=VALID_USER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testauth"
    assert "trustmesh_session" in resp.cookies


@pytest.mark.asyncio
async def test_signup_then_me(client):
    resp = await client.post("/api/users", json=VALID_USER)
    assert resp.status_code == 200

    # Cookie persists on the client instance (avoid per-request cookies=... which is deprecated in httpx)
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "testauth"


@pytest.mark.asyncio
async def test_login_correct_password(client):
    # Signup first
    await client.post("/api/users", json=VALID_USER)

    # Login
    resp = await client.post("/api/auth/login", json={
        "username": "testauth",
        "password": "SecureTestPass1!",
    })
    assert resp.status_code == 200
    assert resp.json()["username"] == "testauth"
    assert "trustmesh_session" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/users", json=VALID_USER)
    resp = await client.post("/api/auth/login", json={
        "username": "testauth",
        "password": "WrongPassword123!",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    resp = await client.post("/api/auth/login", json={
        "username": "nobody",
        "password": "DoesntMatter123!",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_without_cookie(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_session(client):
    # Signup
    await client.post("/api/users", json=VALID_USER)

    # Logout
    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "ok"

    # Session should be invalid now
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 401


@pytest.mark.asyncio
async def test_signup_weak_password_rejected(client):
    resp = await client.post("/api/users", json={
        "username": "weakuser",
        "display_name": "Weak",
        "bio": "",
        "password": "nouppercase12345!",
    })
    assert resp.status_code == 422  # Validation error
    assert "uppercase" in resp.text


@pytest.mark.asyncio
async def test_signup_duplicate_username(client):
    await client.post("/api/users", json=VALID_USER)
    resp = await client.post("/api/users", json=VALID_USER)
    assert resp.status_code == 400
    assert "already taken" in resp.text


@pytest.mark.asyncio
async def test_signup_no_token_in_response_body(client):
    """httpOnly cookie auth: token must NOT appear in response JSON."""
    resp = await client.post("/api/users", json=VALID_USER)
    data = resp.json()
    assert "token" not in data
    assert "session" not in data
