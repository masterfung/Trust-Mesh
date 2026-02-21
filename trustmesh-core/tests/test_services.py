"""Tests for service agent routes — discovery and creation."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db, async_session
from src.models import Agent, User


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    sessions.clear()
    _login_attempts.clear()
    await drop_db()
    await init_db()
    yield
    await drop_db()


@pytest_asyncio.fixture
async def client():
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_user(username="testorg", display_name="Test Org"):
    """Create an organization user directly in DB."""
    from src.crypto import generate_ed25519_keypair, public_key_to_did
    async with async_session() as db:
        user = User(
            username=username,
            display_name=display_name,
            bio="A test organization",
            user_type="organization",
            is_discoverable=True,
        )
        db.add(user)
        await db.flush()

        _, pub = generate_ed25519_keypair()
        agent = Agent(
            owner_id=user.id,
            name=f"{display_name} Agent",
            personality="Helpful org agent",
            public_key=pub,
            did=public_key_to_did(pub),
        )
        db.add(agent)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_list_services_empty(client):
    """List services returns empty when none exist."""
    resp = await client.get("/api/services")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_services_returns_orgs(client):
    """List services includes organization users with agent cards."""
    await _create_org_user()
    resp = await client.get("/api/services")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    svc = data[0]
    assert svc["user_type"] in ("organization", "service")
    assert "agent_card" in svc


@pytest.mark.asyncio
@patch("src.routes.services.upsert_capsule_embedding")
@patch("src.routes.services.extract_profile", new_callable=AsyncMock)
async def test_create_service(mock_extract, mock_fts, client):
    """POST creates a new service with vault + agent."""
    mock_extract.return_value = {"skills": [{"name": "Testing", "category": "qa"}]}
    resp = await client.post("/api/services", json={
        "username": "newservice",
        "display_name": "New Service",
        "bio": "A brand new service",
        "password": "SecureTestPass1!",
        "agent_personality": "Efficient and helpful",
        "capsules": [
            {"type": "skill", "title": "Core Skill", "content": "We do testing"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "newservice"
    assert data["user_type"] == "organization"
    assert data["agent_card"] is not None


@pytest.mark.asyncio
@patch("src.routes.services.upsert_capsule_embedding")
@patch("src.routes.services.extract_profile", new_callable=AsyncMock)
async def test_create_service_duplicate_username(mock_extract, mock_fts, client):
    """Duplicate username → 400."""
    mock_extract.return_value = {}
    resp1 = await client.post("/api/services", json={
        "username": "dupeservice",
        "display_name": "Dupe Service One",
        "bio": "First",
        "password": "SecureTestPass1!",
        "capsules": [],
    })
    assert resp1.status_code == 200

    resp2 = await client.post("/api/services", json={
        "username": "dupeservice",
        "display_name": "Dupe Service Two",
        "bio": "Second",
        "password": "SecureTestPass1!",
        "capsules": [],
    })
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_list_services_excludes_person_users(client):
    """Person-type users should not appear in service list."""
    async with async_session() as db:
        user = User(
            username="personuser",
            display_name="Person User",
            bio="Just a person",
            user_type="person",
            is_discoverable=True,
        )
        db.add(user)
        await db.commit()

    resp = await client.get("/api/services")
    assert resp.status_code == 200
    for svc in resp.json():
        assert svc["user_type"] != "person"


@pytest.mark.asyncio
async def test_service_agent_card_structure(client):
    """Agent card has expected fields."""
    await _create_org_user()
    resp = await client.get("/api/services")
    data = resp.json()
    assert len(data) >= 1
    card = data[0]["agent_card"]
    assert card is not None
    assert "name" in card
    assert "url" in card
    assert "capabilities" in card
    assert "knowledge-query" in card["capabilities"]


@pytest.mark.asyncio
@patch("src.routes.services.upsert_capsule_embedding")
@patch("src.routes.services.extract_profile", new_callable=AsyncMock)
async def test_create_service_with_capsules(mock_extract, mock_fts, client):
    """Service creation stores provided capsules."""
    mock_extract.return_value = {}
    resp = await client.post("/api/services", json={
        "username": "capsvc",
        "display_name": "Capsule Service",
        "bio": "Service with capsules",
        "password": "SecureTestPass1!",
        "capsules": [
            {"type": "procedure", "title": "Setup", "content": "Step 1, Step 2"},
            {"type": "skill", "title": "Expertise", "content": "We know things"},
        ],
    })
    assert resp.status_code == 200
