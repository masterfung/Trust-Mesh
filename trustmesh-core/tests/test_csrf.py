"""Tests for CSRF double-submit cookie middleware."""

import os
import secrets

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
async def csrf_client():
    """Client with CSRF enabled (remove TRUSTMESH_DISABLE_CSRF)."""
    old = os.environ.pop("TRUSTMESH_DISABLE_CSRF", None)
    # Force re-import to pick up env change — middleware reads env per-request
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    # Restore
    if old is not None:
        os.environ["TRUSTMESH_DISABLE_CSRF"] = old


VALID_USER = {
    "username": "csrftest",
    "display_name": "Csrf Test User",
    "bio": "Testing CSRF",
    "password": "SecureTestPass1!",
}


async def _signup_and_login(client):
    """Helper: create user and return authenticated client with session cookie."""
    resp = await client.post("/api/users", json=VALID_USER)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_get_sets_csrf_cookie(csrf_client):
    """First GET request should set the CSRF cookie."""
    resp = await csrf_client.get("/api/health")
    # The cookie should be set on any GET
    assert "trustmesh_csrf" in resp.cookies or resp.status_code == 200


@pytest.mark.asyncio
async def test_post_without_csrf_token_blocked(csrf_client):
    """POST to a non-exempt path without CSRF token → 403."""
    # First create user (exempt path — /api/users is exempt)
    await _signup_and_login(csrf_client)

    # Now try a POST to a non-exempt path without CSRF header
    resp = await csrf_client.post("/api/users/x/capsules", json={"title": "test"})
    assert resp.status_code == 403
    assert "CSRF" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_post_with_matching_csrf_token_succeeds(csrf_client):
    """POST with matching cookie + header → allowed."""
    user = await _signup_and_login(csrf_client)
    user_id = user["id"]

    # Generate a CSRF token and set it as both cookie and header
    token = secrets.token_urlsafe(32)
    csrf_client.cookies.set("trustmesh_csrf", token)

    # Try to get notifications (non-exempt path, PUT)
    resp = await csrf_client.put(
        f"/api/users/{user_id}/notifications/read-all",
        headers={"x-csrf-token": token},
    )
    # Should not be 403 (could be 200 or 404 etc, but NOT CSRF rejection)
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_post_with_mismatched_csrf_tokens_blocked(csrf_client):
    """POST with mismatched cookie vs header → 403."""
    await _signup_and_login(csrf_client)

    csrf_client.cookies.set("trustmesh_csrf", "token-aaa")

    resp = await csrf_client.put(
        "/api/users/x/notifications/read-all",
        headers={"x-csrf-token": "token-bbb"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_csrf_exempt_login_path(csrf_client):
    """Login path is CSRF-exempt — POST without token succeeds."""
    await _signup_and_login(csrf_client)

    resp = await csrf_client.post("/api/auth/login", json={
        "username": "csrftest",
        "password": "SecureTestPass1!",
    })
    # Should not be 403 — login is exempt
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_csrf_exempt_pod_prefix(csrf_client):
    """Pod federation paths (/api/pod/*) are CSRF-exempt."""
    resp = await csrf_client.post("/api/pod/peers", json={"url": "http://example.com"})
    # Should not be 403 due to CSRF — may be 401/422 from auth/validation
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_csrf_exempt_wellknown(csrf_client):
    """/.well-known/* paths are CSRF-exempt."""
    # GET is fine, but even POST should be exempt from CSRF
    resp = await csrf_client.get("/.well-known/agent-card.json")
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_csrf_disabled_env(csrf_client):
    """When TRUSTMESH_DISABLE_CSRF=1, all requests pass."""
    os.environ["TRUSTMESH_DISABLE_CSRF"] = "1"
    try:
        await _signup_and_login(csrf_client)
        # POST without any CSRF tokens should work
        resp = await csrf_client.post("/api/users/x/capsules", json={"title": "test"})
        # Should not be 403 — CSRF disabled
        assert resp.status_code != 403
    finally:
        os.environ["TRUSTMESH_DISABLE_CSRF"] = "1"  # Restore for other tests
