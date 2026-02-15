"""Tests for federation security hardening — auth, ghost cleanup, rate limiting, DID spoofing."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models import (
    Base, Connection, KnowledgeCapsule, Network, NetworkMembership,
    PeerPod, PoolInviteToken, User,
)
from src.federation import cleanup_ghosts_for_pod, get_or_create_ghost_user


# ── Fixtures ──


@pytest_asyncio.fixture
async def api_db():
    """Reset DB for API tests."""
    from src.database import init_db, drop_db
    from src.auth import sessions, _login_attempts
    from src.rate_limit import reset_rate_limits
    from src.federation_auth import reset_federation_auth_state
    sessions.clear()
    _login_attempts.clear()
    reset_rate_limits()
    reset_federation_auth_state()
    await drop_db()
    await init_db()
    yield
    await drop_db()


@pytest_asyncio.fixture
async def api_client(api_db):
    """Create an async API test client."""
    from src.main import app
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


DEMO_PASSWORD = "TrustMesh-demo-2026"


async def _create_user_and_login(api_client, username="testuser", display_name="Test User"):
    """Helper: create a user via API and login, return session cookies."""
    from src.database import async_session
    from src.models import User
    from src.crypto import derive_vault_key, encrypt, generate_key, generate_ed25519_keypair, public_key_to_did
    from src.models import Agent

    vault_key = generate_key()
    derived, salt = derive_vault_key(DEMO_PASSWORD)
    enc_vault = encrypt(vault_key, derived)

    async with async_session() as db:
        user = User(
            id=f"{username}-id", username=username, display_name=display_name,
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
            is_demo=True,
        )
        db.add(user)
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id=user.id, name=f"{display_name} Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    from src.main import vault_keys
    vault_keys[f"{username}-id"] = vault_key

    resp = await api_client.post("/api/auth/login", json={
        "username": username,
        "password": DEMO_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.cookies


# ── Fix 1: Auth on federation mutation endpoints ──


@pytest.mark.asyncio
async def test_add_peer_requires_auth(api_client):
    """POST /api/pod/peers without session or secret returns 401."""
    resp = await api_client.post("/api/pod/peers", json={"url": "http://evil.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_remove_peer_requires_auth(api_client):
    """DELETE /api/pod/peers/{id} without auth returns 401."""
    resp = await api_client.delete("/api/pod/peers/some-id")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ping_peer_requires_auth(api_client):
    """POST /api/pod/peers/{id}/ping without auth returns 401."""
    resp = await api_client.post("/api/pod/peers/some-id/ping")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_add_peer_with_session_auth(api_client):
    """POST /api/pod/peers with session auth works (502 because peer is unreachable, not 401)."""
    cookies = await _create_user_and_login(api_client)
    resp = await api_client.post(
        "/api/pod/peers", json={"url": "http://unreachable-peer.local:9999"},
        cookies=cookies,
    )
    # 502 means auth passed but peer is unreachable — auth worked
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_add_peer_with_federation_secret(api_client):
    """POST /api/pod/peers with X-Pool-Sync-Secret header works."""
    with patch("src.routes.pod.POOL_SYNC_SECRET", "test-secret-123"):
        resp = await api_client.post(
            "/api/pod/peers", json={"url": "http://unreachable-peer.local:9999"},
            headers={"X-Pool-Sync-Secret": "test-secret-123"},
        )
    # 502 means auth passed but peer is unreachable
    assert resp.status_code == 502


# ── Fix 2: Pool-sync shared secret ──


@pytest.mark.asyncio
async def test_pool_sync_requires_secret(api_client):
    """POST /api/pod/pool-sync without secret returns 403 or 503."""
    with patch("src.routes.pod.POOL_SYNC_SECRET", "test-secret"):
        resp = await api_client.post("/api/pod/pool-sync", json={
            "network_name": "Evil Pool",
            "creator_pod_url": "http://evil.com",
            "members": [],
        })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pool_sync_no_secret_configured(api_client):
    """POST /api/pod/pool-sync with no TRUSTMESH_POOL_SYNC_SECRET returns 503."""
    with patch("src.routes.pod.POOL_SYNC_SECRET", ""):
        resp = await api_client.post("/api/pod/pool-sync", json={
            "network_name": "Pool",
            "creator_pod_url": "http://example.com",
            "members": [],
        })
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_pool_sync_with_valid_secret(api_client):
    """POST /api/pod/pool-sync with correct secret succeeds."""
    # Create a local user first (pool-sync needs one)
    from src.database import async_session as _as

    async with _as() as db:
        user = User(id="sync-user-id", username="sync_user", display_name="Sync User")
        db.add(user)
        await db.commit()

    with patch("src.routes.pod.POOL_SYNC_SECRET", "correct-secret"):
        resp = await api_client.post(
            "/api/pod/pool-sync",
            json={
                "network_name": "Test Pool",
                "creator_pod_url": "http://localhost:8000",
                "members": [],
            },
            headers={"X-Pool-Sync-Secret": "correct-secret"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "synced"


# ── Fix 3: Pool invite send — owner only ──


@pytest.mark.asyncio
async def test_pool_invite_send_owner_only(api_client):
    """Non-owner member trying to send pool invite gets 403."""
    from src.database import async_session
    from src.crypto import derive_vault_key, encrypt, generate_key

    # Create owner and member users
    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    async with async_session() as db:
        owner = User(
            id="owner-inv-id", username="owner_inv", display_name="Owner",
            vault_key_salt=salt, encrypted_vault_key=enc_vault, is_demo=True,
        )
        member = User(
            id="member-inv-id", username="member_inv", display_name="Member",
            vault_key_salt=salt, encrypted_vault_key=enc_vault, is_demo=True,
        )
        db.add_all([owner, member])
        await db.flush()

        network = Network(id="invite-net-id", owner_id="owner-inv-id", name="Invite Pool")
        db.add(network)
        await db.flush()

        db.add(NetworkMembership(network_id="invite-net-id", user_id="owner-inv-id", role="owner"))
        db.add(NetworkMembership(network_id="invite-net-id", user_id="member-inv-id", role="member"))
        await db.commit()

    # Login as the non-owner member
    from src.main import vault_keys
    vault_keys["member-inv-id"] = vault_key
    vault_keys["owner-inv-id"] = vault_key

    member_cookies = await _create_user_and_login(api_client, "member_inv2", "Member 2")
    # We need to use member-inv-id's session, let's just login directly
    from src.auth import sessions
    # Create session for member
    import secrets as _secrets
    sid = _secrets.token_hex(32)
    sessions[sid] = ("member-inv-id", __import__("time").time())

    resp = await api_client.post(
        "/api/pod/pool-invite/send",
        json={
            "network_id": "invite-net-id",
            "target_pod_url": "http://other:8001",
            "target_username": "remote_user",
            "target_display_name": "Remote User",
            "target_did": "did:key:z6MkRemoteInv",
        },
        cookies={"trustmesh_session": sid},
    )
    assert resp.status_code == 403
    assert "owner" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pool_invite_send_owner_succeeds(api_client):
    """Owner can send pool invite."""
    from src.database import async_session
    from src.crypto import derive_vault_key, encrypt, generate_key, generate_ed25519_keypair, public_key_to_did
    from src.models import Agent

    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    async with async_session() as db:
        owner = User(
            id="owner-send-id", username="owner_send", display_name="Owner Send",
            vault_key_salt=salt, encrypted_vault_key=enc_vault, is_demo=True,
        )
        db.add(owner)
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id="owner-send-id", name="Owner Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)

        network = Network(id="send-net-id", owner_id="owner-send-id", name="Send Pool")
        db.add(network)
        await db.flush()

        db.add(NetworkMembership(network_id="send-net-id", user_id="owner-send-id", role="owner"))
        await db.commit()

    from src.main import vault_keys
    vault_keys["owner-send-id"] = vault_key

    from src.auth import sessions
    import secrets as _secrets
    sid = _secrets.token_hex(32)
    sessions[sid] = ("owner-send-id", __import__("time").time())

    # The actual HTTP call to the remote pod will fail, but the endpoint should create
    # the ghost and token locally before that
    resp = await api_client.post(
        "/api/pod/pool-invite/send",
        json={
            "network_id": "send-net-id",
            "target_pod_url": "http://other:8001",
            "target_username": "remote_user",
            "target_display_name": "Remote User",
            "target_did": "did:key:z6MkRemoteSend",
        },
        cookies={"trustmesh_session": sid},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"


# ── Fix 4: Ghost cascade on peer removal ──


@pytest_asyncio.fixture
async def db():
    """In-memory test database for unit tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_ghosts_for_pod(db):
    """cleanup_ghosts_for_pod removes ghosts, connections, and memberships from a pod."""
    # Create local user
    local = User(id="local-id", username="local", display_name="Local User")
    db.add(local)

    # Create ghosts from partner pod
    ghost1 = await get_or_create_ghost_user(db, "g1", "Ghost 1", "did:g1", "http://partner:8001")
    ghost2 = await get_or_create_ghost_user(db, "g2", "Ghost 2", "did:g2", "http://partner:8001")
    # Ghost from a different pod (should NOT be cleaned up)
    ghost3 = await get_or_create_ghost_user(db, "g3", "Ghost 3", "did:g3", "http://other:8002")
    await db.flush()

    # Network and memberships
    net = Network(id="net-id", owner_id="local-id", name="Test Net")
    db.add(net)
    await db.flush()
    db.add(NetworkMembership(network_id="net-id", user_id="local-id", role="owner"))
    db.add(NetworkMembership(network_id="net-id", user_id=ghost1.id, role="remote_member"))
    db.add(NetworkMembership(network_id="net-id", user_id=ghost2.id, role="remote_member"))
    db.add(NetworkMembership(network_id="net-id", user_id=ghost3.id, role="remote_member"))

    # Connections
    db.add(Connection(from_user_id=ghost1.id, to_user_id="local-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    db.add(Connection(from_user_id=ghost2.id, to_user_id="local-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    db.add(Connection(from_user_id=ghost3.id, to_user_id="local-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    await db.commit()

    # Clean up ghosts from partner pod
    stats = await cleanup_ghosts_for_pod(db, "http://partner:8001")
    await db.commit()

    assert stats["ghosts_removed"] == 2
    assert stats["connections_removed"] == 2
    assert stats["memberships_removed"] == 2

    # Verify ghosts from partner are gone
    result = await db.execute(
        select(User).where(User.remote_pod_url == "http://partner:8001")
    )
    assert result.scalars().all() == []

    # Verify ghost from other pod still exists
    result = await db.execute(
        select(User).where(User.remote_pod_url == "http://other:8002")
    )
    assert result.scalar_one_or_none() is not None

    # Verify ghost3's connection and membership still exist
    result = await db.execute(
        select(Connection).where(Connection.from_user_id == ghost3.id)
    )
    assert result.scalar_one_or_none() is not None

    result = await db.execute(
        select(NetworkMembership).where(NetworkMembership.user_id == ghost3.id)
    )
    assert result.scalar_one_or_none() is not None


# ── Fix 5: Network member removal ghost cascade ──


@pytest.mark.asyncio
async def test_ghost_cleanup_on_member_removal(api_client):
    """Removing a ghost with zero other memberships deletes the ghost user."""
    from src.database import async_session

    async with async_session() as db:
        owner = User(id="rm-owner-id", username="rm_owner", display_name="RM Owner")
        db.add(owner)
        await db.flush()

        network = Network(id="rm-net-id", owner_id="rm-owner-id", name="RM Net")
        db.add(network)
        await db.flush()

        ghost = User(
            id="rm-ghost-id", username="remote:rmghost@partner",
            display_name="RM Ghost", is_remote=True,
            remote_pod_url="http://partner:8001", remote_did="did:key:rmghost",
        )
        db.add(ghost)
        await db.flush()

        db.add(NetworkMembership(network_id="rm-net-id", user_id="rm-owner-id", role="owner"))
        db.add(NetworkMembership(network_id="rm-net-id", user_id="rm-ghost-id", role="remote_member"))
        db.add(Connection(
            from_user_id="rm-ghost-id", to_user_id="rm-owner-id",
            status="accepted", accepted_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    from src.auth import sessions
    import secrets as _secrets
    sid = _secrets.token_hex(32)
    sessions[sid] = ("rm-owner-id", __import__("time").time())

    resp = await api_client.delete(
        "/api/networks/rm-net-id/members/rm-ghost-id",
        cookies={"trustmesh_session": sid},
    )
    assert resp.status_code == 200

    # Ghost should be fully cleaned up
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == "rm-ghost-id"))
        assert result.scalar_one_or_none() is None

        result = await db.execute(
            select(Connection).where(
                (Connection.from_user_id == "rm-ghost-id") | (Connection.to_user_id == "rm-ghost-id")
            )
        )
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_ghost_partial_cleanup_keeps_user(api_client):
    """Removing a ghost from one network keeps it if it has other memberships."""
    from src.database import async_session

    async with async_session() as db:
        owner = User(id="pc-owner-id", username="pc_owner", display_name="PC Owner")
        db.add(owner)
        await db.flush()

        net1 = Network(id="pc-net1-id", owner_id="pc-owner-id", name="PC Net 1")
        net2 = Network(id="pc-net2-id", owner_id="pc-owner-id", name="PC Net 2")
        db.add_all([net1, net2])
        await db.flush()

        ghost = User(
            id="pc-ghost-id", username="remote:pcghost@partner",
            display_name="PC Ghost", is_remote=True,
            remote_pod_url="http://partner:8001", remote_did="did:key:pcghost",
        )
        db.add(ghost)
        await db.flush()

        db.add(NetworkMembership(network_id="pc-net1-id", user_id="pc-owner-id", role="owner"))
        db.add(NetworkMembership(network_id="pc-net2-id", user_id="pc-owner-id", role="owner"))
        db.add(NetworkMembership(network_id="pc-net1-id", user_id="pc-ghost-id", role="remote_member"))
        db.add(NetworkMembership(network_id="pc-net2-id", user_id="pc-ghost-id", role="remote_member"))
        db.add(Connection(
            from_user_id="pc-ghost-id", to_user_id="pc-owner-id",
            status="accepted", accepted_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    from src.auth import sessions
    import secrets as _secrets
    sid = _secrets.token_hex(32)
    sessions[sid] = ("pc-owner-id", __import__("time").time())

    # Remove ghost from net1 only
    resp = await api_client.delete(
        "/api/networks/pc-net1-id/members/pc-ghost-id",
        cookies={"trustmesh_session": sid},
    )
    assert resp.status_code == 200

    # Ghost should still exist (has membership in net2)
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == "pc-ghost-id"))
        assert result.scalar_one_or_none() is not None

        # Still has membership in net2
        result = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.user_id == "pc-ghost-id",
                NetworkMembership.network_id == "pc-net2-id",
            )
        )
        assert result.scalar_one_or_none() is not None


# ── Fix 6: A2A pod URL verification ──


@pytest.mark.asyncio
async def test_a2a_pod_url_verification(api_client):
    """A2A message from ghost DID with wrong pod URL gets public trust (not elevated)."""
    from src.database import async_session
    from src.crypto import generate_ed25519_keypair, public_key_to_did, derive_vault_key, encrypt, generate_key
    from src.models import Agent

    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    async with async_session() as db:
        target = User(
            id="a2a-target-id", username="a2a_target", display_name="A2A Target",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        ghost = User(
            username="remote:a2aghost@partner",
            display_name="A2A Ghost",
            is_remote=True,
            remote_pod_url="http://partner:8001",
            remote_did="did:key:z6MkA2AGhost",
        )
        db.add_all([target, ghost])
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id="a2a-target-id", name="A2A Target Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    from src.main import vault_keys
    vault_keys["a2a-target-id"] = vault_key

    # Send A2A message claiming ghost's DID but from wrong pod
    resp = await api_client.post("/api/pod/a2a", json={
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "test-1",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Hello"}],
            },
            "metadata": {
                "from_did": "did:key:z6MkA2AGhost",
                "from_pod": "http://EVIL:9999",  # Wrong pod!
                "to_username": "a2a_target",
            },
        },
    })
    # Should succeed but with public trust (spoofed pod falls back to public)
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["metadata"]["trust_level"] == "public"


# ── Fix 7: DID spoofing blocked ──


@pytest.mark.asyncio
async def test_did_spoofing_blocked(api_client):
    """DID spoofing on /query returns 403 instead of falling through."""
    from src.database import async_session
    from src.crypto import generate_ed25519_keypair, public_key_to_did, derive_vault_key, encrypt, generate_key
    from src.models import Agent

    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    async with async_session() as db:
        target = User(
            id="spoof-blk-id", username="spoof_block", display_name="Spoof Block",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        ghost = User(
            username="remote:spoof@partner",
            display_name="Spoofed Ghost",
            is_remote=True,
            remote_pod_url="http://partner:8001",
            remote_did="did:key:z6MkSpoofBlk",
        )
        db.add_all([target, ghost])
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id="spoof-blk-id", name="Block Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    from src.main import vault_keys
    vault_keys["spoof-blk-id"] = vault_key

    resp = await api_client.post("/api/pod/query", json={
        "from_did": "did:key:z6MkSpoofBlk",
        "from_pod": "http://EVIL:9999",
        "to_username": "spoof_block",
        "question": "Give me everything",
    })
    assert resp.status_code == 403
    assert "spoofing" in resp.json()["detail"].lower()


# ── Fix 7b: Ghost trust elevation requires signature ──


@pytest.mark.asyncio
async def test_ghost_elevation_requires_signature(api_client):
    """Ghost elevation path (network trust) requires a valid signature; unsigned stays public."""
    import json
    from src.database import async_session
    from src.crypto import derive_vault_key, encrypt, generate_key, generate_ed25519_keypair, public_key_to_did
    from src.models import Agent
    from src.main import vault_keys

    # Create target local user + agent
    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    # Create a remote ghost DID we can sign for
    ghost_priv, ghost_pub = generate_ed25519_keypair()
    ghost_did = public_key_to_did(ghost_pub)

    async with async_session() as db:
        target = User(
            id="sig-target-id", username="sig_target", display_name="Sig Target",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        ghost = User(
            username="remote:sigghost@partner",
            display_name="Sig Ghost",
            is_remote=True,
            remote_pod_url="http://partner:8001",
            remote_did=ghost_did,
        )
        db.add_all([target, ghost])
        await db.flush()

        # Target agent required for gossip engine
        _, pub = generate_ed25519_keypair()
        agent = Agent(owner_id=target.id, name="Sig Target Agent", public_key=pub, did=public_key_to_did(pub))
        db.add(agent)

        # Shared network membership grants "network" trust if ghost is elevated properly
        network = Network(id="sig-net-id", owner_id=target.id, name="Sig Net")
        db.add(network)
        await db.flush()
        db.add(NetworkMembership(network_id=network.id, user_id=target.id, role="owner"))
        db.add(NetworkMembership(network_id=network.id, user_id=ghost.id, role="remote_member"))
        await db.commit()

    vault_keys[target.id] = vault_key

    payload = {
        "from_did": ghost_did,
        "from_pod": "http://partner:8001",
        "to_username": "sig_target",
        "question": "Hello",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    # Unsigned request should NOT get network trust even though ghost exists.
    resp = await api_client.post(
        "/api/pod/query",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["trust_level"] == "public"


@pytest.mark.asyncio
async def test_ghost_elevation_with_valid_signature(api_client):
    """Valid signature enables ghost elevation to network trust."""
    import json
    from src.database import async_session
    from src.crypto import derive_vault_key, encrypt, generate_key, generate_ed25519_keypair, public_key_to_did
    from src.federation_auth import sign_federation_request
    from src.models import Agent
    from src.main import vault_keys

    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    ghost_priv, ghost_pub = generate_ed25519_keypair()
    ghost_did = public_key_to_did(ghost_pub)

    async with async_session() as db:
        target = User(
            id="sig2-target-id", username="sig2_target", display_name="Sig2 Target",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        ghost = User(
            username="remote:sig2ghost@partner",
            display_name="Sig2 Ghost",
            is_remote=True,
            remote_pod_url="http://partner:8001",
            remote_did=ghost_did,
        )
        db.add_all([target, ghost])
        await db.flush()

        _, pub = generate_ed25519_keypair()
        agent = Agent(owner_id=target.id, name="Sig2 Target Agent", public_key=pub, did=public_key_to_did(pub))
        db.add(agent)

        network = Network(id="sig2-net-id", owner_id=target.id, name="Sig2 Net")
        db.add(network)
        await db.flush()
        db.add(NetworkMembership(network_id=network.id, user_id=target.id, role="owner"))
        db.add(NetworkMembership(network_id=network.id, user_id=ghost.id, role="remote_member"))
        # PeerPod record so ghost is not considered stale
        db.add(PeerPod(name="partner", url="http://partner:8001", status="active",
                       last_seen_at=datetime.now(timezone.utc)))
        await db.commit()

    vault_keys[target.id] = vault_key

    payload = {
        "from_did": ghost_did,
        "from_pod": "http://partner:8001",
        "to_username": "sig2_target",
        "question": "Hello",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig_headers = sign_federation_request(body, ghost_priv)

    resp = await api_client.post(
        "/api/pod/query",
        content=body,
        headers={"Content-Type": "application/json", **sig_headers},
    )
    assert resp.status_code == 200
    assert resp.json()["trust_level"] == "network"


# ── Fix 8: discover_agents pool leak ──


@pytest.mark.asyncio
async def test_discover_agents_hides_private_pools(db):
    """discover_agents only shows public network names, not private pools."""
    from src.agents import handle_discover_agents, ToolContext
    from src.models import Agent
    from src.crypto import generate_ed25519_keypair, public_key_to_did
    import json

    # Create users
    alice = User(id="alice-da-id", username="alice_da", display_name="Alice DA",
                 is_discoverable=True, bio="Test user")
    bob = User(id="bob-da-id", username="bob_da", display_name="Bob DA",
               is_discoverable=True, bio="Another user")
    db.add_all([alice, bob])
    await db.flush()

    priv, pub = generate_ed25519_keypair()
    agent = Agent(owner_id="alice-da-id", name="Alice Agent", public_key=pub, did=public_key_to_did(pub))
    db.add(agent)

    priv2, pub2 = generate_ed25519_keypair()
    agent2 = Agent(owner_id="bob-da-id", name="Bob Agent", public_key=pub2, did=public_key_to_did(pub2))
    db.add(agent2)

    # Create private and public networks
    private_net = Network(id="priv-net-id", owner_id="alice-da-id", name="Secret Club",
                          is_public=False)
    public_net = Network(id="pub-net-id", owner_id="alice-da-id", name="Public Group",
                         is_public=True)
    db.add_all([private_net, public_net])
    await db.flush()

    db.add(NetworkMembership(network_id="priv-net-id", user_id="bob-da-id", role="member"))
    db.add(NetworkMembership(network_id="pub-net-id", user_id="bob-da-id", role="member"))
    await db.commit()

    # Create a mock ToolContext
    ctx = ToolContext(
        db=db,
        owner_id="alice-da-id",
        owner_name="Alice DA",
        vault_key=b"test-key-unused",
        networks=[],
        query_depth=0,
        actions=[],
    )

    result = await handle_discover_agents(ctx, {})
    data = json.loads(result)

    # Find bob in the results
    bob_entry = next((a for a in data["agents"] if a["username"] == "bob_da"), None)
    assert bob_entry is not None
    # Should only show public network, not private one
    assert "Public Group" in bob_entry["pools"]
    assert "Secret Club" not in bob_entry["pools"]


# ── Fix 9: Global ghost cap ──


@pytest.mark.asyncio
async def test_global_ghost_cap_pool_invite(api_client):
    """Pool invite rejected when pod has >= MAX_GHOSTS_PER_POD ghost users."""
    from src.database import async_session

    async with async_session() as db:
        owner = User(id="gcap-owner-id", username="gcap_owner", display_name="GCap Owner")
        db.add(owner)
        await db.flush()

        network = Network(id="gcap-net-id", owner_id="gcap-owner-id", name="GCap Net")
        db.add(network)
        await db.flush()

        db.add(NetworkMembership(network_id="gcap-net-id", user_id="gcap-owner-id", role="owner"))

        # Create ghosts up to the global cap (use lower cap for testing via patch)
        for i in range(5):
            ghost = User(
                username=f"remote:gcap{i}@other",
                display_name=f"GCap Ghost {i}",
                is_remote=True,
                remote_pod_url="http://other:8001",
                remote_did=f"did:key:gcap{i}",
            )
            db.add(ghost)

        token = PoolInviteToken(
            network_id="gcap-net-id",
            token="gcap-token",
            target_pod_url="http://other:8001",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(token)
        await db.commit()

    # Patch MAX_GHOSTS_PER_POD to 5 for testing
    with patch("src.routes.pod.MAX_GHOSTS_PER_POD", 5):
        resp = await api_client.post("/api/pod/pool-invite", json={
            "network_id": "gcap-net-id",
            "invite_token": "gcap-token",
            "from_pod": "http://other:8001",
            "username": "gcap_new",
            "display_name": "New Ghost",
            "did": "did:key:gcap_new",
        })
    assert resp.status_code == 429
    assert "capacity" in resp.json()["detail"].lower()


# ── Fix 10: Inbound query rate limiting ──


@pytest.mark.asyncio
async def test_inbound_query_rate_limit(api_client):
    """Rapid queries from same DID get rate limited."""
    from src.database import async_session
    from src.crypto import generate_ed25519_keypair, public_key_to_did, derive_vault_key, encrypt, generate_key
    from src.models import Agent

    vault_key = generate_key()
    derived, salt = derive_vault_key("TestPass123!")
    enc_vault = encrypt(vault_key, derived)

    async with async_session() as db:
        target = User(
            id="rl-target-id", username="rl_target", display_name="RL Target",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        db.add(target)
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id="rl-target-id", name="RL Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    from src.main import vault_keys
    vault_keys["rl-target-id"] = vault_key

    # The rate limiter allows 5 queries per minute (burst).
    # Send 6 queries rapidly — the 6th should be rate limited.
    # Use a unique DID to avoid interference from other tests.
    test_did = "did:key:z6MkRateLimit"
    for i in range(5):
        resp = await api_client.post("/api/pod/query", json={
            "from_did": test_did,
            "from_pod": "http://test:8001",
            "to_username": "rl_target",
            "question": f"Query {i}",
        })
        assert resp.status_code == 200, f"Query {i} failed: {resp.text}"

    # 6th query should be rate limited
    resp = await api_client.post("/api/pod/query", json={
        "from_did": test_did,
        "from_pod": "http://test:8001",
        "to_username": "rl_target",
        "question": "One too many",
    })
    assert resp.status_code == 429


# ── Cleanup test for cleanup_ghosts_for_pod with no ghosts ──


@pytest.mark.asyncio
async def test_cleanup_ghosts_no_op(db):
    """cleanup_ghosts_for_pod with no matching ghosts returns zeros."""
    stats = await cleanup_ghosts_for_pod(db, "http://nonexistent:9999")
    assert stats["ghosts_removed"] == 0
    assert stats["connections_removed"] == 0
    assert stats["memberships_removed"] == 0
