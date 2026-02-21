"""Integration tests for the Zig Memory API endpoints.

These test against the running Zig HTTP server (not Python ASGI).
Prerequisites: Zig server running on :8000 with a seeded DB.

Run with: uv run pytest tests/test_memory_api.py -v
"""

import httpx
import pytest

ZIG_URL = "http://localhost:8000"


def _is_zig_server_running() -> bool:
    try:
        r = httpx.get(f"{ZIG_URL}/api/memory/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_zig_server_running(),
    reason="Zig HTTP server not running on :8000",
)


@pytest.fixture(scope="module")
def client():
    """Single authenticated client for the entire test module.

    Session rotation invalidates all prior sessions on each login,
    so we login once and reuse the session across all tests.
    """
    c = httpx.Client(base_url=ZIG_URL, timeout=15.0)
    resp = c.post(
        "/api/auth/login",
        json={"username": "molly", "password": "TrustMesh-demo-2026"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    # Zig server sets Secure cookie — extract manually for HTTP testing
    cookie_header = resp.headers.get("set-cookie", "")
    if "trustmesh_session=" in cookie_header:
        token = cookie_header.split("trustmesh_session=")[1].split(";")[0]
        c.cookies.set("trustmesh_session", token)
    yield c
    c.close()


class TestMemoryHealth:
    def test_health_no_auth(self):
        """GET /api/memory/health works without authentication."""
        resp = httpx.get(f"{ZIG_URL}/api/memory/health", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "db" in data
        assert "transit" in data

    def test_health_all_ok(self):
        resp = httpx.get(f"{ZIG_URL}/api/memory/health", timeout=5.0)
        data = resp.json()
        assert data["db"] is True
        assert data["transit"] is True
        assert data["session"] is True


class TestMemoryStore:
    def test_store_requires_auth(self):
        """POST /api/memory/store without auth returns 401."""
        resp = httpx.post(
            f"{ZIG_URL}/api/memory/store",
            json={"content": "test", "title": "test"},
            timeout=5.0,
        )
        assert resp.status_code == 401

    def test_store_success(self, client):
        """POST /api/memory/store creates a capsule."""
        resp = client.post(
            "/api/memory/store",
            json={
                "content": "Blood pressure 120/80, feeling good today",
                "title": "Health Check",
                "category": "health",
                "visibility": "private",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["status"] == "stored"
        assert len(data["id"]) == 36  # UUID

    def test_store_missing_content(self, client):
        """POST /api/memory/store without content returns 400."""
        resp = client.post("/api/memory/store", json={"title": "No content"})
        assert resp.status_code == 400

    def test_store_empty_body(self, client):
        """POST /api/memory/store with empty body returns 400."""
        resp = client.post("/api/memory/store", content=b"")
        assert resp.status_code == 400

    def test_store_defaults(self, client):
        """POST /api/memory/store with only content uses defaults."""
        resp = client.post("/api/memory/store", json={"content": "Just some data"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "stored"


class TestMemoryRecall:
    def test_recall_requires_auth(self):
        """POST /api/memory/recall without auth returns 401."""
        resp = httpx.post(
            f"{ZIG_URL}/api/memory/recall",
            json={"query": "health"},
            timeout=5.0,
        )
        assert resp.status_code == 401

    def test_recall_success(self, client):
        """Store then recall a capsule by keyword."""
        # Store
        client.post(
            "/api/memory/store",
            json={
                "content": "Unique test data: xylophone-metric-42",
                "title": "Recall Test",
                "category": "test",
            },
        )
        # Recall
        resp = client.post(
            "/api/memory/recall",
            json={"query": "xylophone metric", "top_k": 5},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "results" in data
        # Should find at least the capsule we just stored
        found = any("xylophone" in r.get("content", "") for r in data["results"])
        assert found, f"Expected to find xylophone in recall results: {data}"

    def test_recall_empty_query(self, client):
        """POST /api/memory/recall without query returns 400."""
        resp = client.post("/api/memory/recall", json={})
        assert resp.status_code == 400


class TestMemoryList:
    def test_list_requires_auth(self):
        """GET /api/memory/list without auth returns 401."""
        resp = httpx.get(f"{ZIG_URL}/api/memory/list", timeout=5.0)
        assert resp.status_code == 401

    def test_list_success(self, client):
        """GET /api/memory/list returns capsules."""
        resp = client.get("/api/memory/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "capsules" in data
        assert isinstance(data["capsules"], list)

    def test_list_with_category(self, client):
        """GET /api/memory/list?category=health filters by category."""
        resp = client.get("/api/memory/list?category=health")
        assert resp.status_code == 200
        data = resp.json()
        for cap in data["capsules"]:
            assert cap["category"] == "health"

    def test_list_with_limit(self, client):
        """GET /api/memory/list?limit=2 caps results."""
        resp = client.get("/api/memory/list?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["capsules"]) <= 2


class TestMemoryCount:
    def test_count_requires_auth(self):
        resp = httpx.get(f"{ZIG_URL}/api/memory/count", timeout=5.0)
        assert resp.status_code == 401

    def test_count_success(self, client):
        resp = client.get("/api/memory/count")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] >= 0


class TestMemoryGetOne:
    def test_get_requires_auth(self):
        resp = httpx.get(f"{ZIG_URL}/api/memory/some-id", timeout=5.0)
        assert resp.status_code == 401

    def test_get_not_found(self, client):
        resp = client.get("/api/memory/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_get_success(self, client):
        """Store a capsule then retrieve it by ID."""
        # Store
        store_resp = client.post(
            "/api/memory/store",
            json={"content": "Get test content", "title": "Get Test", "category": "test"},
        )
        assert store_resp.status_code == 201
        capsule_id = store_resp.json()["id"]

        # Get
        resp = client.get(f"/api/memory/{capsule_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == capsule_id
        assert data["title"] == "Get Test"
        assert data["content"] == "Get test content"
        assert data["category"] == "test"


class TestMemoryDelete:
    def test_delete_requires_auth(self):
        resp = httpx.delete(f"{ZIG_URL}/api/memory/some-id", timeout=5.0)
        assert resp.status_code == 401

    def test_delete_success(self, client):
        """Store then delete (archive) a capsule."""
        # Store
        store_resp = client.post(
            "/api/memory/store",
            json={"content": "Delete test", "title": "Delete Me"},
        )
        capsule_id = store_resp.json()["id"]

        # Delete
        resp = client.delete(f"/api/memory/{capsule_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

        # Verify it's gone from GET
        get_resp = client.get(f"/api/memory/{capsule_id}")
        assert get_resp.status_code == 404
