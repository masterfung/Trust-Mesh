"""Tests for federation module — ping, connect, discover, remote query."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.database import init_db, drop_db, async_session
from src.federation import (
    POD_NAME,
    POD_URL,
    FEDERATION_TIMEOUT,
    get_pod_info,
    ping_peer,
    connect_to_peer,
    discover_remote_agents,
    remote_query,
    remote_emergency_access,
)
from src.models import PeerPod


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB for each test."""
    await drop_db()
    await init_db()
    yield
    await drop_db()


# ── Pod Info ──


@pytest.mark.asyncio
async def test_get_pod_info():
    """get_pod_info should return pod name, URL, protocol, and agents list."""
    info = await get_pod_info()
    assert info["pod_name"] == POD_NAME
    assert info["pod_url"] == POD_URL
    assert info["protocol"] == "trustmesh/0.1"
    assert isinstance(info["agents"], list)
    assert info["agent_count"] == len(info["agents"])


# ── Ping ──


@pytest.mark.asyncio
async def test_ping_peer_unreachable():
    """ping_peer should return None for unreachable URLs."""
    result = await ping_peer("http://localhost:59999")
    assert result is None


@pytest.mark.asyncio
async def test_ping_peer_success():
    """ping_peer should return pod info for reachable pods."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "pod_name": "Test Pod",
        "pod_url": "http://localhost:8001",
        "protocol": "trustmesh/0.1",
        "agent_count": 2,
        "agents": [],
    }

    with patch("src.federation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await ping_peer("http://localhost:8001")
        assert result is not None
        assert result["pod_name"] == "Test Pod"


# ── Connect to Peer ──


@pytest.mark.asyncio
async def test_connect_to_unreachable_peer():
    """connect_to_peer should return None for unreachable peers."""
    async with async_session() as db:
        result = await connect_to_peer(db, "http://localhost:59999")
        assert result is None


@pytest.mark.asyncio
async def test_connect_creates_peer_record():
    """connect_to_peer should create PeerPod record on success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "pod_name": "Remote Pod",
        "agent_count": 3,
    }

    with patch("src.federation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        async with async_session() as db:
            pod = await connect_to_peer(db, "http://localhost:8001")
            assert pod is not None
            assert pod.name == "Remote Pod"
            assert pod.url == "http://localhost:8001"
            assert pod.status == "active"
            assert pod.agent_count == 3


@pytest.mark.asyncio
async def test_connect_updates_existing_peer():
    """connect_to_peer should update existing PeerPod record."""
    # First, create a peer record manually
    async with async_session() as db:
        peer = PeerPod(name="Old Name", url="http://localhost:8001", status="unreachable", agent_count=0)
        db.add(peer)
        await db.commit()
        peer_id = peer.id

    # Now connect (mocked)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "pod_name": "Updated Name",
        "agent_count": 5,
    }

    with patch("src.federation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        async with async_session() as db:
            pod = await connect_to_peer(db, "http://localhost:8001")
            assert pod is not None
            assert pod.id == peer_id  # Same record, not a new one
            assert pod.name == "Updated Name"
            assert pod.status == "active"
            assert pod.agent_count == 5


# ── Discover Remote Agents ──


@pytest.mark.asyncio
async def test_discover_no_peers():
    """discover_remote_agents should return empty list with no peers."""
    async with async_session() as db:
        agents = await discover_remote_agents(db)
        assert agents == []


@pytest.mark.asyncio
async def test_discover_with_unreachable_peer():
    """discover_remote_agents should mark unreachable peers."""
    # Create a peer pointing to nowhere
    async with async_session() as db:
        peer = PeerPod(name="Ghost Pod", url="http://localhost:59999", status="active", agent_count=1)
        db.add(peer)
        await db.commit()

    async with async_session() as db:
        agents = await discover_remote_agents(db)
        assert agents == []  # No agents found

    # Peer should now be unreachable
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(PeerPod))
        peer = result.scalar_one()
        assert peer.status == "unreachable"


# ── Remote Query ──


@pytest.mark.asyncio
async def test_remote_query_unreachable():
    """remote_query should return None for unreachable pods."""
    result = await remote_query("http://localhost:59999", "did:key:test", "user", "question?")
    assert result is None


@pytest.mark.asyncio
async def test_remote_query_success():
    """remote_query should return response data on success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "trust_level": "public",
        "response": "Hello from remote pod",
        "decision": "allowed",
    }

    with patch("src.federation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await remote_query("http://localhost:8001", "did:key:test", "dr_lee", "What services?")
        assert result is not None
        assert result["trust_level"] == "public"
        assert result["response"] == "Hello from remote pod"


# ── Remote Emergency Access ──


@pytest.mark.asyncio
async def test_remote_emergency_unreachable():
    """remote_emergency_access should return None for unreachable pods."""
    result = await remote_emergency_access("http://localhost:59999", "token", "patient")
    assert result is None


# ── Federation Constants ──


def test_federation_constants():
    """Federation constants should have sane values."""
    assert FEDERATION_TIMEOUT > 0
    assert POD_NAME
    assert POD_URL.startswith("http")
