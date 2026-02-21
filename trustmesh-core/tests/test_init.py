"""Integration tests for the Zig onboard/init API endpoints.

These test against the running Zig HTTP server (not Python ASGI).
Prerequisites: Zig server running on :8000 with a fresh or seeded DB.

Run with: uv run pytest tests/test_init.py -v

NOTE: These tests create real users in the database, so they should be run
against a test database or cleaned up after. The onboard endpoint only allows
calls from localhost, so remote test runners will fail.
"""

import httpx
import pytest
import uuid

ZIG_URL = "http://localhost:8000"


def _is_zig_server_running() -> bool:
    try:
        r = httpx.get(f"{ZIG_URL}/api/onboard/status", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_zig_server_running(),
    reason="Zig HTTP server not running on :8000",
)


def _unique_username() -> str:
    """Generate a unique username to avoid conflicts between test runs."""
    return f"test_{uuid.uuid4().hex[:8]}"


class TestOnboardStatus:
    def test_status_no_auth(self):
        """GET /api/onboard/status works without authentication."""
        resp = httpx.get(f"{ZIG_URL}/api/onboard/status", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert "initialized" in data
        assert "user_count" in data
        assert "max_users" in data
        assert isinstance(data["initialized"], bool)
        assert isinstance(data["user_count"], int)
        assert data["max_users"] == 50


class TestOnboardInit:
    def test_init_requires_body(self):
        """POST /api/onboard/init with empty body returns 400."""
        resp = httpx.post(f"{ZIG_URL}/api/onboard/init", content=b"", timeout=5.0)
        assert resp.status_code == 400

    def test_init_requires_username(self):
        """POST /api/onboard/init without username returns 400."""
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={"password": "SecurePass123!"},
            timeout=5.0,
        )
        assert resp.status_code == 400

    def test_init_requires_password(self):
        """POST /api/onboard/init without password returns 400."""
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={"username": _unique_username()},
            timeout=5.0,
        )
        assert resp.status_code == 400

    def test_init_weak_password_rejected(self):
        """Short or weak passwords are rejected."""
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={"username": _unique_username(), "password": "short"},
            timeout=5.0,
        )
        assert resp.status_code == 400

    def test_init_no_uppercase_rejected(self):
        """Password without uppercase is rejected."""
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={"username": _unique_username(), "password": "alllowercase123"},
            timeout=5.0,
        )
        assert resp.status_code == 400

    def test_init_no_digit_rejected(self):
        """Password without digit is rejected."""
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={"username": _unique_username(), "password": "AllLettersNoDigit"},
            timeout=5.0,
        )
        assert resp.status_code == 400

    def test_init_success(self):
        """POST /api/onboard/init creates user + agent + DID."""
        username = _unique_username()
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={
                "username": username,
                "password": "SecurePass2026!",
                "display_name": "Test User",
                "user_type": "person",
            },
            timeout=30.0,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "user_id" in data
        assert "did" in data
        assert "session_token" in data
        assert "username" in data

        # Validate DID format
        assert data["did"].startswith("did:key:z"), f"Bad DID: {data['did']}"

        # Validate UUID format for user_id
        assert len(data["user_id"]) == 36

        # Session cookie should be set
        assert "trustmesh_session" in resp.cookies

    def test_init_duplicate_username(self):
        """Creating a second user with same username fails."""
        username = _unique_username()
        # First create succeeds
        resp1 = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={
                "username": username,
                "password": "SecurePass2026!",
                "display_name": "First User",
            },
            timeout=30.0,
        )
        assert resp1.status_code == 200

        # Second create with same username fails
        resp2 = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={
                "username": username,
                "password": "SecurePass2026!",
                "display_name": "Second User",
            },
            timeout=30.0,
        )
        assert resp2.status_code == 409  # Conflict

    def test_init_session_works(self):
        """Session from init can access /api/auth/me."""
        username = _unique_username()
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={
                "username": username,
                "password": "SecurePass2026!",
                "display_name": "Session Test",
            },
            timeout=30.0,
        )
        assert resp.status_code == 200

        # Use session to call /api/auth/me
        token = resp.cookies.get("trustmesh_session")
        assert token

        me_resp = httpx.get(
            f"{ZIG_URL}/api/auth/me",
            cookies={"trustmesh_session": token},
            timeout=5.0,
        )
        assert me_resp.status_code == 200, me_resp.text
        me_data = me_resp.json()
        assert me_data["username"] == username

    def test_init_short_username(self):
        """Username under 2 chars is rejected."""
        resp = httpx.post(
            f"{ZIG_URL}/api/onboard/init",
            json={"username": "x", "password": "SecurePass2026!"},
            timeout=5.0,
        )
        assert resp.status_code == 400
