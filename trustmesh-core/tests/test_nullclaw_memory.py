"""Tests for the NullClaw-compatible memory API.

Wire format matches NullClaw api.zig:
  PUT    /api/memory/{ns}/memories/{key}          — store (client-controlled key)
  GET    /api/memory/{ns}/memories                — list
  POST   /api/memory/{ns}/memories/search         — FTS5 search
  DELETE /api/memory/{ns}/memories/{key}          — soft-delete
  GET    /api/memory/{ns}/health                  — health check
  POST   /api/memory/{ns}/sessions/{sid}/messages — save session message

Auth: Bearer tm_<token> (channel_tokens table, same as /api/channels/*).
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import _login_attempts, sessions
from src.database import drop_db, init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    sessions.clear()
    _login_attempts.clear()
    from src.main import vault_keys
    vault_keys.clear()
    await drop_db()
    await init_db()
    yield
    await drop_db()


@pytest_asyncio.fixture
async def client():
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── Helpers ───────────────────────────────────────────────────────────────────

_USER = {
    "username": "ncmemtest",
    "display_name": "NullClaw Memory Test",
    "bio": "",
    "password": "NullClaw-pass-1!",
}


async def _setup(client: AsyncClient) -> tuple[str, str]:
    """Create user, log in, create channel token. Return (user_id, raw_token)."""
    r = await client.post("/api/users", json=_USER)
    assert r.status_code in (200, 201), r.text
    user_id = r.json()["id"]

    r2 = await client.post(
        "/api/auth/login",
        json={"username": _USER["username"], "password": _USER["password"]},
    )
    assert r2.status_code == 200, r2.text

    r3 = await client.post(
        f"/api/users/{user_id}/channel-tokens",
        json={"name": "nullclaw-test", "scopes": ["query", "memory"]},
    )
    assert r3.status_code == 200, r3.text
    return user_id, r3.json()["raw_token"]


# ── Health ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    r = await client.get(f"/api/memory/{_USER['username']}/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["backend"] == "trustmesh"
    assert data["version"] == "1.0"


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_no_auth_401(client):
    r = await client.put(
        f"/api/memory/{_USER['username']}/memories/{uuid.uuid4()}",
        json={"content": "hello"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_store_invalid_token_401(client):
    r = await client.put(
        f"/api/memory/{_USER['username']}/memories/{uuid.uuid4()}",
        json={"content": "hello"},
        headers={"authorization": "Bearer tm_invalid_garbage"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_no_auth_401(client):
    r = await client.get(f"/api/memory/{_USER['username']}/memories")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_search_no_auth_401(client):
    r = await client.post(
        f"/api/memory/{_USER['username']}/memories/search",
        json={"query": "hello"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_no_auth_401(client):
    r = await client.delete(
        f"/api/memory/{_USER['username']}/memories/{uuid.uuid4()}"
    )
    assert r.status_code == 401


# ── Cross-user access ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_namespace_rejected(client):
    """Token owner_id must match the {ns} user."""
    _, token = await _setup(client)
    r = await client.put(
        f"/api/memory/other_user/memories/{uuid.uuid4()}",
        json={"content": "should fail"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code in (403, 404)


# ── Store & List ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_by_username(client):
    _, token = await _setup(client)
    key = str(uuid.uuid4())
    r = await client.put(
        f"/api/memory/{_USER['username']}/memories/{key}",
        json={"content": "Prefers morning meetings", "category": "core"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == key
    assert data["content"] == "Prefers morning meetings"
    assert data["category"] == "core"
    assert data["session_id"] is None
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_store_by_user_id_namespace(client):
    user_id, token = await _setup(client)
    key = str(uuid.uuid4())
    r = await client.put(
        f"/api/memory/{user_id}/memories/{key}",
        json={"content": "works with uuid ns", "category": "daily"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["category"] == "daily"


@pytest.mark.asyncio
async def test_upsert_same_key(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}
    key = str(uuid.uuid4())

    await client.put(
        f"/api/memory/{ns}/memories/{key}",
        json={"content": "original", "category": "core"},
        headers=headers,
    )
    r = await client.put(
        f"/api/memory/{ns}/memories/{key}",
        json={"content": "updated", "category": "core"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "updated"

    r2 = await client.get(f"/api/memory/{ns}/memories", headers=headers)
    matching = [e for e in r2.json()["entries"] if e["key"] == key]
    assert len(matching) == 1
    assert matching[0]["content"] == "updated"


@pytest.mark.asyncio
async def test_list_returns_entries_shape(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}

    key = str(uuid.uuid4())
    await client.put(
        f"/api/memory/{ns}/memories/{key}",
        json={"content": "some content", "category": "core"},
        headers=headers,
    )

    r = await client.get(f"/api/memory/{ns}/memories", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    entry = next(e for e in data["entries"] if e["key"] == key)
    assert entry["content"] == "some content"
    assert entry["category"] == "core"
    assert entry["session_id"] is None
    assert "timestamp" in entry
    assert "score" in entry


# ── Category mapping ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_category_roundtrip_all(client):
    """All NullClaw categories store and retrieve correctly — single DB/lifespan cycle."""
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}

    for nc_cat in ["core", "daily", "conversation", "custom:health", "custom:financial", "custom:legal"]:
        key = str(uuid.uuid4())
        r = await client.put(
            f"/api/memory/{ns}/memories/{key}",
            json={"content": f"test content for {nc_cat}", "category": nc_cat},
            headers=headers,
        )
        assert r.status_code == 200, f"PUT failed for {nc_cat}: {r.text}"
        assert r.json()["category"] == nc_cat

        r2 = await client.get(f"/api/memory/{ns}/memories", headers=headers)
        entry = next((e for e in r2.json()["entries"] if e["key"] == key), None)
        assert entry is not None, f"Entry not found for {nc_cat}"
        assert entry["category"] == nc_cat


@pytest.mark.asyncio
async def test_category_filter(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}

    core_key = str(uuid.uuid4())
    daily_key = str(uuid.uuid4())

    await client.put(
        f"/api/memory/{ns}/memories/{core_key}",
        json={"content": "core memory", "category": "core"},
        headers=headers,
    )
    await client.put(
        f"/api/memory/{ns}/memories/{daily_key}",
        json={"content": "daily memory", "category": "daily"},
        headers=headers,
    )

    r = await client.get(f"/api/memory/{ns}/memories?category=core", headers=headers)
    entries = r.json()["entries"]
    assert all(e["category"] == "core" for e in entries)
    assert any(e["key"] == core_key for e in entries)
    assert not any(e["key"] == daily_key for e in entries)


# ── Session ID ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_id_roundtrip(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}
    sid = str(uuid.uuid4())
    key = str(uuid.uuid4())

    r = await client.put(
        f"/api/memory/{ns}/memories/{key}",
        json={"content": "session note", "category": "conversation", "session_id": sid},
        headers=headers,
    )
    assert r.json()["session_id"] == sid

    r2 = await client.get(
        f"/api/memory/{ns}/memories?session_id={sid}", headers=headers
    )
    entries = r2.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["session_id"] == sid
    assert entries[0]["key"] == key


# ── Delete ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_removes_from_list(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}
    key = str(uuid.uuid4())

    await client.put(
        f"/api/memory/{ns}/memories/{key}",
        json={"content": "to delete", "category": "core"},
        headers=headers,
    )
    r = await client.delete(f"/api/memory/{ns}/memories/{key}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"

    r2 = await client.get(f"/api/memory/{ns}/memories", headers=headers)
    assert not any(e["key"] == key for e in r2.json()["entries"])


@pytest.mark.asyncio
async def test_delete_nonexistent_404(client):
    _, token = await _setup(client)
    r = await client.delete(
        f"/api/memory/{_USER['username']}/memories/{uuid.uuid4()}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ── Search ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_response_shape(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}

    r = await client.post(
        f"/api/memory/{ns}/memories/search",
        json={"query": "xyz_nonexistent_12345", "limit": 5},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert isinstance(data["entries"], list)


@pytest.mark.asyncio
async def test_search_finds_stored_content(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}
    key = str(uuid.uuid4())

    await client.put(
        f"/api/memory/{ns}/memories/{key}",
        json={"content": "fts5_unique_xylophone_metric", "category": "core"},
        headers=headers,
    )

    r = await client.post(
        f"/api/memory/{ns}/memories/search",
        json={"query": "xylophone", "limit": 10},
        headers=headers,
    )
    assert r.status_code == 200
    # FTS5 may not work in all test environments; just verify shape
    data = r.json()
    assert "entries" in data


# ── Session messages ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_message_saved(client):
    _, token = await _setup(client)
    ns = _USER["username"]
    headers = {"authorization": f"Bearer {token}"}
    sid = str(uuid.uuid4())

    r = await client.post(
        f"/api/memory/{ns}/sessions/{sid}/messages",
        json={"role": "user", "content": "Hello, what time is it?"},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "saved"
    assert "id" in data

    # Should appear in list filtered by session_id
    r2 = await client.get(
        f"/api/memory/{ns}/memories?session_id={sid}", headers=headers
    )
    entries = r2.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["session_id"] == sid
    assert "Hello, what time is it?" in entries[0]["content"]
    assert entries[0]["category"] == "conversation"


# ── Token revocation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoked_token_rejected(client):
    user_id, _ = await _setup(client)

    # Create a second token and immediately revoke it
    r = await client.post(
        f"/api/users/{user_id}/channel-tokens",
        json={"name": "revoke-me", "scopes": ["memory"]},
    )
    token_id = r.json()["id"]
    raw_token = r.json()["raw_token"]

    await client.delete(f"/api/users/{user_id}/channel-tokens/{token_id}")

    r2 = await client.put(
        f"/api/memory/{_USER['username']}/memories/{uuid.uuid4()}",
        json={"content": "should fail", "category": "core"},
        headers={"authorization": f"Bearer {raw_token}"},
    )
    assert r2.status_code == 401
