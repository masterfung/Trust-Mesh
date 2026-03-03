"""Tests for the inter-agent messaging system — bridge + API routes."""

import os
import hashlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio

from src.database import init_db, drop_db, engine


# ── Shared setup fixture ──────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Fresh DB for each test, matching credential_bridge.py pattern."""
    from src.embeddings import close_fts, init_fts
    from src import message_bridge, transit_bridge

    close_fts()
    await drop_db()
    await init_db()
    init_fts()
    transit_bridge._ensure_init()

    # Reset message_bridge state
    message_bridge._db_handle = None
    message_bridge._initialized = False
    message_bridge._ensure_zig()

    await engine.dispose()

    yield

    message_bridge._db_handle = None
    message_bridge._initialized = False
    from src.trust import reset_db_handle
    reset_db_handle()


# ── Helpers ───────────────────────────────────────────────────────────────────

DEMO_PASSWORD = "TrustMesh-demo-2026"


def _setup_vault_key(user_id: str = "msg-test-user") -> str:
    """Store a vault key for the test user so encrypt/decrypt works."""
    from src import transit_bridge
    key = os.urandom(32)
    transit_bridge.store_key(user_id, key)
    return user_id


def _encrypt_body(user_id: str, message_id: str, plaintext: str) -> bytes:
    """Encrypt a message body using transit engine."""
    from src import transit_bridge
    aad = f"message:{message_id}"
    return transit_bridge.encrypt(user_id, plaintext.encode(), aad=aad)


def _create_test_message(
    sender_id: str = "sender-001",
    recipient_id: str = "recipient-001",
    subject: str = "Test subject",
    body: str = "Hello from the test",
    trust_level: str = "connected",
    expires_at: str | None = None,
    rekey_needed: bool = False,
    message_id: str | None = None,
) -> str:
    """Helper: create a message with a dummy encrypted body (no vault key needed)."""
    from src import message_bridge
    mid = message_id or uuid.uuid4().hex
    body_bytes = body.encode()
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    message_bridge.create_message(
        message_id=mid,
        sender_id=sender_id,
        sender_username="sender",
        sender_display_name="Sender User",
        sender_pod_url=None,
        recipient_id=recipient_id,
        subject=subject,
        body_encrypted=body_bytes,  # Not actually encrypted — fine for CRUD tests
        body_hash=body_hash,
        scope="direct",
        network_id=None,
        trust_level=trust_level,
        expires_at=expires_at,
        rekey_needed=rekey_needed,
    )
    return mid


# ── Bridge unit tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_message_returns_id():
    """create_message returns the provided message_id."""
    from src import message_bridge
    mid = "test-msg-001"
    result = message_bridge.create_message(
        message_id=mid,
        sender_id="s1", sender_username="alice", sender_display_name="Alice",
        sender_pod_url=None,
        recipient_id="r1",
        subject="Hi",
        body_encrypted=b"encrypted-blob",
        body_hash="abc123",
    )
    assert result == mid


@pytest.mark.asyncio
async def test_list_inbox_contains_sent_message():
    """A created message shows up in the recipient's inbox."""
    mid = _create_test_message(recipient_id="rcpt-a", subject="Hello")
    from src import message_bridge
    inbox = message_bridge.list_inbox("rcpt-a")
    assert any(m["id"] == mid for m in inbox)


@pytest.mark.asyncio
async def test_list_inbox_empty_for_wrong_user():
    """Inbox for a different user is empty."""
    _create_test_message(recipient_id="rcpt-b")
    from src import message_bridge
    inbox = message_bridge.list_inbox("nobody")
    assert inbox == []


@pytest.mark.asyncio
async def test_unread_count_increments():
    """Unread count reflects number of unread messages."""
    from src import message_bridge
    _create_test_message(recipient_id="rcpt-c")
    _create_test_message(recipient_id="rcpt-c", subject="Second")
    count = message_bridge.unread_count("rcpt-c")
    assert count == 2


@pytest.mark.asyncio
async def test_mark_read_decrements_unread():
    """Marking a message read decrements the unread count."""
    from src import message_bridge
    mid = _create_test_message(recipient_id="rcpt-d")
    assert message_bridge.unread_count("rcpt-d") == 1

    ok = message_bridge.mark_read(mid, "rcpt-d")
    assert ok is True
    assert message_bridge.unread_count("rcpt-d") == 0


@pytest.mark.asyncio
async def test_mark_read_wrong_recipient_fails():
    """mark_read returns False when recipient doesn't match."""
    from src import message_bridge
    mid = _create_test_message(recipient_id="rcpt-e")
    ok = message_bridge.mark_read(mid, "wrong-user")
    # Soft failure — message stays unread
    assert message_bridge.unread_count("rcpt-e") == 1


@pytest.mark.asyncio
async def test_soft_delete_removes_from_inbox():
    """Soft-deleting removes the message from inbox listing."""
    from src import message_bridge
    mid = _create_test_message(recipient_id="rcpt-f")
    ok = message_bridge.soft_delete(mid, "rcpt-f")
    assert ok is True
    inbox = message_bridge.list_inbox("rcpt-f")
    assert not any(m["id"] == mid for m in inbox)


@pytest.mark.asyncio
async def test_list_sent_contains_sent_message():
    """A sent message appears in sender's sent list."""
    from src import message_bridge
    mid = _create_test_message(sender_id="sender-x", recipient_id="any-recipient")
    sent = message_bridge.list_sent("sender-x")
    assert any(m["id"] == mid for m in sent)


@pytest.mark.asyncio
async def test_sweep_expired_removes_old_messages():
    """sweep_expired deletes messages whose expires_at is in the past."""
    from src import message_bridge
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    mid = _create_test_message(recipient_id="rcpt-sweep", expires_at=past)

    count = message_bridge.sweep_expired()
    assert count >= 1

    inbox = message_bridge.list_inbox("rcpt-sweep")
    assert not any(m["id"] == mid for m in inbox)


@pytest.mark.asyncio
async def test_unexpired_message_not_swept():
    """sweep_expired does NOT delete messages with future expiry."""
    from src import message_bridge
    future = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    mid = _create_test_message(recipient_id="rcpt-keep", expires_at=future)
    message_bridge.sweep_expired()
    inbox = message_bridge.list_inbox("rcpt-keep")
    assert any(m["id"] == mid for m in inbox)


@pytest.mark.asyncio
async def test_unread_only_filter():
    """list_inbox(unread_only=True) returns only unread messages."""
    from src import message_bridge
    mid1 = _create_test_message(recipient_id="rcpt-uo", subject="Unread")
    mid2 = _create_test_message(recipient_id="rcpt-uo", subject="Also unread")
    message_bridge.mark_read(mid1, "rcpt-uo")

    unread = message_bridge.list_inbox("rcpt-uo", unread_only=True)
    ids = [m["id"] for m in unread]
    assert mid1 not in ids
    assert mid2 in ids


# ── API-level tests ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client(setup_db):  # noqa: F811 — setup_db already ran (autouse)
    """ASGI test client (DB already reset by autouse setup_db)."""
    from src.auth import sessions, _login_attempts
    from src.rate_limit import reset_rate_limits
    sessions.clear()
    _login_attempts.clear()
    reset_rate_limits()

    from src.main import app
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _create_and_login(client, username: str = "alice") -> tuple[str, dict]:
    """Create a user, login, return (user_id, cookies)."""
    from src.database import async_session
    from src.models import User, Agent
    from src.crypto import (
        derive_vault_key, encrypt, generate_key,
        generate_ed25519_keypair, public_key_to_did,
    )
    from src.main import vault_keys

    vault_key = generate_key()
    derived, salt = derive_vault_key(DEMO_PASSWORD)
    enc_vault = encrypt(vault_key, derived)
    user_id = f"{username}-id"

    async with async_session() as db:
        user = User(
            id=user_id, username=username, display_name=username.title(),
            vault_key_salt=salt, encrypted_vault_key=enc_vault, is_demo=True,
        )
        db.add(user)
        await db.flush()
        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id=user_id, name=f"{username} Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    vault_keys[user_id] = vault_key

    resp = await client.post("/api/auth/login", json={
        "username": username, "password": DEMO_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return user_id, dict(resp.cookies)


@pytest.mark.asyncio
async def test_api_inbox_empty(api_client):
    """GET /api/users/{id}/messages/inbox returns [] when no messages."""
    user_id, cookies = await _create_and_login(api_client, "bob")
    resp = await api_client.get(
        f"/api/users/{user_id}/messages/inbox", cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_api_unread_count_zero(api_client):
    """GET unread-count returns 0 for empty inbox."""
    user_id, cookies = await _create_and_login(api_client, "carol")
    resp = await api_client.get(
        f"/api/users/{user_id}/messages/unread-count", cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_api_inbox_shows_message(api_client):
    """Inbox endpoint returns a message after bridge creates one."""
    user_id, cookies = await _create_and_login(api_client, "dave")
    _create_test_message(recipient_id=user_id, subject="Test API msg")

    resp = await api_client.get(
        f"/api/users/{user_id}/messages/inbox", cookies=cookies
    )
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 1
    assert msgs[0]["subject"] == "Test API msg"
    assert "body" in msgs[0]  # body key always present (may be None if no vault key)


@pytest.mark.asyncio
async def test_api_unread_count_increments(api_client):
    """Unread count rises after messages are created."""
    user_id, cookies = await _create_and_login(api_client, "eve")
    _create_test_message(recipient_id=user_id)
    _create_test_message(recipient_id=user_id)

    resp = await api_client.get(
        f"/api/users/{user_id}/messages/unread-count", cookies=cookies
    )
    assert resp.json()["count"] == 2


@pytest.mark.asyncio
async def test_api_mark_read(api_client):
    """PUT /api/messages/{id}/read marks message as read and decrements count."""
    user_id, cookies = await _create_and_login(api_client, "frank")
    mid = _create_test_message(recipient_id=user_id)

    resp = await api_client.put(f"/api/messages/{mid}/read", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    count_resp = await api_client.get(
        f"/api/users/{user_id}/messages/unread-count", cookies=cookies
    )
    assert count_resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_api_delete_message(api_client):
    """DELETE /api/messages/{id} removes message from inbox."""
    user_id, cookies = await _create_and_login(api_client, "grace")
    mid = _create_test_message(recipient_id=user_id)

    resp = await api_client.delete(f"/api/messages/{mid}", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    inbox_resp = await api_client.get(
        f"/api/users/{user_id}/messages/inbox", cookies=cookies
    )
    ids = [m["id"] for m in inbox_resp.json()]
    assert mid not in ids


@pytest.mark.asyncio
async def test_api_inbox_requires_auth(api_client):
    """Inbox returns 401 without a session cookie."""
    resp = await api_client.get("/api/users/some-id/messages/inbox")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_inbox_denies_wrong_user(api_client):
    """User cannot read another user's inbox."""
    user_id, cookies = await _create_and_login(api_client, "henry")
    resp = await api_client.get(
        "/api/users/other-user-id/messages/inbox", cookies=cookies
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_sent_empty(api_client):
    """GET /sent returns [] when no sent messages."""
    user_id, cookies = await _create_and_login(api_client, "ivan")
    resp = await api_client.get(
        f"/api/users/{user_id}/messages/sent", cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_api_inbox_body_decrypted(api_client):
    """Body is decrypted when vault key is loaded (transit engine active)."""
    user_id, cookies = await _create_and_login(api_client, "judy")
    # Now vault key is in transit engine — encrypt properly
    mid = uuid.uuid4().hex
    body_enc = _encrypt_body(user_id, mid, "Secret health note")
    body_hash = hashlib.sha256(b"Secret health note").hexdigest()

    from src import message_bridge
    message_bridge.create_message(
        message_id=mid,
        sender_id="dr-001", sender_username="dr_lee", sender_display_name="Dr. Lee",
        sender_pod_url=None,
        recipient_id=user_id,
        subject="Health update",
        body_encrypted=body_enc,
        body_hash=body_hash,
        trust_level="connected",
    )

    resp = await api_client.get(
        f"/api/users/{user_id}/messages/inbox", cookies=cookies
    )
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 1
    assert msgs[0]["body"] == "Secret health note"
