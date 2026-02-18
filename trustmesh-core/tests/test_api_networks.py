"""Comprehensive tests for network, membership, join-request, and notification API routes.

Covers:
- Network CRUD (create, list, get, discover)
- Network membership (add, remove)
- Join requests (open auto-approve, approval flow, owner-only review)
- Notifications (list, read, unread count, mark all read)
- Auth enforcement on every protected endpoint
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import engine, init_db, drop_db


# ── Fixtures ──────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB, sessions, and rate limiters for each test."""
    sessions.clear()
    _login_attempts.clear()

    # Reset application-level rate limiters so tests don't bleed into each other
    from src.rate_limit import _connection_limiter, _query_limiter
    _connection_limiter._events.clear()
    _query_limiter._events.clear()

    # Clear in-memory vault keys
    from src.main import vault_keys
    vault_keys.clear()

    # Dispose all pooled connections before dropping tables to avoid
    # "no such table" races with lingering SQLite connections.
    await engine.dispose()

    await drop_db()
    await init_db()
    yield
    # Dispose again on teardown so the next test starts clean.
    await engine.dispose()


def _make_transport():
    """Build a fresh ASGITransport for the app."""
    from src.main import app
    return ASGITransport(app=app)


@pytest_asyncio.fixture
async def client():
    """Create an async test client. Each test gets a fresh client (no leftover cookies)."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client():
    """A second, always-unauthenticated client (never receives signup cookies)."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Test Data ─────────────────────────────────────────

VALID_USER = {
    "username": "testuser1",
    "display_name": "Test User One",
    "bio": "Testing",
    "password": "SecureTestPass1!",
}

VALID_USER2 = {
    "username": "testuser2",
    "display_name": "Test User Two",
    "bio": "Testing 2",
    "password": "SecureTestPass2!",
}

VALID_USER3 = {
    "username": "testuser3",
    "display_name": "Test User Three",
    "bio": "Testing 3",
    "password": "SecureTestPass3!",
}


# ── Helpers ───────────────────────────────────────────


async def signup_on(ac: AsyncClient, user_data: dict) -> tuple[dict, dict]:
    """Sign up a user on a *specific* client and return (user_json, cookies_dict).

    Using a dedicated client per user avoids cookie pollution.
    """
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        resp = await tmp.post("/api/users", json=user_data)
        assert resp.status_code == 200, f"Signup failed: {resp.text}"
        return resp.json(), dict(resp.cookies)


async def create_connection(
    user_a_id: str, cookies_a: dict,
    user_b_id: str, cookies_b: dict,
) -> None:
    """Create an accepted connection between two users.

    Uses throwaway clients to avoid cookie leakage.
    """
    transport = _make_transport()

    # A sends request to B
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies_a)
        req_resp = await tmp.post(
            "/api/connections/request",
            json={"from_user_id": user_a_id, "to_user_id": user_b_id},
        )
        assert req_resp.status_code == 200, f"Connection request failed: {req_resp.text}"
        request_id = req_resp.json()["id"]

    # B accepts
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies_b)
        accept_resp = await tmp.put(
            f"/api/connection-requests/{request_id}",
            json={"status": "accepted"},
        )
        assert accept_resp.status_code == 200, f"Accept connection failed: {accept_resp.text}"


async def create_network_helper(
    owner_id: str,
    cookies: dict,
    name: str = "Test Network",
    description: str = "A test network",
    is_public: bool = False,
    join_policy: str = "invite_only",
) -> dict:
    """Create a network and return its response JSON."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies)
        resp = await tmp.post(
            "/api/networks",
            json={
                "name": name,
                "description": description,
                "network_type": "custom",
                "owner_id": owner_id,
                "is_public": is_public,
                "join_policy": join_policy,
            },
        )
        assert resp.status_code == 200, f"Create network failed: {resp.text}"
        return resp.json()


async def _api_post(path: str, json: dict, cookies: dict) -> "httpx.Response":
    """Perform an authenticated POST via a throwaway client."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies)
        return await tmp.post(path, json=json)


async def _api_get(path: str, cookies: dict) -> "httpx.Response":
    """Perform an authenticated GET via a throwaway client."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies)
        return await tmp.get(path)


async def _api_put(path: str, json: dict, cookies: dict) -> "httpx.Response":
    """Perform an authenticated PUT via a throwaway client."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies)
        return await tmp.put(path, json=json)


async def _api_delete(path: str, cookies: dict) -> "httpx.Response":
    """Perform an authenticated DELETE via a throwaway client."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        tmp.cookies.clear()
        tmp.cookies.update(cookies)
        return await tmp.delete(path)


async def _api_get_anon(path: str) -> "httpx.Response":
    """Perform an unauthenticated GET via a throwaway client."""
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        return await tmp.get(path)


# ══════════════════════════════════════════════════════
# NETWORK TESTS
# ══════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_network_auth(client):
    """1. Create network (auth) -> 200, owner is first member."""
    user, cookies = await signup_on(client, VALID_USER)
    network = await create_network_helper(user["id"], cookies)

    assert network["name"] == "Test Network"
    assert network["owner_id"] == user["id"]
    assert len(network["members"]) == 1
    assert network["members"][0]["id"] == user["id"]


@pytest.mark.asyncio
async def test_create_network_without_auth(client):
    """2. Create network without auth -> 401."""
    resp = await _api_get_anon("/api/networks")  # GET won't work, test POST
    # Actually POST without auth:
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as tmp:
        resp = await tmp.post(
            "/api/networks",
            json={
                "name": "Unauthorized Net",
                "description": "Should fail",
                "network_type": "custom",
                "owner_id": "fake-id",
                "is_public": False,
                "join_policy": "invite_only",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_network_wrong_owner(client):
    """3. Create network as different user (owner_id mismatch) -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, _cookies2 = await signup_on(client, VALID_USER2)

    resp = await _api_post(
        "/api/networks",
        json={
            "name": "Not My Network",
            "description": "Mismatch",
            "network_type": "custom",
            "owner_id": user2["id"],
            "is_public": False,
            "join_policy": "invite_only",
        },
        cookies=cookies1,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_user_networks_auth(client):
    """4. List user networks (auth) -> 200."""
    user, cookies = await signup_on(client, VALID_USER)
    await create_network_helper(user["id"], cookies, name="Net A")
    await create_network_helper(user["id"], cookies, name="Net B")

    resp = await _api_get(f"/api/users/{user['id']}/networks", cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {n["name"] for n in data}
    assert names == {"Net A", "Net B"}


@pytest.mark.asyncio
async def test_list_user_networks_no_auth(client):
    """5. List user networks without auth -> 401."""
    user, _cookies = await signup_on(client, VALID_USER)
    resp = await _api_get_anon(f"/api/users/{user['id']}/networks")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_user_networks_different_user(client):
    """6. List user networks as different user -> 403."""
    user1, _cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    resp = await _api_get(f"/api/users/{user1['id']}/networks", cookies2)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_network_by_id_as_member(client):
    """7. Get network by ID (as member) -> 200."""
    user, cookies = await signup_on(client, VALID_USER)
    network = await create_network_helper(user["id"], cookies)

    resp = await _api_get(f"/api/networks/{network['id']}", cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == network["id"]
    assert data["name"] == "Test Network"
    assert len(data["members"]) == 1


@pytest.mark.asyncio
async def test_get_network_by_id_not_member(client):
    """7b. Get network by ID (not a member) -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(user1["id"], cookies1)

    resp = await _api_get(f"/api/networks/{network['id']}", cookies2)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_network_by_id_no_auth(client):
    """7c. Get network by ID without auth -> 401."""
    user, cookies = await signup_on(client, VALID_USER)
    network = await create_network_helper(user["id"], cookies)

    resp = await _api_get_anon(f"/api/networks/{network['id']}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_network_discovery_no_auth(client):
    """8. Network discovery (no auth) -> 200, only public networks."""
    user, cookies = await signup_on(client, VALID_USER)

    # Create one public and one private network
    await create_network_helper(
        user["id"], cookies, name="Public Net", is_public=True, join_policy="open",
    )
    await create_network_helper(
        user["id"], cookies, name="Private Net", is_public=False,
    )

    resp = await _api_get_anon("/api/networks/discover")
    assert resp.status_code == 200
    data = resp.json()
    names = [n["name"] for n in data]
    assert "Public Net" in names
    assert "Private Net" not in names


@pytest.mark.asyncio
async def test_network_discovery_shows_member_count(client):
    """8b. Network discovery shows member count and owner name."""
    user, cookies = await signup_on(client, VALID_USER)
    await create_network_helper(
        user["id"], cookies, name="Count Net", is_public=True, join_policy="open",
    )

    resp = await _api_get_anon("/api/networks/discover")
    assert resp.status_code == 200
    data = resp.json()
    net = next(n for n in data if n["name"] == "Count Net")
    assert net["member_count"] == 1
    assert net["owner_name"] == "Test User One"


@pytest.mark.asyncio
async def test_create_network_empty_name(client):
    """9. Create network with empty name -> 422."""
    user, cookies = await signup_on(client, VALID_USER)
    resp = await _api_post(
        "/api/networks",
        json={
            "name": "",
            "description": "Bad",
            "network_type": "custom",
            "owner_id": user["id"],
            "is_public": False,
            "join_policy": "invite_only",
        },
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_network_description_too_long(client):
    """10. Create network with description > 2000 chars -> 422."""
    user, cookies = await signup_on(client, VALID_USER)
    resp = await _api_post(
        "/api/networks",
        json={
            "name": "Long Desc Net",
            "description": "x" * 2001,
            "network_type": "custom",
            "owner_id": user["id"],
            "is_public": False,
            "join_policy": "invite_only",
        },
        cookies=cookies,
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════
# NETWORK MEMBER TESTS
# ══════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_add_member_owner(client):
    """11. Add member (owner, after creating connection) -> 200."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    # Create a connection between user1 and user2
    await create_connection(user1["id"], cookies1, user2["id"], cookies2)

    # Create network owned by user1
    network = await create_network_helper(user1["id"], cookies1)

    # Owner adds user2
    resp = await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )
    assert resp.status_code == 200
    data = resp.json()
    member_ids = [m["id"] for m in data["members"]]
    assert user1["id"] in member_ids
    assert user2["id"] in member_ids
    assert len(data["members"]) == 2


@pytest.mark.asyncio
async def test_add_member_not_owner(client):
    """12. Add member (not owner) -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)
    user3, cookies3 = await signup_on(client, VALID_USER3)

    # Connect user1 <-> user2, user1 <-> user3
    await create_connection(user1["id"], cookies1, user2["id"], cookies2)
    await create_connection(user1["id"], cookies1, user3["id"], cookies3)

    # Create network owned by user1, add user2 as member
    network = await create_network_helper(user1["id"], cookies1)
    await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )

    # User2 (non-owner member) tries to add user3
    resp = await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user3["id"]},
        cookies=cookies2,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_add_member_not_connected(client):
    """12b. Add member who is not connected to owner -> 400."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, _cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(user1["id"], cookies1)

    # Try to add user2 without a connection
    resp = await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": _user2["id"]},
        cookies=cookies1,
    )
    assert resp.status_code == 400
    assert "connected" in resp.text.lower()


@pytest.mark.asyncio
async def test_add_member_already_member(client):
    """12c. Add member who is already a member -> 400."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    await create_connection(user1["id"], cookies1, user2["id"], cookies2)
    network = await create_network_helper(user1["id"], cookies1)

    # Add user2
    resp1 = await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )
    assert resp1.status_code == 200

    # Try to add user2 again
    resp2 = await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )
    assert resp2.status_code == 400
    assert "already" in resp2.text.lower()


@pytest.mark.asyncio
async def test_remove_member_owner_removes(client):
    """13. Remove member (owner removes member) -> 200."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    await create_connection(user1["id"], cookies1, user2["id"], cookies2)
    network = await create_network_helper(user1["id"], cookies1)

    # Add user2
    await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )

    # Owner removes user2
    resp = await _api_delete(
        f"/api/networks/{network['id']}/members/{user2['id']}",
        cookies1,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_remove_member_self_removal(client):
    """14. Remove member (member removes self) -> 200."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    await create_connection(user1["id"], cookies1, user2["id"], cookies2)
    network = await create_network_helper(user1["id"], cookies1)

    # Add user2
    await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )

    # User2 removes themselves
    resp = await _api_delete(
        f"/api/networks/{network['id']}/members/{user2['id']}",
        cookies2,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_cannot_remove_network_owner(client):
    """15. Cannot remove network owner -> 400."""
    user1, cookies1 = await signup_on(client, VALID_USER)

    network = await create_network_helper(user1["id"], cookies1)

    resp = await _api_delete(
        f"/api/networks/{network['id']}/members/{user1['id']}",
        cookies1,
    )
    assert resp.status_code == 400
    assert "owner" in resp.text.lower()


@pytest.mark.asyncio
async def test_remove_member_unauthorized(client):
    """15b. Non-owner, non-self cannot remove member -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)
    user3, cookies3 = await signup_on(client, VALID_USER3)

    await create_connection(user1["id"], cookies1, user2["id"], cookies2)
    await create_connection(user1["id"], cookies1, user3["id"], cookies3)

    network = await create_network_helper(user1["id"], cookies1)

    # Add both user2 and user3
    await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user2["id"]},
        cookies=cookies1,
    )
    await _api_post(
        f"/api/networks/{network['id']}/members",
        json={"user_id": user3["id"]},
        cookies=cookies1,
    )

    # User3 tries to remove user2 (not owner, not self)
    resp = await _api_delete(
        f"/api/networks/{network['id']}/members/{user2['id']}",
        cookies3,
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════
# JOIN REQUEST TESTS
# ══════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_join_request_open_policy_auto_approved(client):
    """16. Join request to public network with open policy -> auto-approved."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Open Net", is_public=True, join_policy="open",
    )

    resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Let me in"},
        cookies=cookies2,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"

    # Verify user2 is now a member by accessing the network
    net_resp = await _api_get(f"/api/networks/{network['id']}", cookies2)
    assert net_resp.status_code == 200
    member_ids = [m["id"] for m in net_resp.json()["members"]]
    assert user2["id"] in member_ids


@pytest.mark.asyncio
async def test_join_request_approval_policy_pending(client):
    """17. Join request to public network with approval policy -> pending."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Approval Net", is_public=True, join_policy="approval",
    )

    resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Please approve me"},
        cookies=cookies2,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["user_id"] == user2["id"]
    assert data["network_id"] == network["id"]


@pytest.mark.asyncio
async def test_review_join_request_owner_approves(client):
    """18. Review join request (owner approves) -> adds member."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Approval Net", is_public=True, join_policy="approval",
    )

    # User2 sends join request
    join_resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Approve me"},
        cookies=cookies2,
    )
    assert join_resp.status_code == 200
    request_id = join_resp.json()["id"]

    # Owner lists join requests
    list_resp = await _api_get(
        f"/api/networks/{network['id']}/join-requests",
        cookies1,
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Owner approves
    approve_resp = await _api_put(
        f"/api/networks/{network['id']}/join-requests/{request_id}",
        json={"status": "approved"},
        cookies=cookies1,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    # Verify user2 is now a member
    net_resp = await _api_get(f"/api/networks/{network['id']}", cookies2)
    assert net_resp.status_code == 200
    member_ids = [m["id"] for m in net_resp.json()["members"]]
    assert user2["id"] in member_ids


@pytest.mark.asyncio
async def test_review_join_request_not_owner(client):
    """19. Review join request (not owner) -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)
    _user3, cookies3 = await signup_on(client, VALID_USER3)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Approval Net", is_public=True, join_policy="approval",
    )

    # User3 sends join request
    join_resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Hi"},
        cookies=cookies3,
    )
    request_id = join_resp.json()["id"]

    # User2 (not owner) tries to approve
    resp = await _api_put(
        f"/api/networks/{network['id']}/join-requests/{request_id}",
        json={"status": "approved"},
        cookies=cookies2,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_join_request_private_network_rejected(client):
    """19b. Join request to private network -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Private Net", is_public=False, join_policy="invite_only",
    )

    resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Let me in"},
        cookies=cookies2,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_join_request_already_member(client):
    """19c. Join request when already a member -> 400."""
    user1, cookies1 = await signup_on(client, VALID_USER)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Open Net", is_public=True, join_policy="open",
    )

    # Owner is already a member, try to join
    resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "I'm already in"},
        cookies=cookies1,
    )
    assert resp.status_code == 400
    assert "already" in resp.text.lower()


@pytest.mark.asyncio
async def test_join_request_duplicate_pending(client):
    """19d. Duplicate pending join request -> 400."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Approval Net", is_public=True, join_policy="approval",
    )

    # First request
    resp1 = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "First"},
        cookies=cookies2,
    )
    assert resp1.status_code == 200

    # Second request while first is pending
    resp2 = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Second"},
        cookies=cookies2,
    )
    assert resp2.status_code == 400
    assert "pending" in resp2.text.lower()


@pytest.mark.asyncio
async def test_review_join_request_decline(client):
    """19e. Owner declines join request."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Approval Net", is_public=True, join_policy="approval",
    )

    join_resp = await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Hi"},
        cookies=cookies2,
    )
    request_id = join_resp.json()["id"]

    # Owner declines
    decline_resp = await _api_put(
        f"/api/networks/{network['id']}/join-requests/{request_id}",
        json={"status": "declined"},
        cookies=cookies1,
    )
    assert decline_resp.status_code == 200
    assert decline_resp.json()["status"] == "declined"

    # User2 should NOT be a member
    net_resp = await _api_get(f"/api/networks/{network['id']}", cookies2)
    assert net_resp.status_code == 403  # Not a member


# ══════════════════════════════════════════════════════
# NOTIFICATION TESTS
# ══════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_notifications_auth(client):
    """20. List notifications (auth) -> 200."""
    user, cookies = await signup_on(client, VALID_USER)

    resp = await _api_get(f"/api/users/{user['id']}/notifications", cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_notifications_no_auth(client):
    """21. List notifications without auth -> 401."""
    user, _cookies = await signup_on(client, VALID_USER)

    resp = await _api_get_anon(f"/api/users/{user['id']}/notifications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_notifications_different_user(client):
    """22. List notifications as different user -> 403."""
    user1, _cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    resp = await _api_get(f"/api/users/{user1['id']}/notifications", cookies2)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_notification_read_owner(client):
    """23. Mark notification read (owner) -> 200."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    # Trigger a notification: join request with approval policy creates a notification
    network = await create_network_helper(
        user1["id"], cookies1,
        name="Notif Net", is_public=True, join_policy="approval",
    )
    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Please"},
        cookies=cookies2,
    )

    # Owner should have a notification
    notifs_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    assert notifs_resp.status_code == 200
    notifs = notifs_resp.json()
    assert len(notifs) >= 1

    notif_id = notifs[0]["id"]
    assert notifs[0]["is_read"] is False

    # Mark as read
    read_resp = await _api_put(
        f"/api/notifications/{notif_id}/read", json={}, cookies=cookies1,
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["ok"] is True

    # Verify it's marked as read
    notifs_resp2 = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    notif = next(n for n in notifs_resp2.json() if n["id"] == notif_id)
    assert notif["is_read"] is True


@pytest.mark.asyncio
async def test_mark_notification_read_not_owner(client):
    """24. Mark notification read (not owner) -> 403."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    # Create a notification for user1
    network = await create_network_helper(
        user1["id"], cookies1,
        name="Notif Net", is_public=True, join_policy="approval",
    )
    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Hi"},
        cookies=cookies2,
    )

    # Get the notification ID
    notifs_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    notif_id = notifs_resp.json()[0]["id"]

    # User2 tries to mark user1's notification as read
    resp = await _api_put(
        f"/api/notifications/{notif_id}/read", json={}, cookies=cookies2,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_all_read(client):
    """25. Mark all read (auth) -> 200."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)
    _user3, cookies3 = await signup_on(client, VALID_USER3)

    # Create two notifications via two join requests
    network = await create_network_helper(
        user1["id"], cookies1,
        name="Multi Notif Net", is_public=True, join_policy="approval",
    )
    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "From user2"},
        cookies=cookies2,
    )
    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "From user3"},
        cookies=cookies3,
    )

    # Verify there are unread notifications
    notifs_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    assert len(notifs_resp.json()) >= 2
    assert all(not n["is_read"] for n in notifs_resp.json())

    # Mark all as read
    resp = await _api_put(
        f"/api/users/{user1['id']}/notifications/read-all", json={}, cookies=cookies1,
    )
    assert resp.status_code == 200

    # Verify all are read
    notifs_resp2 = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    assert all(n["is_read"] for n in notifs_resp2.json())


@pytest.mark.asyncio
async def test_unread_count(client):
    """26. Unread count (auth) -> returns count."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    # Initially 0
    resp = await _api_get(
        f"/api/users/{user1['id']}/notifications/unread-count", cookies1,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0

    # Trigger a notification
    network = await create_network_helper(
        user1["id"], cookies1,
        name="Count Net", is_public=True, join_policy="approval",
    )
    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Counting"},
        cookies=cookies2,
    )

    # Should now be 1
    resp2 = await _api_get(
        f"/api/users/{user1['id']}/notifications/unread-count", cookies1,
    )
    assert resp2.status_code == 200
    assert resp2.json()["count"] == 1


@pytest.mark.asyncio
async def test_unread_count_no_auth(client):
    """26b. Unread count without auth -> 401."""
    user, _cookies = await signup_on(client, VALID_USER)
    resp = await _api_get_anon(f"/api/users/{user['id']}/notifications/unread-count")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unread_count_different_user(client):
    """26c. Unread count as different user -> 403."""
    user1, _cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    resp = await _api_get(
        f"/api/users/{user1['id']}/notifications/unread-count", cookies2,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_all_read_different_user(client):
    """26d. Mark all read as different user -> 403."""
    user1, _cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    resp = await _api_put(
        f"/api/users/{user1['id']}/notifications/read-all", json={}, cookies=cookies2,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_nonexistent_notification_read(client):
    """26e. Mark nonexistent notification read -> 404."""
    _user, cookies = await signup_on(client, VALID_USER)
    resp = await _api_put(
        "/api/notifications/nonexistent-id/read", json={}, cookies=cookies,
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════
# NOTIFICATION CONTENT TESTS
# ══════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_join_request_creates_notification_for_owner(client):
    """Join request with approval policy creates a notification for the network owner."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Notify Test Net", is_public=True, join_policy="approval",
    )

    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "I want to join"},
        cookies=cookies2,
    )

    # Check owner's notifications
    notifs_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    assert notifs_resp.status_code == 200
    notifs = notifs_resp.json()
    assert len(notifs) == 1
    assert notifs[0]["notification_type"] == "join_request"
    assert "Notify Test Net" in notifs[0]["title"]
    assert notifs[0]["related_id"] == network["id"]


@pytest.mark.asyncio
async def test_open_join_does_not_create_notification(client):
    """Open join policy auto-approves without creating a notification."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Open Net", is_public=True, join_policy="open",
    )

    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Auto join"},
        cookies=cookies2,
    )

    # Owner should not have notifications (open policy = no review needed)
    notifs_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    assert notifs_resp.status_code == 200
    assert len(notifs_resp.json()) == 0


@pytest.mark.asyncio
async def test_unread_count_decreases_after_mark_read(client):
    """Unread count decreases after marking a notification as read."""
    user1, cookies1 = await signup_on(client, VALID_USER)
    _user2, cookies2 = await signup_on(client, VALID_USER2)

    network = await create_network_helper(
        user1["id"], cookies1,
        name="Decr Net", is_public=True, join_policy="approval",
    )
    await _api_post(
        f"/api/networks/{network['id']}/join-request",
        json={"message": "Test"},
        cookies=cookies2,
    )

    # Count should be 1
    count_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications/unread-count", cookies1,
    )
    assert count_resp.json()["count"] == 1

    # Get the notification and mark read
    notifs_resp = await _api_get(
        f"/api/users/{user1['id']}/notifications", cookies1,
    )
    notifs = notifs_resp.json()
    await _api_put(
        f"/api/notifications/{notifs[0]['id']}/read", json={}, cookies=cookies1,
    )

    # Count should now be 0
    count_resp2 = await _api_get(
        f"/api/users/{user1['id']}/notifications/unread-count", cookies1,
    )
    assert count_resp2.json()["count"] == 0
