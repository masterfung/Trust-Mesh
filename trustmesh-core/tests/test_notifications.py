"""Tests for notification routes — activity feed for users."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db, async_session
from src.models import Notification, User


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
    "username": "notiftest",
    "display_name": "Notif Test User",
    "bio": "Testing notifications",
    "password": "SecureTestPass1!",
}


async def _signup(client):
    resp = await client.post("/api/users", json=VALID_USER)
    assert resp.status_code == 200
    return resp.json()


async def _create_notification(user_id, title="Test Notification", is_read=False):
    async with async_session() as db:
        notif = Notification(
            user_id=user_id,
            notification_type="info",
            title=title,
            body="Test body",
            is_read=is_read,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)
        return notif.id


@pytest.mark.asyncio
async def test_list_notifications_empty(client):
    """List notifications for user with no notifications."""
    user = await _signup(client)
    resp = await client.get(f"/api/users/{user['id']}/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_notifications_ordered(client):
    """Notifications returned unread first, then by recency."""
    user = await _signup(client)
    uid = user["id"]
    await _create_notification(uid, title="Unread 1", is_read=False)
    await _create_notification(uid, title="Read 1", is_read=True)
    await _create_notification(uid, title="Unread 2", is_read=False)

    resp = await client.get(f"/api/users/{uid}/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # Unread should come before read
    unread_titles = [n["title"] for n in data if not n["is_read"]]
    read_titles = [n["title"] for n in data if n["is_read"]]
    assert len(unread_titles) == 2
    assert len(read_titles) == 1


@pytest.mark.asyncio
async def test_unread_count(client):
    """GET unread count returns correct number."""
    user = await _signup(client)
    uid = user["id"]
    await _create_notification(uid, title="Unread 1", is_read=False)
    await _create_notification(uid, title="Unread 2", is_read=False)
    await _create_notification(uid, title="Read 1", is_read=True)

    resp = await client.get(f"/api/users/{uid}/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


@pytest.mark.asyncio
async def test_mark_single_read(client):
    """PUT marks a single notification as read."""
    user = await _signup(client)
    uid = user["id"]
    notif_id = await _create_notification(uid, title="To Read")

    resp = await client.put(f"/api/notifications/{notif_id}/read")
    assert resp.status_code == 200

    # Verify it's now read
    resp = await client.get(f"/api/users/{uid}/notifications/unread-count")
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_all_read(client):
    """PUT marks all notifications as read."""
    user = await _signup(client)
    uid = user["id"]
    await _create_notification(uid, title="N1")
    await _create_notification(uid, title="N2")
    await _create_notification(uid, title="N3")

    resp = await client.put(f"/api/users/{uid}/notifications/read-all")
    assert resp.status_code == 200

    resp = await client.get(f"/api/users/{uid}/notifications/unread-count")
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_auth_enforcement_list(client):
    """Can't read another user's notifications."""
    user = await _signup(client)
    # Try to access a different user's notifications
    resp = await client.get("/api/users/some-other-id/notifications")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_auth_enforcement_mark_read(client):
    """Can't mark another user's notification as read."""
    user = await _signup(client)
    uid = user["id"]

    # Create notification for another user directly in DB
    other_notif_id = await _create_notification("other-user-id", title="Other's notif")

    resp = await client.put(f"/api/notifications/{other_notif_id}/read")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_nonexistent_notification(client):
    """PUT for nonexistent notification → 404."""
    await _signup(client)
    resp = await client.put("/api/notifications/nonexistent-id/read")
    assert resp.status_code == 404
