"""Tests for organization signup: org_subtype, agent_mode, default pools, and services filter."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db
from src.embeddings import close_fts, init_fts
from src import transit_bridge


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    sessions.clear()
    _login_attempts.clear()
    close_fts()
    await drop_db()
    await init_db()
    init_fts()
    transit_bridge._ensure_init()
    yield
    close_fts()
    await drop_db()


@pytest_asyncio.fixture
async def client():
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


VALID_PERSON = {
    "display_name": "Alice Smith",
    "bio": "A regular person",
    "password": "SecureTestPass1!",
}

VALID_ORG = {
    "display_name": "Acme Corp",
    "bio": "A test company",
    "email": "admin@acme.com",
    "password": "SecureTestPass1!",
    "user_type": "organization",
    "org_subtype": "company",
}

VALID_HEALTHCARE_ORG = {
    "display_name": "Bay Area Medical Center",
    "bio": "Healthcare org",
    "email": "admin@baymed.com",
    "password": "SecureTestPass1!",
    "user_type": "organization",
    "org_subtype": "healthcare",
}


@pytest.mark.asyncio
async def test_person_signup_defaults(client):
    """Person signup: agent_mode=private, org_subtype=null, NOT in /api/services."""
    resp = await client.post("/api/users", json=VALID_PERSON)
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_type"] == "person"
    assert data["agent_mode"] == "private"
    assert data["org_subtype"] is None

    # Person should NOT appear in /api/services
    svc_resp = await client.get("/api/services")
    assert svc_resp.status_code == 200
    service_ids = [s["id"] for s in svc_resp.json()]
    assert data["id"] not in service_ids


@pytest.mark.asyncio
async def test_org_signup_creates_default_pools(client):
    """Org signup: agent_mode=internal, org_subtype set, default networks created."""
    resp = await client.post("/api/users", json=VALID_ORG)
    assert resp.status_code == 200
    data = resp.json()

    assert data["user_type"] == "organization"
    assert data["org_subtype"] == "company"
    assert data["agent_mode"] == "internal"

    user_id = data["id"]

    # Should have two default networks (All Staff, Leadership)
    net_resp = await client.get(f"/api/users/{user_id}/networks")
    assert net_resp.status_code == 200
    networks = net_resp.json()
    pool_types = {n["pool_type"] for n in networks}
    assert "org_all_staff" in pool_types
    assert "org_executives" in pool_types

    names = {n["name"] for n in networks}
    assert "All Staff" in names
    assert "Leadership" in names


@pytest.mark.asyncio
async def test_org_not_in_services_when_internal(client):
    """Org with agent_mode=internal should NOT appear in /api/services."""
    resp = await client.post("/api/users", json=VALID_ORG)
    assert resp.status_code == 200
    org_id = resp.json()["id"]

    svc_resp = await client.get("/api/services")
    service_ids = [s["id"] for s in svc_resp.json()]
    assert org_id not in service_ids


@pytest.mark.asyncio
async def test_go_public_toggle(client):
    """PATCH agent-mode=public: org appears in services, toggling back removes it."""
    resp = await client.post("/api/users", json=VALID_ORG)
    assert resp.status_code == 200
    org_id = resp.json()["id"]

    # Go public
    patch_resp = await client.patch(
        f"/api/users/{org_id}/agent-mode",
        json={"mode": "public"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["agent_mode"] == "public"
    assert patch_resp.json()["is_discoverable"] is True

    # Should appear in /api/services
    svc_resp = await client.get("/api/services")
    service_ids = [s["id"] for s in svc_resp.json()]
    assert org_id in service_ids

    # Go back to internal
    patch_resp2 = await client.patch(
        f"/api/users/{org_id}/agent-mode",
        json={"mode": "internal"},
    )
    assert patch_resp2.status_code == 200
    assert patch_resp2.json()["agent_mode"] == "internal"

    # Should no longer appear in /api/services
    svc_resp2 = await client.get("/api/services")
    service_ids2 = [s["id"] for s in svc_resp2.json()]
    assert org_id not in service_ids2


@pytest.mark.asyncio
async def test_person_cannot_change_agent_mode(client):
    """Persons are not allowed to use the agent-mode endpoint."""
    resp = await client.post("/api/users", json=VALID_PERSON)
    assert resp.status_code == 200
    person_id = resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/users/{person_id}/agent-mode",
        json={"mode": "public"},
    )
    assert patch_resp.status_code == 400


@pytest.mark.asyncio
async def test_healthcare_org_subtype(client):
    """Healthcare org gets org_subtype=healthcare."""
    resp = await client.post("/api/users", json=VALID_HEALTHCARE_ORG)
    assert resp.status_code == 200
    data = resp.json()
    assert data["org_subtype"] == "healthcare"
    assert data["user_type"] == "organization"


@pytest.mark.asyncio
async def test_invalid_org_subtype_rejected(client):
    """Invalid org_subtype should be rejected with 422."""
    bad_org = {**VALID_ORG, "org_subtype": "pirates"}
    resp = await client.post("/api/users", json=bad_org)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_services_filter_only_public_orgs(client):
    """GET /api/services returns only organizations with agent_mode=public."""
    # Create two orgs: one internal (default), one public
    resp1 = await client.post("/api/users", json=VALID_ORG)
    assert resp1.status_code == 200
    internal_id = resp1.json()["id"]

    public_org = {**VALID_ORG, "display_name": "Public Corp", "email": "admin2@public.com"}
    resp2 = await client.post("/api/users", json=public_org)
    assert resp2.status_code == 200
    public_id = resp2.json()["id"]
    # Make second org public
    await client.patch(f"/api/users/{public_id}/agent-mode", json={"mode": "public"})

    svc_resp = await client.get("/api/services")
    service_ids = [s["id"] for s in svc_resp.json()]

    assert public_id in service_ids
    assert internal_id not in service_ids


@pytest.mark.asyncio
async def test_government_user_type_normalized(client):
    """Legacy user_type=government is normalized to organization+government subtype."""
    gov_user = {**VALID_ORG, "user_type": "government", "org_subtype": None, "email": "gov@test.com"}
    resp = await client.post("/api/users", json=gov_user)
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_type"] == "organization"
    assert data["org_subtype"] == "government"
