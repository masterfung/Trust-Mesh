"""Comprehensive tests for capsule CRUD and connection request API endpoints.

Tests cover authentication, authorization, validation, and happy-path behavior
for the capsule and connection routes, using httpOnly cookie-based auth.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db
from src.rate_limit import _connection_limiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def setup_db():
    """Reset DB, auth state, and rate limiters for each test."""
    sessions.clear()
    _login_attempts.clear()
    _connection_limiter._events.clear()

    # Also clear vault keys so tests are fully isolated
    from src.main import vault_keys
    vault_keys.clear()

    await drop_db()
    await init_db()
    yield
    await drop_db()


def _make_transport():
    """Build an ASGITransport from the app (import deferred to avoid import-order issues)."""
    from src.main import app
    return ASGITransport(app=app)


@pytest.fixture
async def client():
    """Create an async test client."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def anon_client():
    """A second, always-unauthenticated client (no stored cookies)."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_USER_A = {
    "username": "capsuleuser_a",
    "display_name": "Capsule User A",
    "bio": "",
    "password": "SecureTestPass1!",
}

VALID_USER_B = {
    "username": "capsuleuser_b",
    "display_name": "Capsule User B",
    "bio": "",
    "password": "SecureTestPass2!",
}

CAPSULE_PAYLOAD = {
    "capsule_type": "memory",
    "title": "Test Capsule",
    "content": "This is test capsule content.",
    "tier": "private",
    "network_ids": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def signup_user(client: AsyncClient, user_data: dict) -> tuple[dict, dict]:
    """Sign up a user and return (user_json, cookies_dict).

    The cookies dict can be passed to subsequent requests as
    ``cookies=cookies``.
    """
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    # httpx cookies are a Cookies object; convert to plain dict for reuse
    cookies = dict(resp.cookies)
    return resp.json(), cookies


async def create_capsule(
    client: AsyncClient, user_id: str, cookies: dict, payload: dict | None = None,
) -> dict:
    """Create a capsule for a user and return the response JSON."""
    data = payload or CAPSULE_PAYLOAD
    resp = await client.post(
        f"/api/users/{user_id}/capsules", json=data, cookies=cookies,
    )
    assert resp.status_code == 200, f"Create capsule failed: {resp.text}"
    return resp.json()


# ===================================================================
# CAPSULE TESTS
# ===================================================================


@pytest.mark.asyncio
async def test_create_capsule_authenticated(client):
    """1. Create capsule (authenticated) returns 200 with decrypted content."""
    user, cookies = await signup_user(client, VALID_USER_A)
    capsule = await create_capsule(client, user["id"], cookies)

    assert capsule["owner_id"] == user["id"]
    assert capsule["capsule_type"] == "memory"
    assert capsule["title"] == "Test Capsule"
    assert capsule["content"] == "This is test capsule content."
    assert capsule["tier"] == "private"
    assert capsule["network_ids"] == []
    assert "id" in capsule
    assert "created_at" in capsule


@pytest.mark.asyncio
async def test_create_capsule_without_auth(client, anon_client):
    """2. Create capsule without auth returns 401."""
    user, cookies = await signup_user(client, VALID_USER_A)

    # Use the anon_client which has no session cookie stored
    resp = await anon_client.post(
        f"/api/users/{user['id']}/capsules", json=CAPSULE_PAYLOAD,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_capsule_as_different_user(client):
    """3. Create capsule as different user returns 403."""
    user_a, _cookies_a = await signup_user(client, VALID_USER_A)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)

    resp = await client.post(
        f"/api/users/{user_a['id']}/capsules",
        json=CAPSULE_PAYLOAD,
        cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_capsules_authenticated(client):
    """4. List capsules (authenticated) returns all user's capsules."""
    user, cookies = await signup_user(client, VALID_USER_A)

    # Create two capsules
    await create_capsule(client, user["id"], cookies, {
        **CAPSULE_PAYLOAD, "title": "Capsule One",
    })
    await create_capsule(client, user["id"], cookies, {
        **CAPSULE_PAYLOAD, "title": "Capsule Two",
    })

    resp = await client.get(
        f"/api/users/{user['id']}/capsules", cookies=cookies,
    )
    assert resp.status_code == 200
    capsules = resp.json()
    assert len(capsules) == 2
    titles = {c["title"] for c in capsules}
    assert titles == {"Capsule One", "Capsule Two"}


@pytest.mark.asyncio
async def test_list_capsules_without_auth(client, anon_client):
    """5. List capsules without auth returns 401."""
    user, cookies = await signup_user(client, VALID_USER_A)
    await create_capsule(client, user["id"], cookies)

    # Use the anon_client which has no session cookie
    resp = await anon_client.get(f"/api/users/{user['id']}/capsules")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_capsules_as_different_user(client):
    """6. List capsules as different user returns 403."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)
    await create_capsule(client, user_a["id"], cookies_a)

    resp = await client.get(
        f"/api/users/{user_a['id']}/capsules", cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_capsule_owner(client):
    """7. Update capsule (owner) returns 200 with updated fields."""
    user, cookies = await signup_user(client, VALID_USER_A)
    capsule = await create_capsule(client, user["id"], cookies)

    update_payload = {
        "title": "Updated Title",
        "content": "Updated content here.",
    }
    resp = await client.put(
        f"/api/capsules/{capsule['id']}", json=update_payload, cookies=cookies,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["title"] == "Updated Title"
    assert updated["content"] == "Updated content here."
    assert updated["id"] == capsule["id"]


@pytest.mark.asyncio
async def test_update_capsule_not_owner(client):
    """8. Update capsule (not owner) returns 403."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)
    capsule = await create_capsule(client, user_a["id"], cookies_a)

    resp = await client.put(
        f"/api/capsules/{capsule['id']}",
        json={"title": "Hijacked"},
        cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_capsule_owner(client):
    """9. Delete capsule (owner) returns 200, then list returns empty."""
    user, cookies = await signup_user(client, VALID_USER_A)
    capsule = await create_capsule(client, user["id"], cookies)

    # Delete
    resp = await client.delete(
        f"/api/capsules/{capsule['id']}", cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # List should be empty
    list_resp = await client.get(
        f"/api/users/{user['id']}/capsules", cookies=cookies,
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_capsule_not_owner(client):
    """10. Delete capsule (not owner) returns 403."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)
    capsule = await create_capsule(client, user_a["id"], cookies_a)

    resp = await client.delete(
        f"/api/capsules/{capsule['id']}", cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_capsule_invalid_type(client):
    """11. Create capsule with invalid capsule_type returns 422."""
    user, cookies = await signup_user(client, VALID_USER_A)

    bad_payload = {**CAPSULE_PAYLOAD, "capsule_type": "invalid_type"}
    resp = await client.post(
        f"/api/users/{user['id']}/capsules", json=bad_payload, cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_capsule_empty_title(client):
    """12. Create capsule with empty title returns 422."""
    user, cookies = await signup_user(client, VALID_USER_A)

    bad_payload = {**CAPSULE_PAYLOAD, "title": ""}
    resp = await client.post(
        f"/api/users/{user['id']}/capsules", json=bad_payload, cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_capsule_content_exceeds_max_length(client):
    """13. Create capsule with content over 100000 chars returns 422."""
    user, cookies = await signup_user(client, VALID_USER_A)

    bad_payload = {**CAPSULE_PAYLOAD, "content": "x" * 100001}
    resp = await client.post(
        f"/api/users/{user['id']}/capsules", json=bad_payload, cookies=cookies,
    )
    assert resp.status_code == 422


# ===================================================================
# CONNECTION TESTS
# ===================================================================


@pytest.mark.asyncio
async def test_send_connection_request_authenticated(client):
    """14. Send connection request (auth) returns 200."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    user_b, _cookies_b = await signup_user(client, VALID_USER_B)

    payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_b["id"],
        "message": "Hello, let's connect!",
    }
    resp = await client.post(
        "/api/connections/request", json=payload, cookies=cookies_a,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_user_id"] == user_a["id"]
    assert data["to_user_id"] == user_b["id"]
    assert data["status"] == "pending"
    assert data["message"] == "Hello, let's connect!"


@pytest.mark.asyncio
async def test_send_connection_request_without_auth(client, anon_client):
    """15. Send connection request without auth returns 401."""
    user_a, _cookies_a = await signup_user(client, VALID_USER_A)
    user_b, _cookies_b = await signup_user(client, VALID_USER_B)

    payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_b["id"],
        "message": "Hello",
    }
    # Use the anon_client which has no session cookie
    resp = await anon_client.post("/api/connections/request", json=payload)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_send_connection_request_as_wrong_user(client):
    """16. Send connection request as wrong user returns 403."""
    user_a, _cookies_a = await signup_user(client, VALID_USER_A)
    user_b, cookies_b = await signup_user(client, VALID_USER_B)

    # User B tries to send a request pretending to be user A
    payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_b["id"],
        "message": "Spoofed",
    }
    resp = await client.post(
        "/api/connections/request", json=payload, cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_send_connection_request_to_self(client):
    """17. Send connection request to self returns 400."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)

    payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_a["id"],
        "message": "Self connect",
    }
    resp = await client.post(
        "/api/connections/request", json=payload, cookies=cookies_a,
    )
    assert resp.status_code == 400
    assert "yourself" in resp.text.lower()


@pytest.mark.asyncio
async def test_accept_connection_request(client):
    """18. Accept connection request returns 200, creates connection."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    user_b, cookies_b = await signup_user(client, VALID_USER_B)

    # Send request from A to B
    req_payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_b["id"],
        "message": "Let's connect",
    }
    req_resp = await client.post(
        "/api/connections/request", json=req_payload, cookies=cookies_a,
    )
    assert req_resp.status_code == 200
    request_id = req_resp.json()["id"]

    # Accept as B (the recipient)
    accept_resp = await client.put(
        f"/api/connection-requests/{request_id}",
        json={"status": "accepted"},
        cookies=cookies_b,
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    # Verify connection appears in B's connection list
    conn_resp = await client.get(
        f"/api/users/{user_b['id']}/connections", cookies=cookies_b,
    )
    assert conn_resp.status_code == 200
    connections = conn_resp.json()
    assert len(connections) == 1
    assert connections[0]["status"] == "accepted"


@pytest.mark.asyncio
async def test_accept_connection_by_wrong_user(client):
    """19. Accept connection by wrong user (not the recipient) returns 403."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    user_b, _cookies_b = await signup_user(client, VALID_USER_B)

    # Send request from A to B
    req_payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_b["id"],
        "message": "Connect",
    }
    req_resp = await client.post(
        "/api/connections/request", json=req_payload, cookies=cookies_a,
    )
    request_id = req_resp.json()["id"]

    # A (the sender) tries to accept -- should be denied
    accept_resp = await client.put(
        f"/api/connection-requests/{request_id}",
        json={"status": "accepted"},
        cookies=cookies_a,
    )
    assert accept_resp.status_code == 403


@pytest.mark.asyncio
async def test_list_connections_authenticated(client):
    """20. List connections (auth) returns 200."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)

    resp = await client.get(
        f"/api/users/{user_a['id']}/connections", cookies=cookies_a,
    )
    assert resp.status_code == 200
    assert resp.json() == []  # No connections yet


@pytest.mark.asyncio
async def test_list_connections_without_auth(client, anon_client):
    """21. List connections without auth returns 401."""
    user_a, _cookies = await signup_user(client, VALID_USER_A)

    # Use the anon_client which has no session cookie
    resp = await anon_client.get(f"/api/users/{user_a['id']}/connections")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_connection_request(client):
    """22. Duplicate connection request returns 400."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    user_b, _cookies_b = await signup_user(client, VALID_USER_B)

    payload = {
        "from_user_id": user_a["id"],
        "to_user_id": user_b["id"],
        "message": "First request",
    }

    # First request succeeds
    resp1 = await client.post(
        "/api/connections/request", json=payload, cookies=cookies_a,
    )
    assert resp1.status_code == 200

    # Second identical request fails
    resp2 = await client.post(
        "/api/connections/request", json=payload, cookies=cookies_a,
    )
    assert resp2.status_code == 400
    assert "pending" in resp2.text.lower() or "already" in resp2.text.lower()
