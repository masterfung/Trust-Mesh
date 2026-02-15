"""Tests for pod federation endpoints — pod identity, peer CRUD, cross-pod discovery."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient

from src.database import init_db, drop_db

# Shared test secret for authenticated peer operations
_TEST_SECRET = "test-pod-secret"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB for each test."""
    from src.auth import sessions, _login_attempts
    from src.rate_limit import reset_rate_limits
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
    "username": "testpod",
    "display_name": "Test Pod User",
    "bio": "Testing pod federation",
    "password": "SecureTestPass1!",
}


# ── Pod Identity ──


@pytest.mark.asyncio
async def test_pod_info_returns_identity(client):
    """GET /api/pod should return pod name, URL, protocol, and agents."""
    resp = await client.get("/api/pod")
    assert resp.status_code == 200
    data = resp.json()
    assert "pod_name" in data
    assert "pod_url" in data
    assert data["protocol"] == "trustmesh/0.1"
    assert "agent_count" in data
    assert isinstance(data["agents"], list)


@pytest.mark.asyncio
async def test_pod_info_no_auth_required(client):
    """GET /api/pod is public — no auth needed."""
    resp = await client.get("/api/pod")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_pod_info_includes_agents_after_signup(client):
    """After creating a user, their agent should appear in pod info."""
    # Create a user (which also creates an agent)
    signup = await client.post("/api/users", json=VALID_USER)
    assert signup.status_code == 200

    resp = await client.get("/api/pod")
    data = resp.json()
    assert data["agent_count"] >= 1
    assert any(a["owner_username"] == "testpod" for a in data["agents"])


# ── Agent Card ──


@pytest.mark.asyncio
async def test_agent_card_a2a_format(client):
    """/.well-known/agent-card.json should return A2A-compatible format."""
    resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    data = resp.json()
    # Required A2A fields
    assert "name" in data
    assert "url" in data
    assert "version" in data
    assert "capabilities" in data
    assert "skills" in data
    assert "defaultInputModes" in data
    assert "defaultOutputModes" in data
    # TrustMesh extension
    assert "trustmesh" in data
    assert data["trustmesh"]["protocol"] == "trustmesh/0.1"


@pytest.mark.asyncio
async def test_agent_card_legacy_endpoint(client):
    """/.well-known/agent.json should return same format as agent-card.json."""
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert "trustmesh" in data


@pytest.mark.asyncio
async def test_agent_card_includes_skills_after_signup(client):
    """After creating a user, their skill should appear in agent card."""
    await client.post("/api/users", json=VALID_USER)

    resp = await client.get("/.well-known/agent-card.json")
    data = resp.json()
    assert len(data["skills"]) >= 1
    assert any("testpod" in s["id"] for s in data["skills"])


# ── Peer Management ──


@pytest.mark.asyncio
async def test_list_peers_empty(client):
    """GET /api/pod/peers should return empty list when no peers."""
    resp = await client.get("/api/pod/peers")
    assert resp.status_code == 200
    data = resp.json()
    assert "peers" in data
    assert len(data["peers"]) == 0


@pytest.mark.asyncio
async def test_add_peer_self_rejected(client):
    """POST /api/pod/peers with self URL should be rejected."""
    from src.federation import POD_URL
    with patch("src.routes.pod.POOL_SYNC_SECRET", _TEST_SECRET):
        resp = await client.post(
            "/api/pod/peers", json={"url": POD_URL},
            headers={"X-Pool-Sync-Secret": _TEST_SECRET},
        )
    assert resp.status_code == 400
    assert "yourself" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_peer_unreachable(client):
    """POST /api/pod/peers with unreachable URL should return 502."""
    with patch("src.routes.pod.POOL_SYNC_SECRET", _TEST_SECRET):
        resp = await client.post(
            "/api/pod/peers", json={"url": "http://localhost:59999"},
            headers={"X-Pool-Sync-Secret": _TEST_SECRET},
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_remove_peer_not_found(client):
    """DELETE /api/pod/peers/{id} with bad ID should return 404."""
    with patch("src.routes.pod.POOL_SYNC_SECRET", _TEST_SECRET):
        resp = await client.delete(
            "/api/pod/peers/nonexistent-id",
            headers={"X-Pool-Sync-Secret": _TEST_SECRET},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ping_peer_not_found(client):
    """POST /api/pod/peers/{id}/ping with bad ID should return 404."""
    with patch("src.routes.pod.POOL_SYNC_SECRET", _TEST_SECRET):
        resp = await client.post(
            "/api/pod/peers/nonexistent-id/ping",
            headers={"X-Pool-Sync-Secret": _TEST_SECRET},
        )
    assert resp.status_code == 404


# ── Cross-Pod Discovery ──


@pytest.mark.asyncio
async def test_discover_local_only(client):
    """GET /api/pod/discover should return local agents when no peers."""
    await client.post("/api/users", json=VALID_USER)

    resp = await client.get("/api/pod/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["local_count"] >= 1
    assert data["remote_count"] == 0
    assert data["total"] == data["local_count"] + data["remote_count"]
    # Local agents have is_local flag
    for a in data["agents"]:
        assert a["_pod"]["is_local"] is True


# ── Cross-Pod Query ──


@pytest.mark.asyncio
async def test_remote_query_user_not_found(client):
    """POST /api/pod/query with unknown username should return 404."""
    resp = await client.post("/api/pod/query", json={
        "from_did": "did:key:z6MkTest",
        "from_pod": "http://remote-pod:8001",
        "to_username": "nonexistent",
        "question": "Hello?",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remote_query_valid_user(client):
    """POST /api/pod/query with valid user should execute (may fail on LLM but not 404/500)."""
    # Create a user on this pod
    signup = await client.post("/api/users", json=VALID_USER)
    assert signup.status_code == 200

    resp = await client.post("/api/pod/query", json={
        "from_did": "did:key:z6MkTestRemote",
        "from_pod": "http://remote-pod:8001",
        "to_username": "testpod",
        "question": "What do you know?",
    })
    # Should not be 404 (user exists) or 500 (should handle gracefully)
    assert resp.status_code == 200
    data = resp.json()
    # Should have trust_level = "public" for remote query
    assert data.get("trust_level") == "public"


# ── PeerPod Model ──


@pytest.mark.asyncio
async def test_peer_pod_model():
    """PeerPod model should not have did or public_key fields."""
    from src.models import PeerPod
    columns = {c.name for c in PeerPod.__table__.columns}
    assert "id" in columns
    assert "name" in columns
    assert "url" in columns
    assert "status" in columns
    assert "agent_count" in columns
    assert "last_seen_at" in columns
    assert "created_at" in columns
    # These should NOT exist (removed per design)
    assert "did" not in columns
    assert "public_key" not in columns


# ── A2A Endpoint ──


@pytest.mark.asyncio
async def test_a2a_endpoint_unsupported_method(client):
    """POST /api/pod/a2a with unsupported method should return JSON-RPC error."""
    resp = await client.post("/api/pod/a2a", json={
        "jsonrpc": "2.0",
        "method": "task/cancel",
        "id": "1",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "hello"}]},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_a2a_endpoint_no_text(client):
    """POST /api/pod/a2a with empty text parts should return error."""
    resp = await client.post("/api/pod/a2a", json={
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "2",
        "params": {
            "message": {"role": "user", "parts": []},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_a2a_endpoint_valid_query(client):
    """POST /api/pod/a2a with valid user should return A2A task response."""
    # Create a user first
    await client.post("/api/users", json=VALID_USER)

    resp = await client.post("/api/pod/a2a", json={
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "3",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "What do you know?"}]},
            "metadata": {"to_username": "testpod"},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    assert data["result"]["status"]["state"] in ("completed", "failed")
    assert "metadata" in data["result"]
    assert data["result"]["metadata"]["trust_level"] == "public"


@pytest.mark.asyncio
async def test_a2a_endpoint_nonexistent_user(client):
    """POST /api/pod/a2a targeting unknown user should return error."""
    resp = await client.post("/api/pod/a2a", json={
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "4",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "Hello"}]},
            "metadata": {"to_username": "nobody"},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


# ── Registry Endpoints ──


@pytest.mark.asyncio
async def test_registry_agents_empty(client):
    """GET /api/registry/agents should return empty list when no users."""
    resp = await client.get("/api/registry/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_registry_agents_after_signup(client):
    """GET /api/registry/agents should include agents after user creation."""
    await client.post("/api/users", json=VALID_USER)
    resp = await client.get("/api/registry/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any(a["username"] == "testpod" for a in data["agents"])


@pytest.mark.asyncio
async def test_registry_search(client):
    """GET /api/registry/search should find agents by query."""
    await client.post("/api/users", json=VALID_USER)
    resp = await client.get("/api/registry/search", params={"q": "testpod"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1


@pytest.mark.asyncio
async def test_registry_search_no_results(client):
    """GET /api/registry/search with no matching query returns empty."""
    resp = await client.get("/api/registry/search", params={"q": "zzz_nonexistent_zzz"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_registry_lookup_not_found(client):
    """GET /api/registry/lookup/{did} with bad DID returns 404."""
    resp = await client.get("/api/registry/lookup/did:key:z6MkNonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_registry_lookup_by_did(client):
    """GET /api/registry/lookup/{did} should find agent by DID."""
    await client.post("/api/users", json=VALID_USER)

    # Get the agent's DID via registry (which has it)
    agents_resp = await client.get("/api/registry/agents")
    agents = agents_resp.json()["agents"]
    did = next(a["did"] for a in agents if a["username"] == "testpod")

    # Lookup by DID
    resp = await client.get(f"/api/registry/lookup/{did}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["did"] == did
    assert data["username"] == "testpod"
    assert "pod" in data
