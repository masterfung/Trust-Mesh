"""
Tests for the Timeline API routes (/api/timeline/*).

Tests the FastAPI routes that wrap the Zig kernel via the FFI bridge.
"""

import time

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import COOKIE_NAME, sessions
from src.main import app
from src.timeline_bridge import is_available

# Skip all tests if kernel not built
pytestmark = [
    pytest.mark.skipif(
        not is_available(),
        reason="libpodos not built — run: cd kernel && zig build",
    ),
    pytest.mark.asyncio,
]

# Test user session
TEST_USER_ID = "timeline-test-user"
TEST_SESSION = "timeline-test-session-token"


@pytest.fixture(autouse=True)
def setup_session():
    """Inject a test session for auth."""
    sessions[TEST_SESSION] = (TEST_USER_ID, time.time())
    yield
    sessions.pop(TEST_SESSION, None)


@pytest.fixture
def cookies():
    return {COOKIE_NAME: TEST_SESSION}


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ═══════════════════════════════════════════
#  HEALTH CHECK
# ═══════════════════════════════════════════


async def test_timeline_health(client, cookies):
    resp = await client.get("/api/timeline/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["kernel_built"] is True


# ═══════════════════════════════════════════
#  ENGINE STATE
# ═══════════════════════════════════════════


async def test_get_state(client, cookies):
    resp = await client.get("/api/timeline/state", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "active_count" in data
    assert "tick_count" in data
    assert data["is_running"] is True  # auto-started by _get_engine


# ═══════════════════════════════════════════
#  TICK
# ═══════════════════════════════════════════


async def test_tick(client, cookies):
    resp = await client.post("/api/timeline/tick", cookies=cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tick_count"] >= 1


# ═══════════════════════════════════════════
#  ENTRY CRUD
# ═══════════════════════════════════════════


async def test_create_entry(client, cookies):
    resp = await client.post(
        "/api/timeline/entries",
        json={
            "label": "Test entry",
            "category": "test",
            "salience": 0.7,
        },
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["label"] == "Test entry"
    assert data["category"] == "test"
    assert data["state_name"] == "DORMANT"
    assert "id" in data


async def test_create_entry_with_time_trigger(client, cookies):
    now_ms = int(time.time() * 1000)
    resp = await client.post(
        "/api/timeline/entries",
        json={
            "label": "Timed entry",
            "category": "health",
            "activation_trigger": {
                "kind": "time",
                "at_ms": now_ms - 1000,
            },
        },
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["label"] == "Timed entry"


async def test_list_entries(client, cookies):
    # Create two entries
    await client.post(
        "/api/timeline/entries",
        json={"label": "Entry A", "category": "test"},
        cookies=cookies,
    )
    await client.post(
        "/api/timeline/entries",
        json={"label": "Entry B", "category": "test"},
        cookies=cookies,
    )

    resp = await client.get("/api/timeline/entries", cookies=cookies)
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) >= 2
    labels = [e["label"] for e in entries]
    assert "Entry A" in labels
    assert "Entry B" in labels


async def test_get_entry_by_id(client, cookies):
    create_resp = await client.post(
        "/api/timeline/entries",
        json={"label": "Specific entry", "category": "test"},
        cookies=cookies,
    )
    entry_id = create_resp.json()["id"]

    resp = await client.get(f"/api/timeline/entries/{entry_id}", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["label"] == "Specific entry"


async def test_get_nonexistent_entry(client, cookies):
    fake_id = "00000000-0000-0000-0000-000000000099"
    resp = await client.get(f"/api/timeline/entries/{fake_id}", cookies=cookies)
    assert resp.status_code == 404


# ═══════════════════════════════════════════
#  TRANSITIONS
# ═══════════════════════════════════════════


async def test_transition_entry(client, cookies):
    create_resp = await client.post(
        "/api/timeline/entries",
        json={"label": "Transition me", "category": "test"},
        cookies=cookies,
    )
    entry_id = create_resp.json()["id"]

    # dormant → pending (valid)
    resp = await client.post(
        f"/api/timeline/entries/{entry_id}/transition",
        json={"new_state": 1},  # PENDING
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["state_name"] == "PENDING"


async def test_invalid_transition(client, cookies):
    create_resp = await client.post(
        "/api/timeline/entries",
        json={"label": "Invalid transition", "category": "test"},
        cookies=cookies,
    )
    entry_id = create_resp.json()["id"]

    # dormant → active (invalid, must go through pending first)
    resp = await client.post(
        f"/api/timeline/entries/{entry_id}/transition",
        json={"new_state": 3},  # ACTIVE
        cookies=cookies,
    )
    assert resp.status_code == 400


# ═══════════════════════════════════════════
#  EVENTS
# ═══════════════════════════════════════════


async def test_push_event(client, cookies):
    resp = await client.post(
        "/api/timeline/events",
        json={"event_type": "test.event", "source": 0},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "test.event"


async def test_event_triggers_entry(client, cookies):
    # Create event-triggered entry
    await client.post(
        "/api/timeline/entries",
        json={
            "label": "Event listener",
            "category": "test",
            "activation_trigger": {
                "kind": "event",
                "event_type": "data.updated",
                "event_source": 0,
            },
        },
        cookies=cookies,
    )

    # Push matching event
    await client.post(
        "/api/timeline/events",
        json={"event_type": "data.updated", "source": 4},
        cookies=cookies,
    )

    # Tick to process
    await client.post("/api/timeline/tick", cookies=cookies)

    # Check state
    resp = await client.get("/api/timeline/state", cookies=cookies)
    data = resp.json()
    # At least something should have moved from dormant
    assert data["total_count"] >= 1


# ═══════════════════════════════════════════
#  HOOKS
# ═══════════════════════════════════════════


async def test_hook_complete(client, cookies):
    create_resp = await client.post(
        "/api/timeline/entries",
        json={
            "label": "Hooked entry",
            "category": "test",
            "hooks": [
                {"action": 0, "phase": 0, "prompt": "Do a thing"},
            ],
        },
        cookies=cookies,
    )
    entry_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/timeline/entries/{entry_id}/hooks/0/complete",
        json={"hook_index": 0, "success": True},
        cookies=cookies,
    )
    assert resp.status_code == 200


# ═══════════════════════════════════════════
#  START / STOP
# ═══════════════════════════════════════════


async def test_start_stop(client, cookies):
    resp = await client.post("/api/timeline/stop", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"

    resp = await client.post("/api/timeline/start", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


# ═══════════════════════════════════════════
#  AUTH REQUIRED
# ═══════════════════════════════════════════


async def test_state_requires_auth(client):
    resp = await client.get("/api/timeline/state")
    assert resp.status_code == 401


async def test_tick_requires_auth(client):
    resp = await client.post("/api/timeline/tick")
    assert resp.status_code == 401


async def test_create_entry_requires_auth(client):
    resp = await client.post(
        "/api/timeline/entries",
        json={"label": "No auth", "category": "test"},
    )
    assert resp.status_code == 401
