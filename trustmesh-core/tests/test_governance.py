"""Tests for the data governance model: visibility levels, emergency access flags,
reshare control, backward-compatible tier mapping, and context filtering.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db
from src.rate_limit import _connection_limiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB, auth state, and rate limiters for each test."""
    sessions.clear()
    _login_attempts.clear()
    _connection_limiter._events.clear()

    from src.main import vault_keys, pin_tokens
    vault_keys.clear()
    pin_tokens.clear()

    await drop_db()
    await init_db()
    yield
    await drop_db()


def _make_transport():
    from src.main import app
    return ASGITransport(app=app)


@pytest_asyncio.fixture
async def client():
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client():
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_USER = {
    "username": "gov_user",
    "display_name": "Governance User",
    "bio": "",
    "password": "SecureTestPass1!",
}

VALID_USER_B = {
    "username": "gov_user_b",
    "display_name": "Governance User B",
    "bio": "",
    "password": "SecureTestPass2!",
}

BASE_CAPSULE = {
    "capsule_type": "preference",
    "title": "Test Capsule",
    "content": "Test content for governance.",
    "network_ids": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def signup_user(client: AsyncClient, user_data: dict) -> tuple[dict, dict]:
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    cookies = dict(resp.cookies)
    return resp.json(), cookies


async def create_capsule(
    client: AsyncClient, user_id: str, cookies: dict, payload: dict | None = None,
) -> dict:
    data = payload or BASE_CAPSULE
    resp = await client.post(
        f"/api/users/{user_id}/capsules", json=data, cookies=cookies,
    )
    assert resp.status_code == 200, f"Create capsule failed: {resp.text}"
    return resp.json()


# ===================================================================
# VISIBILITY TESTS
# ===================================================================


@pytest.mark.asyncio
async def test_create_capsule_visibility_private(client):
    """Create capsule with visibility=private stores and returns correct visibility."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "visibility": "private",
    })

    assert capsule["visibility"] == "private"
    assert capsule["tier"] == "private"  # backward-compat alias


@pytest.mark.asyncio
async def test_create_capsule_visibility_internal(client):
    """Create capsule with visibility=internal stores and returns correct fields."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "visibility": "internal",
    })

    assert capsule["visibility"] == "internal"
    assert capsule["tier"] == "network"  # internal maps to old "network" tier


@pytest.mark.asyncio
async def test_create_capsule_visibility_shareable(client):
    """Create capsule with visibility=shareable stores and returns correct fields."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "visibility": "shareable",
    })

    assert capsule["visibility"] == "shareable"
    assert capsule["tier"] == "network"  # shareable also maps to "network"


@pytest.mark.asyncio
async def test_create_capsule_visibility_open(client):
    """Create capsule with visibility=open stores and returns correct fields."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "visibility": "open",
    })

    assert capsule["visibility"] == "open"
    assert capsule["tier"] == "public"  # open maps to old "public" tier


@pytest.mark.asyncio
async def test_create_capsule_invalid_visibility(client):
    """Create capsule with invalid visibility returns 422."""
    user, cookies = await signup_user(client, VALID_USER)
    resp = await client.post(
        f"/api/users/{user['id']}/capsules",
        json={**BASE_CAPSULE, "visibility": "top_secret"},
        cookies=cookies,
    )
    assert resp.status_code == 422


# ===================================================================
# EMERGENCY ACCESSIBLE FLAG
# ===================================================================


@pytest.mark.asyncio
async def test_create_capsule_emergency_accessible_true(client):
    """Create capsule with emergency_accessible=true returns flag correctly."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "emergency_accessible": True,
    })

    assert capsule["emergency_accessible"] is True


@pytest.mark.asyncio
async def test_create_capsule_emergency_accessible_false(client):
    """Create capsule with emergency_accessible=false (default) is stored."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, BASE_CAPSULE)

    assert capsule["emergency_accessible"] is False


# ===================================================================
# RESHARE FLAG
# ===================================================================


@pytest.mark.asyncio
async def test_create_capsule_can_reshare_true(client):
    """Create capsule with can_reshare=true returns flag correctly."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "can_reshare": True,
    })

    assert capsule["can_reshare"] is True


@pytest.mark.asyncio
async def test_create_capsule_can_reshare_false_default(client):
    """Create capsule without can_reshare defaults to false."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, BASE_CAPSULE)

    assert capsule["can_reshare"] is False


# ===================================================================
# UPDATE CAPSULE VISIBILITY
# ===================================================================


@pytest.mark.asyncio
async def test_update_capsule_visibility(client):
    """Update capsule to change visibility from private to internal."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "visibility": "private",
    })
    assert capsule["visibility"] == "private"

    # Update visibility
    resp = await client.put(
        f"/api/capsules/{capsule['id']}",
        json={"visibility": "internal"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["visibility"] == "internal"
    assert updated["tier"] == "network"


@pytest.mark.asyncio
async def test_update_capsule_emergency_accessible(client):
    """Update capsule to toggle emergency_accessible flag."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, BASE_CAPSULE)
    assert capsule["emergency_accessible"] is False

    resp = await client.put(
        f"/api/capsules/{capsule['id']}",
        json={"emergency_accessible": True},
        cookies=cookies,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["emergency_accessible"] is True


@pytest.mark.asyncio
async def test_update_capsule_can_reshare(client):
    """Update capsule to toggle can_reshare flag."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, BASE_CAPSULE)
    assert capsule["can_reshare"] is False

    resp = await client.put(
        f"/api/capsules/{capsule['id']}",
        json={"can_reshare": True},
        cookies=cookies,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["can_reshare"] is True


# ===================================================================
# BACKWARD COMPATIBILITY: TIER FIELD
# ===================================================================


@pytest.mark.asyncio
async def test_create_capsule_with_tier_private(client):
    """Create capsule with old tier=private maps to visibility=private."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "tier": "private",
    })

    assert capsule["visibility"] == "private"
    assert capsule["tier"] == "private"


@pytest.mark.asyncio
async def test_create_capsule_with_tier_network(client):
    """Create capsule with old tier=network maps to visibility=internal."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "tier": "network",
    })

    assert capsule["visibility"] == "internal"
    assert capsule["tier"] == "network"


@pytest.mark.asyncio
async def test_create_capsule_with_tier_public(client):
    """Create capsule with old tier=public maps to visibility=open via effective_visibility()."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "tier": "public",
    })

    assert capsule["visibility"] == "open"
    assert capsule["tier"] == "public"


@pytest.mark.asyncio
async def test_tier_overrides_default_visibility(client):
    """When tier is provided, effective_visibility() maps it, overriding the default."""
    user, cookies = await signup_user(client, VALID_USER)
    # Send both tier and default visibility — tier should win
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "tier": "public",
        # visibility defaults to "private" in schema, but tier="public" should override
    })

    assert capsule["visibility"] == "open"


# ===================================================================
# effective_visibility() UNIT TEST (schema-level)
# ===================================================================


@pytest.mark.asyncio
async def test_effective_visibility_with_tier():
    """CapsuleCreate.effective_visibility() maps tier to visibility correctly."""
    from src.schemas import CapsuleCreate

    schema = CapsuleCreate(
        capsule_type="memory", title="Test", content="Test content",
        tier="public",
    )
    assert schema.effective_visibility() == "open"

    schema2 = CapsuleCreate(
        capsule_type="memory", title="Test", content="Test content",
        tier="network",
    )
    assert schema2.effective_visibility() == "internal"

    schema3 = CapsuleCreate(
        capsule_type="memory", title="Test", content="Test content",
        tier="private",
    )
    assert schema3.effective_visibility() == "private"


@pytest.mark.asyncio
async def test_effective_visibility_without_tier():
    """CapsuleCreate.effective_visibility() returns visibility when no tier provided."""
    from src.schemas import CapsuleCreate

    schema = CapsuleCreate(
        capsule_type="memory", title="Test", content="Test content",
        visibility="shareable",
    )
    assert schema.effective_visibility() == "shareable"


# ===================================================================
# CONTEXT FILTER ON LIST CAPSULES
# ===================================================================


@pytest.mark.asyncio
async def test_list_capsules_with_context_filter_work(client):
    """List capsules filtered by context=work returns only work + both capsules."""
    user, cookies = await signup_user(client, VALID_USER)

    # Create capsules with different contexts
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Work Capsule", "context": "work",
    })
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Personal Capsule", "context": "personal",
    })
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Both Capsule", "context": "both",
    })

    # Filter by work
    resp = await client.get(
        f"/api/users/{user['id']}/capsules?context=work", cookies=cookies,
    )
    assert resp.status_code == 200
    capsules = resp.json()
    titles = {c["title"] for c in capsules}
    assert "Work Capsule" in titles
    assert "Both Capsule" in titles
    assert "Personal Capsule" not in titles


@pytest.mark.asyncio
async def test_list_capsules_with_context_filter_personal(client):
    """List capsules filtered by context=personal returns only personal + both capsules."""
    user, cookies = await signup_user(client, VALID_USER)

    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Work Capsule", "context": "work",
    })
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Personal Capsule", "context": "personal",
    })
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Both Capsule", "context": "both",
    })

    resp = await client.get(
        f"/api/users/{user['id']}/capsules?context=personal", cookies=cookies,
    )
    assert resp.status_code == 200
    capsules = resp.json()
    titles = {c["title"] for c in capsules}
    assert "Personal Capsule" in titles
    assert "Both Capsule" in titles
    assert "Work Capsule" not in titles


@pytest.mark.asyncio
async def test_list_capsules_no_context_filter(client):
    """List capsules without context filter returns all capsules."""
    user, cookies = await signup_user(client, VALID_USER)

    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Work Capsule", "context": "work",
    })
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Personal Capsule", "context": "personal",
    })

    resp = await client.get(
        f"/api/users/{user['id']}/capsules", cookies=cookies,
    )
    assert resp.status_code == 200
    capsules = resp.json()
    assert len(capsules) == 2


@pytest.mark.asyncio
async def test_list_capsules_context_all_returns_everything(client):
    """List capsules with context=all returns all capsules (same as no filter)."""
    user, cookies = await signup_user(client, VALID_USER)

    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Work Capsule", "context": "work",
    })
    await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "title": "Personal Capsule", "context": "personal",
    })

    resp = await client.get(
        f"/api/users/{user['id']}/capsules?context=all", cookies=cookies,
    )
    assert resp.status_code == 200
    capsules = resp.json()
    assert len(capsules) == 2


# ===================================================================
# CATEGORY FIELD
# ===================================================================


@pytest.mark.asyncio
async def test_create_capsule_with_category(client):
    """Create capsule with category returns category in response."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "category": "health",
    })

    assert capsule["category"] == "health"


@pytest.mark.asyncio
async def test_create_capsule_empty_category(client):
    """Create capsule without category defaults to empty string."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, BASE_CAPSULE)

    assert capsule["category"] == ""


# ===================================================================
# COMBINED GOVERNANCE SCENARIO
# ===================================================================


@pytest.mark.asyncio
async def test_full_governance_scenario(client):
    """Full scenario: create capsule with all governance fields, verify, update, verify again."""
    user, cookies = await signup_user(client, VALID_USER)

    # Create with full governance fields
    capsule = await create_capsule(client, user["id"], cookies, {
        "capsule_type": "preference",
        "title": "Health Record",
        "content": "Patient blood type A+",
        "visibility": "shareable",
        "emergency_accessible": True,
        "can_reshare": False,
        "category": "health",
        "context": "personal",
        "network_ids": [],
    })

    assert capsule["visibility"] == "shareable"
    assert capsule["emergency_accessible"] is True
    assert capsule["can_reshare"] is False
    assert capsule["category"] == "health"
    assert capsule["context"] == "personal"

    # Update to make it open and reshare-enabled
    resp = await client.put(
        f"/api/capsules/{capsule['id']}",
        json={
            "visibility": "open",
            "can_reshare": True,
            "emergency_accessible": False,
        },
        cookies=cookies,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["visibility"] == "open"
    assert updated["can_reshare"] is True
    assert updated["emergency_accessible"] is False

    # Verify the response also has both tier and visibility
    assert updated["tier"] == "public"  # open -> public tier


@pytest.mark.asyncio
async def test_update_capsule_visibility_via_tier(client):
    """Update capsule visibility via old tier field (backward compat on update)."""
    user, cookies = await signup_user(client, VALID_USER)
    capsule = await create_capsule(client, user["id"], cookies, {
        **BASE_CAPSULE, "visibility": "private",
    })
    assert capsule["visibility"] == "private"

    # Update via tier field instead of visibility
    resp = await client.put(
        f"/api/capsules/{capsule['id']}",
        json={"tier": "public"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["visibility"] == "open"
    assert updated["tier"] == "public"
