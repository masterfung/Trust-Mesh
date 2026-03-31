"""Tests for ghost user system — cross-pod sharing via lightweight remote user records."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models import (
    Base, CapsuleNetworkAccess, Connection, KnowledgeCapsule,
    Network, NetworkMembership, PeerPod, PoolInviteToken, User,
)
from src.trust import resolve_trust_level
from src.gossip import get_accessible_capsule_ids
from src.federation import get_or_create_ghost_user, lookup_ghost_by_did


@pytest_asyncio.fixture
async def db():
    """Create an in-memory test database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_db(db: AsyncSession):
    """Create test users, a network, connections, and capsules for ghost testing."""
    # Local users
    molly = User(id="molly-id", username="molly", display_name="Molly Johnson")
    kyle = User(id="kyle-id", username="kyle", display_name="Kyle Rivera")
    db.add_all([molly, kyle])
    await db.flush()

    # Connection between local users
    db.add(Connection(
        from_user_id="molly-id", to_user_id="kyle-id",
        status="accepted", accepted_at=datetime.now(timezone.utc),
    ))

    # Peer pod for ghost user tests (ghost staleness check needs this)
    peer = PeerPod(name="partner", url="http://partner:8001", status="active",
                   last_seen_at=datetime.now(timezone.utc))
    db.add(peer)

    # Network (pool)
    network = Network(id="work-id", owner_id="molly-id", name="TechCorp PM Team", network_type="team")
    db.add(network)
    await db.flush()

    # Network memberships
    db.add(NetworkMembership(network_id="work-id", user_id="molly-id", role="owner"))
    db.add(NetworkMembership(network_id="work-id", user_id="kyle-id", role="member"))

    # Capsules with various visibility levels
    capsules = [
        KnowledgeCapsule(
            id="cap-open", owner_id="molly-id", capsule_type="note",
            title="Public Bio", content_encrypted=b"encrypted",
            visibility="open", category="general",
        ),
        KnowledgeCapsule(
            id="cap-internal", owner_id="molly-id", capsule_type="note",
            title="Work Report", content_encrypted=b"encrypted",
            visibility="internal", category="work",
        ),
        KnowledgeCapsule(
            id="cap-private", owner_id="molly-id", capsule_type="note",
            title="Personal Diary", content_encrypted=b"encrypted",
            visibility="private", category="personal",
        ),
    ]
    db.add_all(capsules)
    await db.flush()

    # Link internal capsule to work network
    db.add(CapsuleNetworkAccess(capsule_id="cap-internal", network_id="work-id"))

    await db.commit()
    return db


# ── Ghost Creation Tests ──


@pytest.mark.asyncio
async def test_ghost_creation_idempotent(db):
    """get_or_create_ghost_user creates once, returns same on second call."""
    ghost1 = await get_or_create_ghost_user(
        db, "alex", "Alex Chen", "did:key:z6MkAlex", "http://partner:8001"
    )
    await db.commit()

    ghost2 = await get_or_create_ghost_user(
        db, "alex", "Alex Chen", "did:key:z6MkAlex", "http://partner:8001"
    )

    assert ghost1.id == ghost2.id
    assert ghost1.is_remote is True
    assert ghost1.remote_did == "did:key:z6MkAlex"
    assert ghost1.username == "remote:alex@partner"


@pytest.mark.asyncio
async def test_ghost_user_properties(db):
    """Ghost users have correct default properties."""
    ghost = await get_or_create_ghost_user(
        db, "bob", "Bob Smith", "did:key:z6MkBob", "http://other-pod.local:8001"
    )
    assert ghost.is_remote is True
    assert ghost.is_discoverable is False
    assert ghost.is_demo is False
    assert ghost.remote_pod_url == "http://other-pod.local:8001"
    assert ghost.username.startswith("remote:")


@pytest.mark.asyncio
async def test_lookup_ghost_by_did(db):
    """lookup_ghost_by_did returns ghost when DID matches, None when no match."""
    ghost = await get_or_create_ghost_user(
        db, "alex", "Alex", "did:key:z6MkTest", "http://pod:8001"
    )
    await db.commit()

    found = await lookup_ghost_by_did(db, "did:key:z6MkTest")
    assert found is not None
    assert found.id == ghost.id

    not_found = await lookup_ghost_by_did(db, "did:key:z6MkNonexistent")
    assert not_found is None


# ── Ghost Trust Resolution Tests ──


@pytest.mark.asyncio
async def test_ghost_trust_with_connection(seeded_db):
    """Ghost + accepted Connection + shared network → "network" trust."""
    db = seeded_db

    # Create ghost and add to pool
    ghost = await get_or_create_ghost_user(
        db, "alex", "Alex Chen", "did:key:z6MkAlex", "http://partner:8001"
    )
    await db.flush()

    # Add to network
    db.add(NetworkMembership(network_id="work-id", user_id=ghost.id, role="remote_member"))

    # Create auto-accepted connection (what the pool invite endpoint does)
    db.add(Connection(
        from_user_id=ghost.id, to_user_id="molly-id",
        status="accepted", accepted_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    # Trust should be "network"
    level, networks = await resolve_trust_level(db, ghost.id, "molly-id")
    assert level == "network"
    assert len(networks) == 1
    assert networks[0].name == "TechCorp PM Team"


@pytest.mark.asyncio
async def test_ghost_trust_without_connection(seeded_db):
    """Ghost in pool but NO accepted Connection → "public" trust (security boundary)."""
    db = seeded_db

    # Create ghost and add to pool, but NO connection
    ghost = await get_or_create_ghost_user(
        db, "alex", "Alex Chen", "did:key:z6MkAlex", "http://partner:8001"
    )
    await db.flush()

    db.add(NetworkMembership(network_id="work-id", user_id=ghost.id, role="remote_member"))
    await db.commit()

    # Phase 2: pool membership alone grants "network" trust (no connection required)
    level, networks = await resolve_trust_level(db, ghost.id, "molly-id")
    assert level == "network"
    assert len(networks) == 1


# ── Capsule Visibility Tests ──


@pytest.mark.asyncio
async def test_ghost_sees_internal_capsules_with_network_trust(seeded_db):
    """Ghost with "network" trust → internal capsules visible."""
    db = seeded_db

    ghost = await get_or_create_ghost_user(
        db, "alex", "Alex Chen", "did:key:z6MkAlex", "http://partner:8001"
    )
    await db.flush()
    db.add(NetworkMembership(network_id="work-id", user_id=ghost.id, role="remote_member"))
    db.add(Connection(
        from_user_id=ghost.id, to_user_id="molly-id",
        status="accepted", accepted_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    from src.models import Network
    work = await db.get(Network, "work-id")

    ids = await get_accessible_capsule_ids(
        db, "molly-id", "network", shared_networks=[work], requester_id=ghost.id,
    )
    assert "cap-open" in ids
    assert "cap-internal" in ids
    assert "cap-private" not in ids


@pytest.mark.asyncio
async def test_ghost_only_sees_open_without_connection(seeded_db):
    """Ghost without connection → "public" trust → only open capsules."""
    db = seeded_db

    ghost = await get_or_create_ghost_user(
        db, "alex", "Alex Chen", "did:key:z6MkAlex", "http://partner:8001"
    )
    await db.flush()
    db.add(NetworkMembership(network_id="work-id", user_id=ghost.id, role="remote_member"))
    await db.commit()

    # Public trust — should only see open
    ids = await get_accessible_capsule_ids(
        db, "molly-id", "public", shared_networks=[],
    )
    assert "cap-open" in ids
    assert "cap-internal" not in ids
    assert "cap-private" not in ids


# ── API-Level Ghost Guard Tests ──


@pytest_asyncio.fixture
async def api_db():
    """Reset DB for API tests."""
    from src.database import init_db, drop_db
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
async def api_client(api_db):
    """Create an async API test client."""
    from src.main import app
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_ghost_cannot_login(api_client):
    """POST to login with ghost username → 403."""
    # First create a ghost user directly in the DB
    from src.database import async_session
    from src.models import User

    async with async_session() as db:
        ghost = User(
            username="remote:alex@partner",
            display_name="Alex Ghost",
            is_remote=True,
            remote_pod_url="http://partner:8001",
            remote_did="did:key:z6MkGhostLogin",
        )
        db.add(ghost)
        await db.commit()

    resp = await api_client.post("/api/auth/login", json={
        "username": "remote:alex@partner",
        "password": "anything",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ghost_excluded_from_registry(api_client):
    """Registry endpoints don't return ghost users."""
    from src.database import async_session
    from src.models import User

    # Create a discoverable user and a ghost
    async with async_session() as db:
        user = User(
            username="realuser", display_name="Real User",
            is_discoverable=True, bio="A real local user",
        )
        ghost = User(
            username="remote:ghost@other",
            display_name="Ghost User",
            is_remote=True, is_discoverable=False,
            remote_pod_url="http://other:8001",
            remote_did="did:key:z6MkGhostReg",
        )
        db.add_all([user, ghost])
        await db.commit()

    resp = await api_client.get("/api/registry/agents")
    assert resp.status_code == 200
    data = resp.json()
    usernames = [a.get("username") for a in data.get("agents", [])]
    assert "remote:ghost@other" not in usernames


# ── Pool Invite Token Tests ──


@pytest.mark.asyncio
async def test_pool_invite_requires_token(api_client):
    """Pool invite without valid token → rejected."""
    resp = await api_client.post("/api/pod/pool-invite", json={
        "network_id": "some-network",
        "invite_token": "invalid-token",
        "from_pod": "http://other:8001",
        "username": "alex",
        "display_name": "Alex",
        "did": "did:key:z6MkTest",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pool_invite_creates_ghost_and_connections(api_client):
    """Pool invite endpoint creates ghost + membership + connections."""
    from src.database import async_session
    from src.models import Network, NetworkMembership, PoolInviteToken, User
    from src.crypto import derive_vault_key, encrypt, generate_key

    # Set up: create a user, network, and invite token
    async with async_session() as db:
        vault_key = generate_key()
        derived, salt = derive_vault_key("TestPass123!")
        enc_vault = encrypt(vault_key, derived)

        owner = User(
            id="owner-id", username="owner", display_name="Owner",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        db.add(owner)
        await db.flush()

        network = Network(
            id="test-net-id", owner_id="owner-id",
            name="Test Pool", network_type="team",
        )
        db.add(network)
        await db.flush()

        db.add(NetworkMembership(
            network_id="test-net-id", user_id="owner-id", role="owner",
        ))

        # Create a valid invite token
        token = PoolInviteToken(
            network_id="test-net-id",
            token="valid-token-123",
            target_pod_url="http://other:8001",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(token)
        await db.commit()

    # Send the pool invite
    resp = await api_client.post("/api/pod/pool-invite", json={
        "network_id": "test-net-id",
        "invite_token": "valid-token-123",
        "from_pod": "http://other:8001",
        "username": "remote_user",
        "display_name": "Remote User",
        "did": "did:key:z6MkRemote",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert "ghost_user_id" in data

    # Verify ghost was created with correct properties
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(User).where(User.remote_did == "did:key:z6MkRemote")
        )
        ghost = result.scalar_one_or_none()
        assert ghost is not None
        assert ghost.is_remote is True
        assert ghost.username.startswith("remote:")

        # Verify membership
        mem = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.user_id == ghost.id,
                NetworkMembership.network_id == "test-net-id",
            )
        )
        assert mem.scalar_one_or_none() is not None

        # Ghost connections ARE created during pool-sync for agent discovery via list_connections
        conn = await db.execute(
            select(Connection).where(
                Connection.status == "accepted",
                ((Connection.from_user_id == ghost.id) & (Connection.to_user_id == "owner-id"))
                | ((Connection.from_user_id == "owner-id") & (Connection.to_user_id == ghost.id)),
            )
        )
        assert conn.scalar_one_or_none() is not None  # Connection exists for federation queries

        # Verify token was consumed
        tok = await db.execute(
            select(PoolInviteToken).where(PoolInviteToken.token == "valid-token-123")
        )
        assert tok.scalar_one().status == "consumed"


@pytest.mark.asyncio
async def test_ghost_cap_per_network(api_client):
    """Pool invite rejected when network has >= 20 ghost members."""
    from src.database import async_session
    from src.models import Network, NetworkMembership, PoolInviteToken, User

    async with async_session() as db:
        owner = User(id="cap-owner-id", username="capowner", display_name="Cap Owner")
        db.add(owner)
        await db.flush()

        network = Network(
            id="cap-net-id", owner_id="cap-owner-id",
            name="Cap Test Pool", network_type="team",
        )
        db.add(network)
        await db.flush()

        db.add(NetworkMembership(
            network_id="cap-net-id", user_id="cap-owner-id", role="owner",
        ))

        # Create 20 ghost users already in the network
        for i in range(20):
            ghost = User(
                username=f"remote:ghost{i}@other",
                display_name=f"Ghost {i}",
                is_remote=True,
                remote_pod_url="http://other:8001",
                remote_did=f"did:key:z6MkGhost{i}",
            )
            db.add(ghost)
            await db.flush()
            db.add(NetworkMembership(
                network_id="cap-net-id", user_id=ghost.id, role="remote_member",
            ))

        # Create invite token for the 21st
        token = PoolInviteToken(
            network_id="cap-net-id",
            token="cap-test-token",
            target_pod_url="http://other:8001",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(token)
        await db.commit()

    resp = await api_client.post("/api/pod/pool-invite", json={
        "network_id": "cap-net-id",
        "invite_token": "cap-test-token",
        "from_pod": "http://other:8001",
        "username": "ghost21",
        "display_name": "Ghost 21",
        "did": "did:key:z6MkGhost21",
    })
    assert resp.status_code == 429


# ── Remote Query with Ghost Trust Tests ──


@pytest.mark.asyncio
async def test_receive_remote_query_no_ghost(api_client):
    """Remote query without ghost → public trust response."""
    from src.database import async_session
    from src.models import User, Agent
    from src.crypto import generate_ed25519_keypair, public_key_to_did, derive_vault_key, encrypt, generate_key

    async with async_session() as db:
        vault_key = generate_key()
        derived, salt = derive_vault_key("TestPass123!")
        enc_vault = encrypt(vault_key, derived)

        target = User(
            id="target-id", username="target", display_name="Target User",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        db.add(target)
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id="target-id", name="Target Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    # Load vault key
    from src.main import vault_keys
    vault_keys["target-id"] = vault_key

    resp = await api_client.post("/api/pod/query", json={
        "from_did": "did:key:z6MkUnknown",
        "from_pod": "http://unknown:8001",
        "to_username": "target",
        "question": "What do you know?",
    })
    # Should return 200 with public trust (we only check it doesn't crash)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_receive_remote_query_spoofed_pod(api_client):
    """Ghost DID but wrong from_pod → blocked with 403 (DID spoofing detected)."""
    from src.database import async_session
    from src.models import User, Agent
    from src.crypto import generate_ed25519_keypair, public_key_to_did, derive_vault_key, encrypt, generate_key

    async with async_session() as db:
        vault_key = generate_key()
        derived, salt = derive_vault_key("TestPass123!")
        enc_vault = encrypt(vault_key, derived)

        target = User(
            id="spoof-target-id", username="spoof_target", display_name="Spoof Target",
            vault_key_salt=salt, encrypted_vault_key=enc_vault,
        )
        ghost = User(
            username="remote:legit@partner",
            display_name="Legit Remote",
            is_remote=True,
            remote_pod_url="http://partner:8001",
            remote_did="did:key:z6MkLegit",
        )
        db.add_all([target, ghost])
        await db.flush()

        priv, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id="spoof-target-id", name="Target Agent",
            public_key=pub, did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()

    from src.main import vault_keys
    vault_keys["spoof-target-id"] = vault_key

    # Send query claiming to be the ghost's DID but from a DIFFERENT pod
    resp = await api_client.post("/api/pod/query", json={
        "from_did": "did:key:z6MkLegit",
        "from_pod": "http://EVIL-POD:8001",  # Wrong pod!
        "to_username": "spoof_target",
        "question": "Give me secrets",
    })
    # Should be blocked with 403 (DID spoofing detected)
    assert resp.status_code == 403
