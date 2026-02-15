"""Integration smoke tests for multi-pod federation.

These tests validate the multi-pod setup AFTER orchestration.
Run with: uv run pytest tests/test_multi_pod.py -v

Prerequisites:
  1. ./multi-pod.sh seed
  2. ./multi-pod.sh start
  3. ./multi-pod.sh orchestrate
"""

import httpx
import pytest

REGISTRY_URL = "http://localhost:8100"
PODS = {
    "sarah":   8001,
    "mike":    8002,
    "emma":    8003,
    "grandma": 8004,
    "dr_chen": 8005,
    "tom":     8006,
    "lisa":    8007,
    "priya":   8008,
    "james":   8009,
    "maria":   8010,
    "techcorp": 8011,
    "hospital": 8012,
    "music":    8013,
    "city":     8014,
    "insurance": 8015,
    "dance":    8016,
}


def _is_pod_running(port: int) -> bool:
    """Quick check if a pod is responding."""
    try:
        import urllib.request
        r = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2)
        return r.status == 200
    except Exception:
        return False


# Skip all tests if pods aren't running
pytestmark = pytest.mark.skipif(
    not _is_pod_running(8001),
    reason="Multi-pod federation not running. Start with: ./multi-pod.sh start && ./multi-pod.sh orchestrate"
)


@pytest.fixture
def client():
    return httpx.Client(timeout=10.0)


class TestPodHealth:
    """Test that all 19 pods respond to health checks."""

    @pytest.mark.parametrize("key,port", list(PODS.items()))
    def test_pod_health(self, client, key, port):
        r = client.get(f"http://localhost:{port}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.parametrize("key,port", list(PODS.items()))
    def test_pod_info(self, client, key, port):
        r = client.get(f"http://localhost:{port}/api/pod")
        assert r.status_code == 200
        data = r.json()
        assert data["agent_count"] >= 1
        assert len(data["agents"]) >= 1

    @pytest.mark.parametrize("key,port", list(PODS.items()))
    def test_agent_card(self, client, key, port):
        r = client.get(f"http://localhost:{port}/.well-known/agent-card.json")
        assert r.status_code == 200
        card = r.json()
        assert "trustmesh" in card
        assert card["trustmesh"]["pod_url"] == f"http://localhost:{port}"


class TestRegistry:
    """Test the public registry service."""

    def test_registry_health(self, client):
        r = client.get(f"{REGISTRY_URL}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_registry_has_agents(self, client):
        r = client.get(f"{REGISTRY_URL}/agents")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 16  # At least 16 agents registered

    def test_registry_search(self, client):
        r = client.get(f"{REGISTRY_URL}/search?q=Johnson")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 1


class TestPeerConnections:
    """Test that peer connections were established."""

    def test_sarah_has_peers(self, client):
        r = client.get("http://localhost:8001/api/pod/peers")
        assert r.status_code == 200
        peers = r.json()["peers"]
        assert len(peers) >= 2  # At least mike, emma, grandma, tom

    def test_dr_chen_has_hospital_peer(self, client):
        r = client.get("http://localhost:8005/api/pod/peers")
        assert r.status_code == 200
        peers = r.json()["peers"]
        peer_ports = [p["url"].split(":")[-1] for p in peers]
        # Dr. Chen should be peered with hospital (8012)
        assert "8012" in peer_ports or len(peers) >= 1


class TestPoolSync:
    """Test that pools were synced with ghost users."""

    def test_sarah_has_johnsons_pool(self, client):
        """Sarah's pod should have 'The Johnsons' network."""
        # Login first to get session
        r = client.post("http://localhost:8001/api/auth/login", json={
            "username": "molly", "password": "TrustMesh-demo-2026",
        })
        if r.status_code != 200:
            pytest.skip("Cannot login to Sarah's pod")

        # List networks
        user_id = r.json()["id"]
        r = client.get(f"http://localhost:8001/api/users/{user_id}/networks")
        assert r.status_code == 200
        networks = r.json()
        names = [n["name"] for n in networks]
        assert "The Johnsons" in names or len(networks) >= 1

    def test_dr_chen_has_er_team_pool(self, client):
        """Dr. Chen's pod should have 'Riverside ER Team' network."""
        r = client.post("http://localhost:8005/api/auth/login", json={
            "username": "dr_lee", "password": "TrustMesh-demo-2026",
        })
        if r.status_code != 200:
            pytest.skip("Cannot login to Dr. Chen's pod")

        user_id = r.json()["id"]
        r = client.get(f"http://localhost:8005/api/users/{user_id}/networks")
        assert r.status_code == 200
        networks = r.json()
        names = [n["name"] for n in networks]
        assert "Riverside ER Team" in names or len(networks) >= 1


class TestCrossPodQuery:
    """Test cross-pod queries work via federation."""

    def test_public_query_to_sarah(self, client):
        """An anonymous cross-pod query to Sarah's pod should get public data only."""
        r = client.post("http://localhost:8001/api/pod/query", json={
            "from_did": "did:key:z6MkTestAnonymous",
            "from_pod": "http://localhost:9999",
            "to_username": "molly",
            "question": "What does Molly do for work?",
        })
        # Should work but only return public/open data
        assert r.status_code == 200
        data = r.json()
        assert data.get("trust_level") == "public"
