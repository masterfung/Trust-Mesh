"""Tests for relationship types, connected trust level, capsule sharing info, and label perspectives."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pydantic import ValidationError

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models import (
    Base, CapsuleNetworkAccess, Connection,
    KnowledgeCapsule, Network, NetworkMembership, User,
)
from src.trust import resolve_trust_level
from src.gossip import get_accessible_capsule_ids
from src.schemas import ConnectionRequestCreate, ConnectionLabelUpdate, VALID_RELATIONSHIP_TYPES


# ── Fixtures ──

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
    """Users with connections (some with shared pools, some without)."""
    alice = User(id="alice-id", username="alice", display_name="Alice")
    bob = User(id="bob-id", username="bob", display_name="Bob")
    carol = User(id="carol-id", username="carol", display_name="Carol")
    dave = User(id="dave-id", username="dave", display_name="Dave")
    db.add_all([alice, bob, carol, dave])
    await db.flush()

    # Alice <-> Bob: connected WITH shared pool
    db.add(Connection(
        from_user_id="alice-id", to_user_id="bob-id", status="accepted",
        relationship_type="work", from_label="colleague", to_label="colleague",
        accepted_at=datetime.now(timezone.utc),
    ))
    # Alice <-> Carol: connected but NO shared pool
    db.add(Connection(
        from_user_id="alice-id", to_user_id="carol-id", status="accepted",
        relationship_type="friend", from_label="close friend", to_label="best friend",
        accepted_at=datetime.now(timezone.utc),
    ))
    # Dave: no connections to anyone

    pool = Network(id="pool-id", owner_id="alice-id", name="Work Pool", network_type="team")
    db.add(pool)
    await db.flush()

    db.add(NetworkMembership(network_id="pool-id", user_id="alice-id", role="owner"))
    db.add(NetworkMembership(network_id="pool-id", user_id="bob-id", role="member"))
    # Carol NOT in pool

    await db.commit()
    return db


# ── Trust Level Tests ──

@pytest.mark.asyncio
async def test_connected_trust_level(seeded_db):
    """Connected-no-pool returns 'connected' instead of 'public'."""
    level, networks = await resolve_trust_level(seeded_db, "alice-id", "carol-id")
    assert level == "connected"
    assert networks == []


@pytest.mark.asyncio
async def test_stranger_still_public(seeded_db):
    """No connection, no pool returns 'public'."""
    level, networks = await resolve_trust_level(seeded_db, "dave-id", "alice-id")
    assert level == "public"
    assert networks == []


@pytest.mark.asyncio
async def test_connected_with_pool_is_network(seeded_db):
    """Connected + shared pool returns 'network'."""
    level, networks = await resolve_trust_level(seeded_db, "alice-id", "bob-id")
    assert level == "network"
    assert len(networks) == 1


@pytest.mark.asyncio
async def test_connected_bidirectional(seeded_db):
    """Connected trust works both ways."""
    level, _ = await resolve_trust_level(seeded_db, "carol-id", "alice-id")
    assert level == "connected"


# ── Capsule Access at Connected Level ──

@pytest_asyncio.fixture
async def capsule_db(seeded_db: AsyncSession):
    """Add capsules to test connected access."""
    db = seeded_db
    capsules = [
        KnowledgeCapsule(
            id="cap-open", owner_id="alice-id", capsule_type="note",
            title="Open", content_encrypted=b"enc",
            visibility="open", category="general",
        ),
        KnowledgeCapsule(
            id="cap-internal", owner_id="alice-id", capsule_type="note",
            title="Internal", content_encrypted=b"enc",
            visibility="internal", category="work",
        ),
        KnowledgeCapsule(
            id="cap-private", owner_id="alice-id", capsule_type="note",
            title="Private", content_encrypted=b"enc",
            visibility="private", category="personal",
        ),
    ]
    db.add_all(capsules)
    await db.flush()
    db.add(CapsuleNetworkAccess(capsule_id="cap-internal", network_id="pool-id"))
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_connected_capsule_access_same_as_public(capsule_db):
    """Connected trust level sees open capsules only (same as public)."""
    ids = await get_accessible_capsule_ids(
        capsule_db, "alice-id", "connected", shared_networks=[]
    )
    assert "cap-open" in ids
    assert "cap-internal" not in ids
    assert "cap-private" not in ids


# ── Connection Relationship Fields ──

@pytest.mark.asyncio
async def test_connection_with_relationship_type(seeded_db):
    """Verify connection has relationship_type and labels."""
    from sqlalchemy import select
    result = await seeded_db.execute(
        select(Connection).where(
            Connection.from_user_id == "alice-id",
            Connection.to_user_id == "carol-id",
        )
    )
    conn = result.scalar_one()
    assert conn.relationship_type == "friend"
    assert conn.from_label == "close friend"
    assert conn.to_label == "best friend"


@pytest.mark.asyncio
async def test_my_label_perspective_from_user(seeded_db):
    """from_user sees their from_label as my_label."""
    from sqlalchemy import select
    result = await seeded_db.execute(
        select(Connection).where(
            Connection.from_user_id == "alice-id",
            Connection.to_user_id == "carol-id",
        )
    )
    conn = result.scalar_one()
    # Alice is from_user, so her label is from_label
    is_from = conn.from_user_id == "alice-id"
    my_label = conn.from_label if is_from else conn.to_label
    peer_label = conn.to_label if is_from else conn.from_label
    assert my_label == "close friend"
    assert peer_label == "best friend"


@pytest.mark.asyncio
async def test_my_label_perspective_to_user(seeded_db):
    """to_user sees their to_label as my_label."""
    from sqlalchemy import select
    result = await seeded_db.execute(
        select(Connection).where(
            Connection.from_user_id == "alice-id",
            Connection.to_user_id == "carol-id",
        )
    )
    conn = result.scalar_one()
    # Carol is to_user, so her label is to_label
    is_from = conn.from_user_id == "carol-id"
    my_label = conn.from_label if is_from else conn.to_label
    peer_label = conn.to_label if is_from else conn.from_label
    assert my_label == "best friend"
    assert peer_label == "close friend"


@pytest.mark.asyncio
async def test_update_connection_label(seeded_db):
    """PATCH label updates the correct side."""
    from sqlalchemy import select
    result = await seeded_db.execute(
        select(Connection).where(
            Connection.from_user_id == "alice-id",
            Connection.to_user_id == "carol-id",
        )
    )
    conn = result.scalar_one()

    # Simulate Alice updating her label
    is_from = conn.from_user_id == "alice-id"
    new_label = "bestie"
    if is_from:
        conn.from_label = new_label
    else:
        conn.to_label = new_label
    await seeded_db.commit()

    await seeded_db.refresh(conn)
    assert conn.from_label == "bestie"
    assert conn.to_label == "best friend"  # Carol's label unchanged


# ── Schema Validation ──

class TestRelationshipTypeValidation:
    """Validate relationship_type constraints on schemas."""

    def test_valid_relationship_types(self):
        """All valid types should be accepted."""
        for rtype in VALID_RELATIONSHIP_TYPES:
            req = ConnectionRequestCreate(
                from_user_id="u1", to_user_id="u2", message="hi",
                relationship_type=rtype,
            )
            assert req.relationship_type == rtype

    def test_invalid_relationship_type_rejected(self):
        """Invalid type must be rejected."""
        with pytest.raises(ValidationError):
            ConnectionRequestCreate(
                from_user_id="u1", to_user_id="u2", message="hi",
                relationship_type="romantic",
            )

    def test_none_relationship_type_accepted(self):
        """None relationship_type is valid (optional)."""
        req = ConnectionRequestCreate(
            from_user_id="u1", to_user_id="u2", message="hi",
        )
        assert req.relationship_type is None

    def test_label_update_validation(self):
        """ConnectionLabelUpdate validates relationship_type."""
        update = ConnectionLabelUpdate(my_label="friend", relationship_type="work")
        assert update.relationship_type == "work"

    def test_label_update_invalid_type(self):
        """ConnectionLabelUpdate rejects invalid relationship_type."""
        with pytest.raises(ValidationError):
            ConnectionLabelUpdate(my_label="friend", relationship_type="invalid")


# ── Seed Data Verification ──

@pytest.mark.asyncio
async def test_seed_connections_have_relationships(seeded_db):
    """Verify that seeded connections have relationship fields populated."""
    from sqlalchemy import select
    result = await seeded_db.execute(select(Connection))
    conns = result.scalars().all()
    assert len(conns) == 2
    for conn in conns:
        assert conn.relationship_type is not None
        assert conn.from_label is not None
        assert conn.to_label is not None


# ── Capsule Sharing Info ──

@pytest_asyncio.fixture
async def capsule_sharing_db(db: AsyncSession):
    """Test capsule with network names."""
    owner = User(id="owner-id", username="owner", display_name="The Owner")
    db.add(owner)
    await db.flush()

    net1 = Network(id="net1-id", owner_id="owner-id", name="Family Circle", network_type="family")
    net2 = Network(id="net2-id", owner_id="owner-id", name="Work Team", network_type="team")
    db.add_all([net1, net2])
    await db.flush()

    capsule = KnowledgeCapsule(
        id="cap-shared", owner_id="owner-id", capsule_type="memory",
        title="Shared Cap", content_encrypted=b"enc",
        visibility="internal", category="general",
    )
    db.add(capsule)
    await db.flush()

    db.add(CapsuleNetworkAccess(capsule_id="cap-shared", network_id="net1-id"))
    db.add(CapsuleNetworkAccess(capsule_id="cap-shared", network_id="net2-id"))
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_capsule_network_access_records(capsule_sharing_db):
    """Capsule is linked to two networks via CapsuleNetworkAccess."""
    from sqlalchemy import select
    result = await capsule_sharing_db.execute(
        select(CapsuleNetworkAccess).where(CapsuleNetworkAccess.capsule_id == "cap-shared")
    )
    accesses = result.scalars().all()
    network_ids = {a.network_id for a in accesses}
    assert "net1-id" in network_ids
    assert "net2-id" in network_ids
    assert len(network_ids) == 2


@pytest.mark.asyncio
async def test_capsule_owner_name_retrievable(capsule_sharing_db):
    """Owner display name can be retrieved from the DB."""
    owner = await capsule_sharing_db.get(User, "owner-id")
    assert owner.display_name == "The Owner"
