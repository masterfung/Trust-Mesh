"""Tests for trust resolution between users and capsule visibility enforcement."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models import Base, CapsuleNetworkAccess, Connection, KnowledgeCapsule, Network, NetworkMembership, User
from src.trust import get_accepted_connection, get_shared_networks, resolve_trust_level
from src.gossip import get_accessible_capsule_ids


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
    """Create test users, connections, and networks."""
    # Users
    peter = User(id="peter-id", username="peter", display_name="Peter Johnson")
    molly = User(id="molly-id", username="molly", display_name="Molly Johnson")
    jane = User(id="jane-id", username="jane", display_name="Jane Johnson")
    kyle = User(id="kyle-id", username="kyle", display_name="Kyle Rivera")

    db.add_all([peter, molly, jane, kyle])
    await db.flush()

    # Connections
    db.add(Connection(from_user_id="peter-id", to_user_id="molly-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    db.add(Connection(from_user_id="peter-id", to_user_id="jane-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    db.add(Connection(from_user_id="molly-id", to_user_id="kyle-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    db.add(Connection(from_user_id="jane-id", to_user_id="molly-id", status="accepted",
                      accepted_at=datetime.now(timezone.utc)))
    # Kyle NOT connected to Peter or Jane

    # Networks
    family = Network(id="family-id", owner_id="peter-id", name="The Johnsons", network_type="family")
    work = Network(id="work-id", owner_id="molly-id", name="TechCorp PM Team", network_type="team")
    db.add_all([family, work])
    await db.flush()

    # Network memberships
    db.add(NetworkMembership(network_id="family-id", user_id="peter-id", role="owner"))
    db.add(NetworkMembership(network_id="family-id", user_id="molly-id", role="member"))
    db.add(NetworkMembership(network_id="family-id", user_id="jane-id", role="member"))
    db.add(NetworkMembership(network_id="work-id", user_id="molly-id", role="owner"))
    db.add(NetworkMembership(network_id="work-id", user_id="kyle-id", role="member"))

    await db.commit()
    return db


@pytest.mark.asyncio
async def test_accepted_connection_exists(seeded_db):
    conn = await get_accepted_connection(seeded_db, "peter-id", "molly-id")
    assert conn is not None
    assert conn.status == "accepted"


@pytest.mark.asyncio
async def test_accepted_connection_bidirectional(seeded_db):
    """Connection lookup works regardless of direction."""
    conn = await get_accepted_connection(seeded_db, "molly-id", "peter-id")
    assert conn is not None


@pytest.mark.asyncio
async def test_no_connection_between_kyle_and_peter(seeded_db):
    conn = await get_accepted_connection(seeded_db, "kyle-id", "peter-id")
    assert conn is None


@pytest.mark.asyncio
async def test_no_connection_between_kyle_and_jane(seeded_db):
    conn = await get_accepted_connection(seeded_db, "kyle-id", "jane-id")
    assert conn is None


@pytest.mark.asyncio
async def test_shared_networks_family(seeded_db):
    """Peter and Molly share The Johnsons network."""
    networks = await get_shared_networks(seeded_db, "peter-id", "molly-id")
    assert len(networks) == 1
    assert networks[0].name == "The Johnsons"


@pytest.mark.asyncio
async def test_shared_networks_work(seeded_db):
    """Molly and Kyle share TechCorp PM Team."""
    networks = await get_shared_networks(seeded_db, "molly-id", "kyle-id")
    assert len(networks) == 1
    assert networks[0].name == "TechCorp PM Team"


@pytest.mark.asyncio
async def test_no_shared_networks(seeded_db):
    """Kyle and Peter have no shared networks."""
    networks = await get_shared_networks(seeded_db, "kyle-id", "peter-id")
    assert len(networks) == 0


@pytest.mark.asyncio
async def test_trust_level_same_user(seeded_db):
    """Same user = private access."""
    level, networks = await resolve_trust_level(seeded_db, "peter-id", "peter-id")
    assert level == "private"
    assert networks == []


@pytest.mark.asyncio
async def test_trust_level_family_network(seeded_db):
    """Peter -> Molly: connected + shared family network = network level."""
    level, networks = await resolve_trust_level(seeded_db, "peter-id", "molly-id")
    assert level == "network"
    assert len(networks) == 1
    assert networks[0].name == "The Johnsons"


@pytest.mark.asyncio
async def test_trust_level_work_network(seeded_db):
    """Kyle -> Molly: connected + shared work network = network level."""
    level, networks = await resolve_trust_level(seeded_db, "kyle-id", "molly-id")
    assert level == "network"
    assert len(networks) == 1
    assert networks[0].name == "TechCorp PM Team"


@pytest.mark.asyncio
async def test_trust_level_no_connection(seeded_db):
    """Kyle -> Peter: no connection = public level."""
    level, networks = await resolve_trust_level(seeded_db, "kyle-id", "peter-id")
    assert level == "public"
    assert networks == []


@pytest.mark.asyncio
async def test_trust_level_no_connection_kyle_jane(seeded_db):
    """Kyle -> Jane: no connection = public level."""
    level, networks = await resolve_trust_level(seeded_db, "kyle-id", "jane-id")
    assert level == "public"
    assert networks == []


# ── Capsule Visibility Enforcement Tests ──

@pytest_asyncio.fixture
async def capsule_db(seeded_db: AsyncSession):
    """Add capsules with various visibility levels to the seeded DB."""
    db = seeded_db

    # Peter's capsules with different visibility levels
    capsules = [
        KnowledgeCapsule(
            id="cap-private", owner_id="peter-id", capsule_type="note",
            title="Private Note", content_encrypted=b"encrypted",
            visibility="private", category="personal",
        ),
        KnowledgeCapsule(
            id="cap-internal", owner_id="peter-id", capsule_type="note",
            title="Family Info", content_encrypted=b"encrypted",
            visibility="internal", category="family",
        ),
        KnowledgeCapsule(
            id="cap-shareable", owner_id="peter-id", capsule_type="note",
            title="Shareable Doc", content_encrypted=b"encrypted",
            visibility="shareable", category="work",
        ),
        KnowledgeCapsule(
            id="cap-open", owner_id="peter-id", capsule_type="note",
            title="Public Bio", content_encrypted=b"encrypted",
            visibility="open", category="personal",
        ),
    ]
    db.add_all(capsules)
    await db.flush()

    # Link internal capsule to family network
    db.add(CapsuleNetworkAccess(capsule_id="cap-internal", network_id="family-id"))
    await db.commit()

    return db


@pytest.mark.asyncio
async def test_public_trust_only_sees_open_capsules(capsule_db):
    """Public trust level should ONLY return open capsules. This is the security core."""
    ids = await get_accessible_capsule_ids(
        capsule_db, "peter-id", "public", shared_networks=[]
    )
    assert "cap-open" in ids
    assert "cap-private" not in ids
    assert "cap-internal" not in ids
    assert "cap-shareable" not in ids
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_network_trust_sees_open_and_internal(capsule_db):
    """Network trust should see open + internal capsules shared to the network."""
    from src.models import Network
    family = await capsule_db.get(Network, "family-id")

    ids = await get_accessible_capsule_ids(
        capsule_db, "peter-id", "network", shared_networks=[family],
        requester_id="molly-id",
    )
    assert "cap-open" in ids
    assert "cap-internal" in ids
    assert "cap-private" not in ids
    # shareable is only accessible via explicit grants, which we haven't created
    assert len([i for i in ids if i.startswith("cap-")]) >= 2


@pytest.mark.asyncio
async def test_private_trust_sees_all_capsules(capsule_db):
    """Private trust (self-query) should see ALL capsules."""
    ids = await get_accessible_capsule_ids(
        capsule_db, "peter-id", "private", shared_networks=[]
    )
    assert "cap-private" in ids
    assert "cap-internal" in ids
    assert "cap-shareable" in ids
    assert "cap-open" in ids
    assert len(ids) == 4


@pytest.mark.asyncio
async def test_network_trust_without_shared_networks_sees_only_open(capsule_db):
    """Network trust with empty shared_networks behaves like public."""
    ids = await get_accessible_capsule_ids(
        capsule_db, "peter-id", "network", shared_networks=[]
    )
    assert "cap-open" in ids
    assert "cap-internal" not in ids
    assert "cap-private" not in ids


@pytest.mark.asyncio
async def test_archived_capsules_excluded(capsule_db):
    """Archived capsules should never appear regardless of trust level."""
    # Archive the open capsule
    cap = await capsule_db.get(KnowledgeCapsule, "cap-open")
    cap.is_archived = True
    await capsule_db.commit()

    ids = await get_accessible_capsule_ids(
        capsule_db, "peter-id", "private", shared_networks=[]
    )
    assert "cap-open" not in ids
    assert "cap-private" in ids


# ── Pool Membership Trust Tests (Phase 2) ──

@pytest_asyncio.fixture
async def pool_only_db(db: AsyncSession):
    """Create users with pool membership but NO direct connection."""
    alice = User(id="alice-id", username="alice", display_name="Alice")
    bob = User(id="bob-id", username="bob", display_name="Bob")
    carol = User(id="carol-id", username="carol", display_name="Carol")
    dave = User(id="dave-id", username="dave", display_name="Dave")
    db.add_all([alice, bob, carol, dave])
    await db.flush()

    # Pool that alice and bob share (NO connection between them)
    pool = Network(id="pool-id", owner_id="alice-id", name="Shared Pool", network_type="custom")
    db.add(pool)
    await db.flush()

    db.add(NetworkMembership(network_id="pool-id", user_id="alice-id", role="owner"))
    db.add(NetworkMembership(network_id="pool-id", user_id="bob-id", role="member"))
    # carol and dave are NOT in any pool and NOT connected to anyone
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_pool_membership_alone_grants_network_trust(pool_only_db):
    """Users sharing a pool get 'network' trust even without a direct connection."""
    level, networks = await resolve_trust_level(pool_only_db, "alice-id", "bob-id")
    assert level == "network"
    assert len(networks) == 1
    assert networks[0].name == "Shared Pool"


@pytest.mark.asyncio
async def test_pool_membership_bidirectional(pool_only_db):
    """Pool trust works both ways."""
    level, networks = await resolve_trust_level(pool_only_db, "bob-id", "alice-id")
    assert level == "network"
    assert len(networks) == 1


@pytest.mark.asyncio
async def test_no_pool_no_connection_is_public(pool_only_db):
    """No shared pool and no connection = public trust."""
    level, networks = await resolve_trust_level(pool_only_db, "carol-id", "dave-id")
    assert level == "public"
    assert networks == []


# ── Category-Scoped Pool Tests (Phase 2) ──

@pytest_asyncio.fixture
async def category_scoped_db(db: AsyncSession):
    """Create users with category_scoped and standard pools, and capsules across categories."""
    alice = User(id="alice-id", username="alice", display_name="Alice")
    bob = User(id="bob-id", username="bob", display_name="Bob")
    carol = User(id="carol-id", username="carol", display_name="Carol")
    db.add_all([alice, bob, carol])
    await db.flush()

    # Category-scoped pool: only "health" capsules visible
    health_pool = Network(
        id="health-pool-id", owner_id="alice-id", name="Health Pool",
        network_type="custom", pool_type="category_scoped",
        shared_categories='["health"]',
    )
    # Standard pool: no category restriction
    standard_pool = Network(
        id="standard-pool-id", owner_id="alice-id", name="Standard Pool",
        network_type="custom", pool_type="standard",
    )
    db.add_all([health_pool, standard_pool])
    await db.flush()

    # Alice and Bob in health_pool only
    db.add(NetworkMembership(network_id="health-pool-id", user_id="alice-id", role="owner"))
    db.add(NetworkMembership(network_id="health-pool-id", user_id="bob-id", role="member"))

    # Alice and Carol in standard_pool only
    db.add(NetworkMembership(network_id="standard-pool-id", user_id="alice-id", role="owner"))
    db.add(NetworkMembership(network_id="standard-pool-id", user_id="carol-id", role="member"))

    # Alice's capsules: health, work, and family categories
    capsules = [
        KnowledgeCapsule(
            id="cap-health", owner_id="alice-id", capsule_type="note",
            title="Health Info", content_encrypted=b"enc",
            visibility="internal", category="health",
        ),
        KnowledgeCapsule(
            id="cap-work", owner_id="alice-id", capsule_type="note",
            title="Work Info", content_encrypted=b"enc",
            visibility="internal", category="work",
        ),
        KnowledgeCapsule(
            id="cap-family", owner_id="alice-id", capsule_type="note",
            title="Family Info", content_encrypted=b"enc",
            visibility="internal", category="family",
        ),
        KnowledgeCapsule(
            id="cap-open2", owner_id="alice-id", capsule_type="note",
            title="Open Info", content_encrypted=b"enc",
            visibility="open", category="general",
        ),
    ]
    db.add_all(capsules)
    await db.flush()

    # Share all internal capsules to both pools
    for cap_id in ["cap-health", "cap-work", "cap-family"]:
        db.add(CapsuleNetworkAccess(capsule_id=cap_id, network_id="health-pool-id"))
        db.add(CapsuleNetworkAccess(capsule_id=cap_id, network_id="standard-pool-id"))

    await db.commit()
    return db


@pytest.mark.asyncio
async def test_category_scoped_pool_filters_capsules(category_scoped_db):
    """Category-scoped pool only shows capsules matching its shared_categories."""
    db = category_scoped_db
    health_pool = await db.get(Network, "health-pool-id")

    ids = await get_accessible_capsule_ids(
        db, "alice-id", "network", shared_networks=[health_pool],
        requester_id="bob-id",
    )
    assert "cap-health" in ids
    assert "cap-work" not in ids
    assert "cap-family" not in ids
    assert "cap-open2" in ids  # open capsules always visible


@pytest.mark.asyncio
async def test_standard_pool_no_category_filter(category_scoped_db):
    """Standard pool shows all internal capsules regardless of category."""
    db = category_scoped_db
    standard_pool = await db.get(Network, "standard-pool-id")

    ids = await get_accessible_capsule_ids(
        db, "alice-id", "network", shared_networks=[standard_pool],
        requester_id="carol-id",
    )
    assert "cap-health" in ids
    assert "cap-work" in ids
    assert "cap-family" in ids
    assert "cap-open2" in ids


@pytest.mark.asyncio
async def test_mixed_pools_standard_lifts_restriction(category_scoped_db):
    """If any shared pool is standard, category restriction is lifted."""
    db = category_scoped_db
    health_pool = await db.get(Network, "health-pool-id")
    standard_pool = await db.get(Network, "standard-pool-id")

    ids = await get_accessible_capsule_ids(
        db, "alice-id", "network", shared_networks=[health_pool, standard_pool],
    )
    assert "cap-health" in ids
    assert "cap-work" in ids
    assert "cap-family" in ids
