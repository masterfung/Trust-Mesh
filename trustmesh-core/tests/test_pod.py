"""Tests for pod federation endpoints — pod identity, peer CRUD, cross-pod discovery."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.database import init_db, drop_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB for each test."""
    from src.auth import sessions, _login_attempts
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
    resp = await client.post("/api/pod/peers", json={"url": POD_URL})
    assert resp.status_code == 400
    assert "yourself" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_peer_unreachable(client):
    """POST /api/pod/peers with unreachable URL should return 502."""
    resp = await client.post("/api/pod/peers", json={"url": "http://localhost:59999"})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_remove_peer_not_found(client):
    """DELETE /api/pod/peers/{id} with bad ID should return 404."""
    resp = await client.delete("/api/pod/peers/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ping_peer_not_found(client):
    """POST /api/pod/peers/{id}/ping with bad ID should return 404."""
    resp = await client.post("/api/pod/peers/nonexistent-id/ping")
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
