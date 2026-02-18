"""Tests for pool invite endpoints — send, receive, accept, expiry, auth, and caps."""

import secrets as _secrets
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select, func

from src.models import (
    Base, Connection, Network, NetworkMembership,
    PoolInviteToken, User, Agent,
)


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


async def _create_user(username, display_name, *, with_agent=False):
    """Create a user directly in the DB and store vault key. Returns user_id."""
    from src.database import async_session
    from src.crypto import derive_vault_key, encrypt, generate_key
    from src.main import vault_keys

    vault_key = generate_key()
    derived, salt = derive_vault_key(DEMO_PASSWORD)
    enc_vault = encrypt(vault_key, derived)
    user_id = f"{username}-id"

    async with async_session() as db:
        user = User(
            id=user_id,
            username=username,
            display_name=display_name,
            vault_key_salt=salt,
            encrypted_vault_key=enc_vault,
            is_demo=True,
        )
        db.add(user)
        await db.flush()

        if with_agent:
            from src.crypto import generate_ed25519_keypair, public_key_to_did

            priv, pub = generate_ed25519_keypair()
            agent = Agent(
                owner_id=user_id,
                name=f"{display_name} Agent",
                public_key=pub,
                did=public_key_to_did(pub),
            )
            db.add(agent)

        await db.commit()

    vault_keys[user_id] = vault_key
    return user_id


def _inject_session(user_id):
    """Create a session for user_id and return cookie dict."""
    from src.auth import sessions

    sid = _secrets.token_hex(32)
    sessions[sid] = (user_id, time.time())
    return {"trustmesh_session": sid}


async def _create_network(owner_id, network_id, name="Test Pool"):
    """Create a network owned by owner_id with owner membership."""
    from src.database import async_session

    async with async_session() as db:
        network = Network(id=network_id, owner_id=owner_id, name=name)
        db.add(network)
        await db.flush()
        db.add(NetworkMembership(
            network_id=network_id, user_id=owner_id, role="owner",
        ))
        await db.commit()


async def _create_invite_token(network_id, target_pod_url, *, token=None, expires_delta=None, status="pending"):
    """Create a PoolInviteToken and return the token string."""
    from src.database import async_session

    token_str = token or _secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=24))

    async with async_session() as db:
        invite = PoolInviteToken(
            network_id=network_id,
            token=token_str,
            target_pod_url=target_pod_url,
            status=status,
            expires_at=expires,
        )
        db.add(invite)
        await db.commit()

    return token_str


# ── Test 1: POST pool-invite/send creates token and ghost ──


@pytest.mark.asyncio
async def test_send_pool_invite_creates_token_and_ghost(api_client):
    """Owner sending a pool invite creates a PoolInviteToken and ghost user locally."""
    owner_id = await _create_user("inv_owner", "Invite Owner", with_agent=True)
    await _create_network(owner_id, "inv-net-1", "Invite Pool")
    cookies = _inject_session(owner_id)

    resp = await api_client.post(
        "/api/pod/pool-invite/send",
        json={
            "network_id": "inv-net-1",
            "target_pod_url": "http://remote-pod:8001",
            "target_username": "remote_alice",
            "target_display_name": "Remote Alice",
            "target_did": "did:key:z6MkRemoteAlice",
        },
        cookies=cookies,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["network_name"] == "Invite Pool"
    assert "ghost_user_id" in data
    assert "invite_token" in data

    # Verify token was persisted in DB
    from src.database import async_session

    async with async_session() as db:
        result = await db.execute(
            select(PoolInviteToken).where(
                PoolInviteToken.network_id == "inv-net-1"
            )
        )
        token = result.scalar_one_or_none()
        assert token is not None
        assert token.target_pod_url == "http://remote-pod:8001"
        assert token.status == "pending"

        # Verify ghost user was created
        ghost_result = await db.execute(
            select(User).where(User.remote_did == "did:key:z6MkRemoteAlice")
        )
        ghost = ghost_result.scalar_one_or_none()
        assert ghost is not None
        assert ghost.is_remote is True
        assert ghost.remote_pod_url == "http://remote-pod:8001"

        # Verify ghost was added to network
        mem_result = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.network_id == "inv-net-1",
                NetworkMembership.user_id == ghost.id,
            )
        )
        membership = mem_result.scalar_one_or_none()
        assert membership is not None
        assert membership.role == "remote_member"


# ── Test 2: Receive pool invite creates membership ──


@pytest.mark.asyncio
async def test_receive_pool_invite_creates_membership(api_client):
    """Receiving a valid pool invite creates a ghost user and network membership."""
    owner_id = await _create_user("recv_owner", "Recv Owner")
    await _create_network(owner_id, "recv-net-1", "Recv Pool")
    token_str = await _create_invite_token("recv-net-1", "http://sender:8002")

    resp = await api_client.post(
        "/api/pod/pool-invite",
        json={
            "network_id": "recv-net-1",
            "invite_token": token_str,
            "from_pod": "http://sender:8002",
            "username": "sender_bob",
            "display_name": "Sender Bob",
            "did": "did:key:z6MkSenderBob",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["network_name"] == "Recv Pool"
    assert "ghost_user_id" in data

    # Verify ghost and membership in DB
    from src.database import async_session

    async with async_session() as db:
        ghost_result = await db.execute(
            select(User).where(User.remote_did == "did:key:z6MkSenderBob")
        )
        ghost = ghost_result.scalar_one_or_none()
        assert ghost is not None
        assert ghost.is_remote is True

        mem_result = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.network_id == "recv-net-1",
                NetworkMembership.user_id == ghost.id,
            )
        )
        assert mem_result.scalar_one_or_none() is not None

        # Verify token was consumed
        token_result = await db.execute(
            select(PoolInviteToken).where(PoolInviteToken.token == token_str)
        )
        consumed_token = token_result.scalar_one()
        assert consumed_token.status == "consumed"


# ── Test 3: Duplicate accept returns error ──


@pytest.mark.asyncio
async def test_duplicate_accept_returns_error(api_client):
    """Using the same invite token twice returns 403 (token already consumed)."""
    owner_id = await _create_user("dup_owner", "Dup Owner")
    await _create_network(owner_id, "dup-net-1", "Dup Pool")
    token_str = await _create_invite_token("dup-net-1", "http://sender:8003")

    # First accept succeeds
    resp1 = await api_client.post(
        "/api/pod/pool-invite",
        json={
            "network_id": "dup-net-1",
            "invite_token": token_str,
            "from_pod": "http://sender:8003",
            "username": "dup_user",
            "display_name": "Dup User",
            "did": "did:key:z6MkDupUser",
        },
    )
    assert resp1.status_code == 200

    # Second accept with same token fails
    resp2 = await api_client.post(
        "/api/pod/pool-invite",
        json={
            "network_id": "dup-net-1",
            "invite_token": token_str,
            "from_pod": "http://sender:8003",
            "username": "dup_user2",
            "display_name": "Dup User 2",
            "did": "did:key:z6MkDupUser2",
        },
    )
    assert resp2.status_code == 403
    assert "invalid" in resp2.json()["detail"].lower() or "expired" in resp2.json()["detail"].lower()


# ── Test 4: Expired invite returns error ──


@pytest.mark.asyncio
async def test_expired_invite_returns_error(api_client):
    """An invite token past its expiration date returns 403."""
    owner_id = await _create_user("exp_owner", "Exp Owner")
    await _create_network(owner_id, "exp-net-1", "Exp Pool")

    # Create token that expired 1 hour ago
    token_str = await _create_invite_token(
        "exp-net-1", "http://sender:8004",
        expires_delta=timedelta(hours=-1),
    )

    resp = await api_client.post(
        "/api/pod/pool-invite",
        json={
            "network_id": "exp-net-1",
            "invite_token": token_str,
            "from_pod": "http://sender:8004",
            "username": "exp_user",
            "display_name": "Exp User",
            "did": "did:key:z6MkExpUser",
        },
    )
    assert resp.status_code == 403
    assert "expired" in resp.json()["detail"].lower()


# ── Test 5: Non-owner cannot send pool invite (403) ──


@pytest.mark.asyncio
async def test_non_owner_cannot_send_pool_invite(api_client):
    """A user who is not the network owner gets 403 when sending a pool invite."""
    owner_id = await _create_user("authz_owner", "Authz Owner", with_agent=True)
    member_id = await _create_user("authz_member", "Authz Member", with_agent=True)
    await _create_network(owner_id, "authz-net-1", "Authz Pool")

    # Add member to the network
    from src.database import async_session

    async with async_session() as db:
        db.add(NetworkMembership(
            network_id="authz-net-1", user_id=member_id, role="member",
        ))
        await db.commit()

    # Login as the non-owner member
    cookies = _inject_session(member_id)

    resp = await api_client.post(
        "/api/pod/pool-invite/send",
        json={
            "network_id": "authz-net-1",
            "target_pod_url": "http://remote:8005",
            "target_username": "remote_user",
            "target_display_name": "Remote User",
            "target_did": "did:key:z6MkRemoteAuthz",
        },
        cookies=cookies,
    )
    assert resp.status_code == 403
    assert "owner" in resp.json()["detail"].lower()


# ── Test 6: Invite for non-existent network returns 404 ──


@pytest.mark.asyncio
async def test_invite_for_nonexistent_network_returns_404(api_client):
    """Sending a pool invite for a network that does not exist returns 404."""
    owner_id = await _create_user("ne_owner", "NE Owner", with_agent=True)
    cookies = _inject_session(owner_id)

    resp = await api_client.post(
        "/api/pod/pool-invite/send",
        json={
            "network_id": "nonexistent-net-id",
            "target_pod_url": "http://remote:8006",
            "target_username": "remote_user",
            "target_display_name": "Remote User",
            "target_did": "did:key:z6MkRemoteNE",
        },
        cookies=cookies,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ── Test 7: Receive invite with wrong pod URL is rejected ──


@pytest.mark.asyncio
async def test_receive_invite_wrong_pod_url_rejected(api_client):
    """An invite token bound to one pod URL rejects requests from a different pod."""
    owner_id = await _create_user("pod_owner", "Pod Owner")
    await _create_network(owner_id, "pod-net-1", "Pod Pool")

    # Token bound to http://legit-sender:8007
    token_str = await _create_invite_token("pod-net-1", "http://legit-sender:8007")

    # Request comes from a different pod URL
    resp = await api_client.post(
        "/api/pod/pool-invite",
        json={
            "network_id": "pod-net-1",
            "invite_token": token_str,
            "from_pod": "http://evil-sender:9999",
            "username": "evil_user",
            "display_name": "Evil User",
            "did": "did:key:z6MkEvilUser",
        },
    )
    assert resp.status_code == 403
    assert "not valid for this sender" in resp.json()["detail"].lower()


# ── Test 8: Per-network ghost cap enforcement ──


@pytest.mark.asyncio
async def test_per_network_ghost_cap_enforcement(api_client):
    """Receiving an invite when the network already has GHOST_CAP_PER_NETWORK remote members returns 429."""
    owner_id = await _create_user("cap_owner", "Cap Owner")
    await _create_network(owner_id, "cap-net-1", "Cap Pool")

    from src.database import async_session

    # Fill the network with ghosts up to the cap (use a low cap for speed)
    test_cap = 3
    async with async_session() as db:
        for i in range(test_cap):
            ghost = User(
                username=f"remote:capghost{i}@other",
                display_name=f"Cap Ghost {i}",
                is_remote=True,
                remote_pod_url="http://other:8001",
                remote_did=f"did:key:capghost{i}",
            )
            db.add(ghost)
            await db.flush()
            db.add(NetworkMembership(
                network_id="cap-net-1",
                user_id=ghost.id,
                role="remote_member",
            ))
        await db.commit()

    token_str = await _create_invite_token("cap-net-1", "http://sender:8008")

    # Patch the cap to match our test setup
    with patch("src.routes.pod.GHOST_CAP_PER_NETWORK", test_cap):
        resp = await api_client.post(
            "/api/pod/pool-invite",
            json={
                "network_id": "cap-net-1",
                "invite_token": token_str,
                "from_pod": "http://sender:8008",
                "username": "one_too_many",
                "display_name": "One Too Many",
                "did": "did:key:z6MkOneTooMany",
            },
        )

    assert resp.status_code == 429
    assert "maximum" in resp.json()["detail"].lower() or "remote members" in resp.json()["detail"].lower()


# ── Test 9: Global ghost cap enforcement ──


@pytest.mark.asyncio
async def test_global_ghost_cap_enforcement(api_client):
    """Receiving an invite when the pod has MAX_GHOSTS_PER_POD total ghosts returns 429."""
    owner_id = await _create_user("gcap2_owner", "GCap2 Owner")
    await _create_network(owner_id, "gcap2-net-1", "GCap2 Pool")

    from src.database import async_session

    global_cap = 4
    async with async_session() as db:
        # Create ghosts spread across the pod (not all in this network)
        for i in range(global_cap):
            ghost = User(
                username=f"remote:gcap2ghost{i}@various",
                display_name=f"GCap2 Ghost {i}",
                is_remote=True,
                remote_pod_url=f"http://pod{i}:8001",
                remote_did=f"did:key:gcap2ghost{i}",
            )
            db.add(ghost)
        await db.commit()

    token_str = await _create_invite_token("gcap2-net-1", "http://sender:8009")

    with patch("src.routes.pod.MAX_GHOSTS_PER_POD", global_cap):
        resp = await api_client.post(
            "/api/pod/pool-invite",
            json={
                "network_id": "gcap2-net-1",
                "invite_token": token_str,
                "from_pod": "http://sender:8009",
                "username": "global_overflow",
                "display_name": "Global Overflow",
                "did": "did:key:z6MkGlobalOverflow",
            },
        )

    assert resp.status_code == 429
    assert "capacity" in resp.json()["detail"].lower()


# ── Test 10: Mismatched network_id in invite request is rejected ──


@pytest.mark.asyncio
async def test_mismatched_network_id_rejected(api_client):
    """Providing a network_id that differs from the token's network_id returns 400."""
    owner_id = await _create_user("mis_owner", "Mis Owner")
    await _create_network(owner_id, "mis-net-1", "Mis Pool 1")
    await _create_network(owner_id, "mis-net-2", "Mis Pool 2")

    # Token is for mis-net-1
    token_str = await _create_invite_token("mis-net-1", "http://sender:8010")

    # Request claims mis-net-2
    resp = await api_client.post(
        "/api/pod/pool-invite",
        json={
            "network_id": "mis-net-2",
            "invite_token": token_str,
            "from_pod": "http://sender:8010",
            "username": "mis_user",
            "display_name": "Mis User",
            "did": "did:key:z6MkMisUser",
        },
    )
    assert resp.status_code == 400
    assert "does not match" in resp.json()["detail"].lower()
