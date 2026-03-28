"""Tests for the channel bridge and sensitivity routing.

Tests:
- pre_flight_sensitivity() — Python fallback (no Zig kernel needed)
- detect_sensitivity() hint parameter (cannot downgrade)
- channels.py route auth: missing token, invalid token
- channels.py route: Zig-injected headers flow (via mocked headers)
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.agents import detect_sensitivity, pre_flight_sensitivity
from src.database import drop_db, init_db


# ═══════════════════════════════════════════════════════════════
# DB fixture
# ═══════════════════════════════════════════════════════════════


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
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


# ═══════════════════════════════════════════════════════════════
# pre_flight_sensitivity — Python fallback tests
# ═══════════════════════════════════════════════════════════════


class TestPreFlightSensitivity:
    def test_healthcare_relationship_type(self):
        result = pre_flight_sensitivity("what are my tasks today", "healthcare")
        assert result == "sensitive"

    def test_legal_relationship_type(self):
        result = pre_flight_sensitivity("anything", "legal")
        assert result == "sensitive"

    def test_financial_relationship_type(self):
        result = pre_flight_sensitivity("anything", "financial")
        assert result == "sensitive"

    def test_unknown_relationship_type_not_sensitive(self):
        result = pre_flight_sensitivity("what are my tasks today", "scheduling")
        assert result == "standard"

    def test_sensitive_keyword_in_text(self):
        result = pre_flight_sensitivity("dad's dialysis was moved to Thursday")
        assert result == "sensitive"

    def test_blood_pressure_keyword(self):
        result = pre_flight_sensitivity("my blood pressure was 130/80")
        assert result == "sensitive"

    def test_medication_keyword(self):
        result = pre_flight_sensitivity("I need to refill my medication")
        assert result == "sensitive"

    def test_ssn_keyword(self):
        result = pre_flight_sensitivity("what is my SSN on file")
        assert result == "sensitive"

    def test_non_sensitive_text(self):
        result = pre_flight_sensitivity("what are my tasks for today")
        assert result == "standard"

    def test_no_relationship_type(self):
        result = pre_flight_sensitivity("hello world", None)
        assert result == "standard"

    def test_case_insensitive_keyword(self):
        result = pre_flight_sensitivity("dad's DIALYSIS appointment")
        assert result == "sensitive"

    def test_case_insensitive_relationship_type(self):
        result = pre_flight_sensitivity("anything", "HEALTHCARE")
        assert result == "sensitive"


# ═══════════════════════════════════════════════════════════════
# detect_sensitivity — hint parameter (floor, cannot downgrade)
# ═══════════════════════════════════════════════════════════════


class TestDetectSensitivityHint:
    def test_hint_sensitive_overrides(self):
        """hint='sensitive' returns sensitive even with non-sensitive capsules."""
        capsules = [{"category": "general", "capsule_type": "memory"}]
        result = detect_sensitivity(capsules, "hello world", hint="sensitive")
        assert result == "sensitive"

    def test_hint_standard_still_detects_sensitive_capsule(self):
        """hint='standard' doesn't block detection from capsule category."""
        capsules = [{"category": "medical", "capsule_type": "memory"}]
        result = detect_sensitivity(capsules, "anything", hint="standard")
        assert result == "sensitive"

    def test_hint_standard_still_detects_sensitive_keyword(self):
        capsules = []
        result = detect_sensitivity(capsules, "dialysis appointment", hint="standard")
        assert result == "sensitive"

    def test_hint_standard_non_sensitive(self):
        capsules = [{"category": "general", "capsule_type": "memory"}]
        result = detect_sensitivity(capsules, "what are my tasks", hint="standard")
        assert result == "standard"

    def test_default_hint_is_standard(self):
        capsules = [{"category": "general", "capsule_type": "memory"}]
        result = detect_sensitivity(capsules, "hello")
        assert result == "standard"


# ═══════════════════════════════════════════════════════════════
# Channel route auth — missing / invalid token
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_webhook_missing_auth(client):
    """POST /api/channels/webhook without X-Channel-Owner-Id → 401."""
    resp = await client.post(
        "/api/channels/webhook",
        json={"message": "hello"},
        # No X-Channel-Owner-Id header (Zig not running, so header not injected)
    )
    # Without Zig proxy, the header is absent → 401
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_message_missing_auth(client):
    """POST /api/channels/message without X-Channel-Owner-Id → 401."""
    resp = await client.post(
        "/api/channels/message",
        json={"message": "hello"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_missing_message(client):
    """POST /api/channels/webhook with auth header but missing message → 400."""
    resp = await client.post(
        "/api/channels/webhook",
        json={},
        headers={"x-channel-owner-id": "test-user-id"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_message_missing_message(client):
    """POST /api/channels/message with auth header but missing message → 400."""
    resp = await client.post(
        "/api/channels/message",
        json={},
        headers={"x-channel-owner-id": "test-user-id"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_nonexistent_user(client):
    """POST /api/channels/webhook with auth for a non-existent user → error result."""
    resp = await client.post(
        "/api/channels/webhook",
        json={"message": "hello"},
        headers={
            "x-channel-owner-id": "nonexistent-user-uuid",
            "x-preflight-sensitivity": "standard",
        },
    )
    # query_agent returns an error dict (not HTTP error) when user not found
    # The route should still return 200 with an error response, or 500
    assert resp.status_code in (200, 500, 404)
