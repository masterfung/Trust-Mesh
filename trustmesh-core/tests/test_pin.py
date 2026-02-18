"""Tests for vault PIN protection: set, verify, status, validation, and auth checks."""

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

VALID_USER_A = {
    "username": "pin_user_a",
    "display_name": "PIN User A",
    "bio": "",
    "password": "SecureTestPass1!",
}

VALID_USER_B = {
    "username": "pin_user_b",
    "display_name": "PIN User B",
    "bio": "",
    "password": "SecureTestPass2!",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def signup_user(client: AsyncClient, user_data: dict) -> tuple[dict, dict]:
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    cookies = dict(resp.cookies)
    return resp.json(), cookies


# ===================================================================
# SET PIN
# ===================================================================


@pytest.mark.asyncio
async def test_set_pin_success(client):
    """Set a 6-digit PIN for a user returns has_pin=true."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_pin"] is True


@pytest.mark.asyncio
async def test_set_pin_six_digits(client):
    """Set a 6-digit PIN succeeds (PIN can be 4-8 digits)."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["has_pin"] is True


@pytest.mark.asyncio
async def test_set_pin_eight_digits(client):
    """Set an 8-digit PIN succeeds (max length)."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "12345678"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["has_pin"] is True


@pytest.mark.asyncio
async def test_set_pin_update_existing(client):
    """Setting a new PIN replaces the old one."""
    user, cookies = await signup_user(client, VALID_USER_A)

    # Set initial PIN
    resp1 = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies,
    )
    assert resp1.status_code == 200

    # Update to new PIN
    resp2 = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "567890"},
        cookies=cookies,
    )
    assert resp2.status_code == 200

    # Verify old PIN no longer works
    verify_old = await client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "123456"},
        cookies=cookies,
    )
    assert verify_old.status_code == 403

    # Verify new PIN works
    verify_new = await client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "567890"},
        cookies=cookies,
    )
    assert verify_new.status_code == 200
    assert verify_new.json()["verified"] is True


# ===================================================================
# CHECK PIN STATUS
# ===================================================================


@pytest.mark.asyncio
async def test_pin_status_no_pin(client):
    """Check PIN status when no PIN is set returns has_pin=false."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.get(
        f"/api/users/{user['id']}/pin/status",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["has_pin"] is False


@pytest.mark.asyncio
async def test_pin_status_with_pin(client):
    """Check PIN status after setting a PIN returns has_pin=true."""
    user, cookies = await signup_user(client, VALID_USER_A)

    # Set PIN first
    await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies,
    )

    resp = await client.get(
        f"/api/users/{user['id']}/pin/status",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["has_pin"] is True


# ===================================================================
# VERIFY PIN
# ===================================================================


@pytest.mark.asyncio
async def test_verify_correct_pin(client):
    """Verify the correct PIN returns verified=true with a token."""
    user, cookies = await signup_user(client, VALID_USER_A)

    # Set PIN
    await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "654321"},
        cookies=cookies,
    )

    # Verify correct PIN
    resp = await client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "654321"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    assert data["token"] is not None
    assert len(data["token"]) > 0
    assert data["expires_in"] == 300  # 5 minutes


@pytest.mark.asyncio
async def test_verify_wrong_pin(client):
    """Verify an incorrect PIN returns 403."""
    user, cookies = await signup_user(client, VALID_USER_A)

    # Set PIN
    await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies,
    )

    # Verify wrong PIN
    resp = await client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "999123"},
        cookies=cookies,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_verify_pin_not_set(client):
    """Verify PIN when no PIN is set returns 400."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "123456"},
        cookies=cookies,
    )
    assert resp.status_code == 400
    assert "not set" in resp.text.lower() or "pin" in resp.text.lower()


# ===================================================================
# PIN VALIDATION (FORMAT)
# ===================================================================


@pytest.mark.asyncio
async def test_pin_too_short(client):
    """PIN with fewer than 6 digits returns 422 validation error."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "12345"},
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pin_too_long(client):
    """PIN with more than 8 digits returns 422 validation error."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456789"},
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pin_non_numeric(client):
    """PIN with non-numeric characters returns 422 validation error."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "abcd"},
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pin_alphanumeric(client):
    """PIN with mixed alphanumeric characters returns 422."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "12ab"},
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pin_with_spaces(client):
    """PIN with spaces returns 422."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "12 34"},
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_verify_pin_validation_too_short(client):
    """Verify endpoint also validates PIN format (too short)."""
    user, cookies = await signup_user(client, VALID_USER_A)

    resp = await client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "12345"},
        cookies=cookies,
    )
    assert resp.status_code == 422


# ===================================================================
# AUTH CHECKS
# ===================================================================


@pytest.mark.asyncio
async def test_set_pin_wrong_user(client):
    """Cannot set another user's PIN (returns 403)."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    user_b, cookies_b = await signup_user(client, VALID_USER_B)

    # User B tries to set user A's PIN
    resp = await client.post(
        f"/api/users/{user_a['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_verify_pin_wrong_user(client):
    """Cannot verify another user's PIN (returns 403)."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    user_b, cookies_b = await signup_user(client, VALID_USER_B)

    # Set PIN for user A
    await client.post(
        f"/api/users/{user_a['id']}/pin",
        json={"pin": "123456"},
        cookies=cookies_a,
    )

    # User B tries to verify user A's PIN
    resp = await client.post(
        f"/api/users/{user_a['id']}/pin/verify",
        json={"pin": "123456"},
        cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pin_status_wrong_user(client):
    """Cannot check another user's PIN status (returns 403)."""
    user_a, cookies_a = await signup_user(client, VALID_USER_A)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)

    resp = await client.get(
        f"/api/users/{user_a['id']}/pin/status",
        cookies=cookies_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_set_pin_no_auth(anon_client, client):
    """Set PIN without authentication returns 401."""
    user, _cookies = await signup_user(client, VALID_USER_A)

    resp = await anon_client.post(
        f"/api/users/{user['id']}/pin",
        json={"pin": "123456"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_verify_pin_no_auth(anon_client, client):
    """Verify PIN without authentication returns 401."""
    user, _cookies = await signup_user(client, VALID_USER_A)

    resp = await anon_client.post(
        f"/api/users/{user['id']}/pin/verify",
        json={"pin": "123456"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pin_status_no_auth(anon_client, client):
    """Check PIN status without authentication returns 401."""
    user, _cookies = await signup_user(client, VALID_USER_A)

    resp = await anon_client.get(
        f"/api/users/{user['id']}/pin/status",
    )
    assert resp.status_code == 401


# ===================================================================
# CRYPTO-LEVEL PIN TESTS
# ===================================================================


@pytest.mark.asyncio
async def test_hash_pin_produces_consistent_verification():
    """hash_pin + verify_pin round-trip works correctly."""
    from src.crypto import hash_pin, verify_pin

    pin = "5678"
    hashed = hash_pin(pin)

    assert verify_pin(pin, hashed) is True
    assert verify_pin("0000", hashed) is False
    assert verify_pin("5679", hashed) is False


@pytest.mark.asyncio
async def test_hash_pin_produces_different_hashes():
    """hash_pin with same input produces different hashes (random salt)."""
    from src.crypto import hash_pin

    hash1 = hash_pin("1234")
    hash2 = hash_pin("1234")
    # Hashes should differ because of random salt
    assert hash1 != hash2


@pytest.mark.asyncio
async def test_hash_pin_format():
    """hash_pin produces salt$hash format."""
    from src.crypto import hash_pin

    hashed = hash_pin("1234")
    parts = hashed.split("$")
    assert len(parts) == 2
    # Salt is 16 bytes = 32 hex chars
    assert len(parts[0]) == 32
    # Hash is 32 bytes = 64 hex chars
    assert len(parts[1]) == 64


@pytest.mark.asyncio
async def test_verify_pin_with_corrupted_hash():
    """verify_pin with corrupted hash returns False (does not raise)."""
    from src.crypto import verify_pin

    assert verify_pin("1234", "garbage") is False
    assert verify_pin("1234", "") is False
    assert verify_pin("1234", "$") is False
