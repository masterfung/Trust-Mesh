"""Tests for trust resolution between users."""

import pytest
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models import Base, Connection, Network, NetworkMembership, User
from src.trust import get_accepted_connection, get_shared_networks, resolve_trust_level


@pytest.fixture
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


@pytest.fixture
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
