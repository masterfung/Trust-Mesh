"""Tests for the audit log API endpoints (GET /api/users/{id}/audit, GET /api/users/{id}/audit/emergency)."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db, get_db
from src.models import AuditLog
from src.rate_limit import reset_rate_limits


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB and auth state for each test."""
    sessions.clear()
    _login_attempts.clear()
    reset_rate_limits()
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
    "username": "audituser",
    "display_name": "Audit Test User",
    "bio": "Testing audit logs",
    "password": "SecureTestPass1!",
}

SECOND_USER = {
    "username": "otheruser",
    "display_name": "Other User",
    "bio": "Another user",
    "password": "SecureTestPass2!",
}


async def _create_and_login(client: AsyncClient, user_data: dict) -> str:
    """Create a user via signup and return the user id. Client keeps the session cookie."""
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_audit_logs(user_id: str, count: int = 3, event_type: str = "auth") -> None:
    """Insert audit log rows directly into the database for a given user."""
    from src.main import app  # noqa: F811

    async for db in get_db():
        for i in range(count):
            entry = AuditLog(
                actor_user_id=user_id,
                target_user_id=user_id,
                action=f"test_action_{i}",
                event_type=event_type,
                decision="allowed",
            )
            db.add(entry)
        await db.commit()
        break


# ---------- Tests ----------


@pytest.mark.asyncio
async def test_list_audit_logs_empty(client):
    """GET /api/users/{id}/audit returns empty list when no logs exist."""
    user_id = await _create_and_login(client, VALID_USER)

    resp = await client.get(f"/api/users/{user_id}/audit")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_audit_logs_returns_entries(client):
    """GET /api/users/{id}/audit returns seeded audit log entries."""
    user_id = await _create_and_login(client, VALID_USER)
    await _seed_audit_logs(user_id, count=3, event_type="auth")

    resp = await client.get(f"/api/users/{user_id}/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # Verify response shape
    entry = data[0]
    assert "id" in entry
    assert entry["event_type"] == "auth"
    assert entry["decision"] == "allowed"
    assert entry["actor_user_id"] == user_id
    assert entry["target_user_id"] == user_id


@pytest.mark.asyncio
async def test_list_audit_logs_filters_by_event_type(client):
    """GET /api/users/{id}/audit?event_type=emergency filters correctly."""
    user_id = await _create_and_login(client, VALID_USER)

    # Seed a mix of event types
    await _seed_audit_logs(user_id, count=2, event_type="auth")
    await _seed_audit_logs(user_id, count=1, event_type="emergency")

    # Filter for emergency only
    resp = await client.get(f"/api/users/{user_id}/audit", params={"event_type": "emergency"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "emergency"

    # Filter for auth only
    resp = await client.get(f"/api/users/{user_id}/audit", params={"event_type": "auth"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_audit_logs_denied_for_other_user(client):
    """GET /api/users/{other_id}/audit returns 403 when accessing another user's logs."""
    # Create first user (this logs us in as VALID_USER)
    user_id = await _create_and_login(client, VALID_USER)

    # Create second user via a separate client so the first client's cookie is unchanged
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client2:
        other_resp = await client2.post("/api/users", json=SECOND_USER)
        assert other_resp.status_code == 200
        other_id = other_resp.json()["id"]

    # First user tries to access second user's audit logs
    resp = await client.get(f"/api/users/{other_id}/audit")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_audit_logs_unauthenticated(client):
    """GET /api/users/{id}/audit returns 401 without a session."""
    # Use a fake user id -- no login, so should fail auth
    resp = await client.get("/api/users/nonexistent-id/audit")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_emergency_logs_endpoint(client):
    """GET /api/users/{id}/audit/emergency returns only emergency-type entries."""
    user_id = await _create_and_login(client, VALID_USER)

    # Seed emergency and non-emergency logs
    await _seed_audit_logs(user_id, count=2, event_type="auth")
    await _seed_audit_logs(user_id, count=3, event_type="emergency")

    resp = await client.get(f"/api/users/{user_id}/audit/emergency")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    for entry in data:
        assert entry["event_type"] == "emergency"
        assert entry["target_user_id"] == user_id


@pytest.mark.asyncio
async def test_list_audit_logs_respects_limit(client):
    """GET /api/users/{id}/audit?limit=2 caps the result count."""
    user_id = await _create_and_login(client, VALID_USER)
    await _seed_audit_logs(user_id, count=5, event_type="query")

    resp = await client.get(f"/api/users/{user_id}/audit", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_emergency_logs_denied_for_other_user(client):
    """GET /api/users/{other_id}/audit/emergency returns 403 for another user."""
    user_id = await _create_and_login(client, VALID_USER)

    # Create second user via a separate client so the first client's cookie is unchanged
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client2:
        other_resp = await client2.post("/api/users", json=SECOND_USER)
        assert other_resp.status_code == 200
        other_id = other_resp.json()["id"]

    resp = await client.get(f"/api/users/{other_id}/audit/emergency")
    assert resp.status_code == 403
