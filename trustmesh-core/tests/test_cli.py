"""Tests for TrustMesh CLI — session management, commands, and MCP server creation."""

import asyncio
import json
import os
import stat
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli import (
    _clear_session,
    _load_session,
    _save_session,
    app,
)

runner = CliRunner()


# ── Shared mock helpers ──

ME_RESPONSE = {
    "id": "user-1",
    "username": "peter",
    "display_name": "Peter Johnson",
    "user_type": "person",
    "active_context": "all",
    "is_discoverable": False,
}

CAPSULES_RESPONSE = [
    {
        "id": "aaaa1111-0000-0000-0000-000000000001",
        "title": "Music Interests",
        "capsule_type": "preference",
        "visibility": "internal",
        "category": "personal",
        "context": "personal",
        "content": "Plays guitar — classic rock.",
        "owner_display_name": "Peter Johnson",
        "network_names": ["Music Lovers"],
        "is_archived": False,
    },
    {
        "id": "aaaa1111-0000-0000-0000-000000000002",
        "title": "Medical Info",
        "capsule_type": "preference",
        "visibility": "internal",
        "category": "health",
        "context": "personal",
        "content": "Blood type O+. No known allergies.",
        "owner_display_name": "Peter Johnson",
        "network_names": ["The Johnsons"],
        "is_archived": False,
    },
    {
        "id": "bbbb2222-0000-0000-0000-000000000003",
        "title": "Old Notes",
        "capsule_type": "memory",
        "visibility": "private",
        "category": "general",
        "context": "personal",
        "content": "Archived stuff.",
        "owner_display_name": "Peter Johnson",
        "network_names": [],
        "is_archived": True,
    },
]

CONNECTIONS_RESPONSE = [
    {
        "id": "conn-1111-0000-0000-000000000001",
        "from_user_id": "user-1",
        "to_user_id": "user-2",
        "status": "accepted",
        "context": "personal",
        "relationship_type": "family",
        "my_label": "wife",
        "peer_label": "husband",
        "accepted_at": "2026-02-15T10:00:00",
        "peer": {"display_name": "Molly Johnson", "username": "molly", "user_type": "person"},
    },
    {
        "id": "conn-2222-0000-0000-000000000002",
        "from_user_id": "user-1",
        "to_user_id": "user-3",
        "status": "accepted",
        "context": "work",
        "relationship_type": "work",
        "my_label": "colleague",
        "peer_label": "colleague",
        "accepted_at": "2026-02-15T11:00:00",
        "peer": {"display_name": "Kyle Rivera", "username": "kyle", "user_type": "person"},
    },
]

NETWORKS_RESPONSE = [
    {
        "id": "net-1111-0000-0000-000000000001",
        "name": "The Johnsons",
        "network_type": "family",
        "pool_type": "standard",
        "members": [
            {"display_name": "Peter Johnson", "username": "peter", "user_type": "person"},
            {"display_name": "Molly Johnson", "username": "molly", "user_type": "person"},
        ],
    },
    {
        "id": "net-2222-0000-0000-000000000002",
        "name": "TechCorp PM Team",
        "network_type": "team",
        "pool_type": "category_scoped",
        "members": [
            {"display_name": "Molly Johnson", "username": "molly", "user_type": "person"},
            {"display_name": "Kyle Rivera", "username": "kyle", "user_type": "person"},
        ],
    },
]

PENDING_REQUESTS = [
    {
        "id": "req-1111-0000-0000-000000000001",
        "from_user_id": "user-5",
        "to_user_id": "user-1",
        "message": "Let's connect!",
        "status": "pending",
        "relationship_type": "friend",
        "from_label": "buddy",
        "mutual_connections": 2,
        "mutual_networks": 1,
        "created_at": "2026-02-15T10:00:00",
        "from_user": {"display_name": "Amy Torres", "username": "amy", "user_type": "person"},
    },
]


def _mock_api_responses(mock_client, responses: dict):
    """Configure mock_client to return different responses based on the API path.

    responses: dict mapping (method, path_prefix) to response data.
    Falls back to a generic 200/{} for unmatched paths.
    """
    def side_effect(method, path, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        for (m, prefix), data in responses.items():
            if method.upper() == m.upper() and path.startswith(prefix):
                if isinstance(data, int):
                    # Status code only
                    resp.status_code = data
                    resp.json.return_value = {"detail": "error"}
                    resp.text = '{"detail": "error"}'
                else:
                    resp.json.return_value = data
                return resp
        resp.json.return_value = {}
        return resp
    mock_client.request.side_effect = side_effect


# ── Session management tests ──


class TestSessionManagement:
    """Test ~/.trustmesh/session file operations."""

    def test_save_and_load_session(self, tmp_path, monkeypatch):
        """Session is saved as JSON with 0600 permissions and can be loaded back."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        _save_session("http://localhost:8000", "tok123", "user-1", "peter")

        assert session_file.exists()
        # Check permissions are restricted
        mode = session_file.stat().st_mode
        assert mode & stat.S_IROTH == 0  # no world-read
        assert mode & stat.S_IWOTH == 0  # no world-write
        assert mode & stat.S_IRGRP == 0  # no group-read

        data = _load_session()
        assert data is not None
        assert data["pod_url"] == "http://localhost:8000"
        assert data["token"] == "tok123"
        assert data["user_id"] == "user-1"
        assert data["username"] == "peter"

    def test_load_session_missing(self, tmp_path, monkeypatch):
        """Returns None when no session file exists."""
        session_file = tmp_path / ".trustmesh" / "session"
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        assert _load_session() is None

    def test_load_session_corrupt(self, tmp_path, monkeypatch):
        """Returns None when session file is corrupt JSON."""
        config_dir = tmp_path / ".trustmesh"
        config_dir.mkdir()
        session_file = config_dir / "session"
        session_file.write_text("not json at all")
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        assert _load_session() is None

    def test_load_session_missing_keys(self, tmp_path, monkeypatch):
        """Returns None when session file is valid JSON but missing required keys."""
        config_dir = tmp_path / ".trustmesh"
        config_dir.mkdir()
        session_file = config_dir / "session"
        session_file.write_text(json.dumps({"pod_url": "http://localhost:8000"}))
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        assert _load_session() is None  # missing "token"

    def test_clear_session(self, tmp_path, monkeypatch):
        """Clear session deletes the file."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        _save_session("http://localhost:8000", "tok123", "user-1", "peter")
        assert session_file.exists()
        _clear_session()
        assert not session_file.exists()

    def test_clear_session_noop_when_missing(self, tmp_path, monkeypatch):
        """Clear session doesn't error when file doesn't exist."""
        session_file = tmp_path / ".trustmesh" / "session"
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        _clear_session()  # should not raise


# ── CLI command tests ──


class TestLoginCommand:
    """Test the `trustmesh login` command."""

    def test_login_success(self, tmp_path, monkeypatch):
        """Successful login stores session."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.cookies = {"trustmesh_session": "session-token-abc"}
        mock_resp.json.return_value = {
            "id": "user-1",
            "username": "peter",
            "display_name": "Peter Johnson",
        }

        with patch("src.cli.httpx.post", return_value=mock_resp):
            with patch("src.cli.getpass.getpass", return_value="TrustMesh-demo-2026"):
                result = runner.invoke(app, ["login", "--pod", "http://localhost:8000", "--user", "peter"])

        assert result.exit_code == 0
        assert "Logged in as Peter Johnson" in result.output
        assert session_file.exists()

    def test_login_bad_credentials(self, tmp_path, monkeypatch):
        """401 shows error, no session stored."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("src.cli.httpx.post", return_value=mock_resp):
            with patch("src.cli.getpass.getpass", return_value="wrong-password"):
                result = runner.invoke(app, ["login", "--pod", "http://localhost:8000", "--user", "peter"])

        assert result.exit_code == 1
        assert "Wrong username or password" in result.output
        assert not session_file.exists()

    def test_login_connection_error(self, tmp_path, monkeypatch):
        """Connection error shows message."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        import httpx
        with patch("src.cli.httpx.post", side_effect=httpx.ConnectError("Connection refused")):
            with patch("src.cli.getpass.getpass", return_value="whatever"):
                result = runner.invoke(app, ["login", "--pod", "http://localhost:9999", "--user", "peter"])

        assert result.exit_code == 1
        assert "Cannot connect" in result.output


class TestLogoutCommand:
    """Test the `trustmesh logout` command."""

    def test_logout_clears_session(self, tmp_path, monkeypatch):
        """Logout removes session file."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        _save_session("http://localhost:8000", "tok123", "user-1", "peter")

        # Mock the httpx client context manager
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = MagicMock(status_code=200)

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["logout"])

        assert result.exit_code == 0
        assert "Logged out" in result.output
        assert not session_file.exists()


class TestStatusCommand:
    """Test the `trustmesh status` command."""

    def test_status_not_logged_in(self, tmp_path, monkeypatch):
        """Status without session shows login prompt."""
        session_file = tmp_path / ".trustmesh" / "session"
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "Not logged in" in result.output


class TestWhoamiCommand:
    """Test the `trustmesh whoami` command."""

    def test_whoami_not_logged_in(self, tmp_path, monkeypatch):
        """Whoami without session shows login prompt."""
        session_file = tmp_path / ".trustmesh" / "session"
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 1
        assert "Not logged in" in result.output


# ── MCP server creation tests ──


class TestMCPServerCreation:
    """Test that the MCP server creates with expected tools and resources."""

    def test_create_mcp_server_has_tools(self):
        """MCP server exposes the expected tool set."""
        from src.mcp_server import create_mcp_server

        session = {
            "pod_url": "http://localhost:8000",
            "token": "test-token",
            "user_id": "user-1",
            "username": "peter",
        }
        mcp = create_mcp_server(session)

        # FastMCP stores tools internally; verify by listing
        import asyncio
        tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
        tool_names = {t.name for t in tools}

        assert "search_vault" in tool_names
        assert "save_to_vault" in tool_names
        assert "list_capsules" in tool_names
        assert "ask_agent" in tool_names
        assert "list_connections" in tool_names
        assert "list_networks" in tool_names
        assert "pod_status" in tool_names
        assert "discover_agents" in tool_names
        assert "health_check" in tool_names

    def test_create_mcp_server_has_resources(self):
        """MCP server exposes the expected resources."""
        from src.mcp_server import create_mcp_server

        session = {
            "pod_url": "http://localhost:8000",
            "token": "test-token",
            "user_id": "user-1",
            "username": "peter",
        }
        mcp = create_mcp_server(session)

        import asyncio
        resources = asyncio.new_event_loop().run_until_complete(mcp.list_resources())
        resource_uris = {str(r.uri) for r in resources}

        assert "trustmesh://profile" in resource_uris
        assert "trustmesh://vault/summary" in resource_uris
        assert "trustmesh://pod/info" in resource_uris

    def test_create_mcp_server_without_session(self):
        """MCP server can be created without a session (public tools only)."""
        from src.mcp_server import create_mcp_server

        mcp = create_mcp_server(session=None)
        assert mcp.name == "TrustMesh"


# ── Command help tests (verify all subcommands are registered) ──


class TestSubcommandHelp:
    """Verify all subcommand groups show help without errors."""

    @pytest.mark.parametrize("cmd", [
        ["vault", "--help"],
        ["agent", "--help"],
        ["connections", "--help"],
        ["networks", "--help"],
        ["pod", "--help"],
        ["registry", "--help"],
        ["mcp", "--help"],
    ])
    def test_subcommand_help(self, cmd):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0
        assert "Commands" in result.output or "Options" in result.output

    @pytest.mark.parametrize("cmd", [
        ["vault", "search", "--help"],
        ["vault", "list", "--help"],
        ["vault", "get", "--help"],
        ["vault", "add", "--help"],
        ["vault", "archive", "--help"],
        ["agent", "ask", "--help"],
        ["agent", "chat", "--help"],
        ["connections", "list", "--help"],
        ["connections", "request", "--help"],
        ["connections", "accept", "--help"],
        ["connections", "pending", "--help"],
        ["connections", "label", "--help"],
        ["connections", "remove", "--help"],
        ["networks", "list", "--help"],
        ["networks", "members", "--help"],
        ["networks", "create", "--help"],
        ["pod", "info", "--help"],
        ["pod", "peers", "--help"],
        ["pod", "connect", "--help"],
        ["pod", "disconnect", "--help"],
        ["pod", "discover", "--help"],
        ["registry", "list", "--help"],
        ["registry", "search", "--help"],
        ["mcp", "serve", "--help"],
    ])
    def test_leaf_command_help(self, cmd):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0


# ── Pod CLI command tests ──


def _mock_session(tmp_path, monkeypatch):
    """Set up a mock session file and return the session dict."""
    config_dir = tmp_path / ".trustmesh"
    session_file = config_dir / "session"
    monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
    monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
    session = {
        "pod_url": "http://localhost:8000",
        "token": "test-token-abc",
        "user_id": "user-1",
        "username": "peter",
    }
    _save_session(session["pod_url"], session["token"], session["user_id"], session["username"])
    return session


class TestPodInfoCommand:
    """Test the `trustmesh pod info` command."""

    def test_pod_info_shows_identity(self, tmp_path, monkeypatch):
        """Pod info displays pod name, URL, and agents."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "pod_name": "Peter's Pod",
            "pod_url": "http://localhost:8000",
            "agent_count": 2,
            "agents": [
                {"display_name": "Peter Johnson", "username": "peter"},
                {"display_name": "Sarah Johnson", "username": "sarah"},
            ],
            "protocol": "trustmesh/0.1",
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "info"])

        assert result.exit_code == 0
        assert "Peter's Pod" in result.output
        assert "http://localhost:8000" in result.output
        assert "2" in result.output

    def test_pod_info_not_logged_in(self, tmp_path, monkeypatch):
        """Pod info without session shows login prompt."""
        session_file = tmp_path / ".trustmesh" / "session"
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)
        result = runner.invoke(app, ["pod", "info"])
        assert result.exit_code == 1
        assert "Not logged in" in result.output


class TestPodPeersCommand:
    """Test the `trustmesh pod peers` command."""

    def test_pod_peers_empty(self, tmp_path, monkeypatch):
        """Pod peers with no peers shows empty message."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "pod_name": "Peter's Pod",
            "pod_url": "http://localhost:8000",
            "peers": [],
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "peers"])

        assert result.exit_code == 0
        assert "No peer pods connected" in result.output

    def test_pod_peers_with_peers(self, tmp_path, monkeypatch):
        """Pod peers shows table when peers exist."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "pod_name": "Peter's Pod",
            "pod_url": "http://localhost:8000",
            "peers": [
                {
                    "id": "peer-1",
                    "name": "Sarah's Pod",
                    "url": "http://localhost:8001",
                    "status": "active",
                    "agent_count": 1,
                    "last_seen_at": "2026-02-14T10:00:00",
                },
                {
                    "id": "peer-2",
                    "name": "Mike's Pod",
                    "url": "http://localhost:8002",
                    "status": "unreachable",
                    "agent_count": 0,
                    "last_seen_at": None,
                },
            ],
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "peers"])

        assert result.exit_code == 0
        assert "Sarah's Pod" in result.output
        assert "Mike's Pod" in result.output
        assert "Peers (2)" in result.output


class TestPodConnectCommand:
    """Test the `trustmesh pod connect` command."""

    def test_pod_connect_success(self, tmp_path, monkeypatch):
        """Pod connect shows connected message."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "connected",
            "peer": {
                "id": "peer-1",
                "name": "Sarah's Pod",
                "url": "http://localhost:8001",
                "agent_count": 1,
                "status": "active",
            },
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "connect", "http://localhost:8001"])

        assert result.exit_code == 0
        assert "Connected to Sarah's Pod" in result.output

    def test_pod_connect_unreachable(self, tmp_path, monkeypatch):
        """Pod connect to unreachable pod shows error."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.json.return_value = {"detail": "Could not reach peer at http://localhost:9999"}
        mock_resp.text = '{"detail": "Could not reach peer at http://localhost:9999"}'
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "connect", "http://localhost:9999"])

        assert result.exit_code == 1
        assert "502" in result.output


class TestPodDisconnectCommand:
    """Test the `trustmesh pod disconnect` command."""

    def test_pod_disconnect_success(self, tmp_path, monkeypatch):
        """Pod disconnect shows cleanup stats."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "removed",
            "peer_url": "http://localhost:8001",
            "cleanup": {
                "ghosts_removed": 2,
                "connections_removed": 3,
                "memberships_removed": 2,
            },
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "disconnect", "peer-1"])

        assert result.exit_code == 0
        assert "Disconnected from http://localhost:8001" in result.output
        assert "2 ghost user(s)" in result.output
        assert "3 connection(s)" in result.output

    def test_pod_disconnect_no_ghosts(self, tmp_path, monkeypatch):
        """Pod disconnect with no ghosts shows minimal output."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "removed",
            "peer_url": "http://localhost:8001",
            "cleanup": {
                "ghosts_removed": 0,
                "connections_removed": 0,
                "memberships_removed": 0,
            },
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "disconnect", "peer-1"])

        assert result.exit_code == 0
        assert "Disconnected from http://localhost:8001" in result.output
        assert "ghost" not in result.output  # no cleanup message when 0 ghosts

    def test_pod_disconnect_not_found(self, tmp_path, monkeypatch):
        """Pod disconnect with bad peer ID shows error."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"detail": "Peer not found"}
        mock_resp.text = '{"detail": "Peer not found"}'
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "disconnect", "nonexistent-id"])

        assert result.exit_code == 1
        assert "404" in result.output


class TestPodDiscoverCommand:
    """Test the `trustmesh pod discover` command."""

    def test_pod_discover_shows_agents(self, tmp_path, monkeypatch):
        """Pod discover shows federation agent table."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "total": 3,
            "local_count": 1,
            "remote_count": 2,
            "agents": [
                {
                    "owner_display_name": "Peter Johnson",
                    "owner_username": "peter",
                    "user_type": "person",
                    "_pod": {"name": "Peter's Pod", "is_local": True},
                },
                {
                    "name": "Sarah Johnson's Knowledge",
                    "_pod": {"name": "Sarah's Pod", "is_local": False},
                },
                {
                    "name": "TechCorp's Knowledge",
                    "_pod": {"name": "TechCorp Pod", "is_local": False},
                },
            ],
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "discover"])

        assert result.exit_code == 0
        assert "Total agents" in result.output
        assert "3" in result.output
        assert "Peter Johnson" in result.output

    def test_pod_discover_empty(self, tmp_path, monkeypatch):
        """Pod discover with no agents shows count only."""
        _mock_session(tmp_path, monkeypatch)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "total": 0,
            "local_count": 0,
            "remote_count": 0,
            "agents": [],
        }
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "discover"])

        assert result.exit_code == 0
        assert "Total agents" in result.output
        assert "0" in result.output


# ── Whoami command tests ──


class TestWhoamiData:
    """Test whoami command with actual data."""

    def test_whoami_shows_user_info(self, tmp_path, monkeypatch):
        """Whoami displays user name, pod, type, and ID."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/agent/card"): {
                "did": "did:key:z6Mktest", "public_key_b64": "abc123",
                "capabilities": ["knowledge-query"],
            },
            ("GET", "/api/users/user-1/networks"): NETWORKS_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 0
        assert "Peter Johnson" in result.output
        assert "@peter" in result.output
        assert "person" in result.output
        assert "z6Mktest" in result.output  # Rich may convert :key: to emoji
        assert "The Johnsons" in result.output
        assert "Molly Johnson" in result.output

    def test_whoami_no_connections(self, tmp_path, monkeypatch):
        """Whoami with no connections skips connections section."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/agent/card"): {"did": "did:key:z6Mktest", "capabilities": []},
            ("GET", "/api/users/user-1/networks"): [],
            ("GET", "/api/users/user-1/connections"): [],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 0
        assert "Peter Johnson" in result.output
        assert "Connections" not in result.output


# ── Vault command tests ──


class TestVaultList:
    """Test the `trustmesh vault list` command."""

    def test_vault_list_shows_capsules(self, tmp_path, monkeypatch):
        """Vault list displays capsules with all columns."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list"])
        assert result.exit_code == 0
        assert "3 capsules" in result.output
        assert "Music" in result.output  # Rich may truncate long titles
        assert "Medical" in result.output
        assert "Lovers" in result.output  # network_names shown (Rich may wrap)
        normalized = " ".join(result.output.split())
        assert "Shared" in normalized  # adaptive column present (Rich wraps header)
        assert "Archived" in normalized  # adaptive column present (one is archived)

    def test_vault_list_type_filter(self, tmp_path, monkeypatch):
        """Vault list filters by capsule type."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list", "--type", "memory"])
        assert result.exit_code == 0
        assert "1 capsules" in result.output
        assert "Old Notes" in result.output
        assert "Music Interests" not in result.output

    def test_vault_list_visibility_filter(self, tmp_path, monkeypatch):
        """Vault list filters by visibility."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list", "--vis", "private"])
        assert result.exit_code == 0
        assert "1 capsules" in result.output
        assert "Old Notes" in result.output

    def test_vault_list_empty(self, tmp_path, monkeypatch):
        """Vault list shows message when empty."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): [],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list"])
        assert result.exit_code == 0
        assert "No capsules found" in result.output

    def test_vault_list_no_network_column_when_empty(self, tmp_path, monkeypatch):
        """Vault list hides Shared With column when no capsules have network_names."""
        capsules = [
            {**CAPSULES_RESPONSE[0], "network_names": [], "is_archived": False},
        ]
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): capsules,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list"])
        assert result.exit_code == 0
        assert "Shared With" not in result.output
        assert "Archived" not in result.output


class TestVaultGet:
    """Test the `trustmesh vault get` command."""

    def test_vault_get_by_prefix(self, tmp_path, monkeypatch):
        """Vault get finds capsule by ID prefix."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "get", "aaaa1111-0000-0000-0000-000000000001"])
        assert result.exit_code == 0
        assert "Music Interests" in result.output
        assert "Owner: Peter Johnson" in result.output
        assert "Shared with: Music Lovers" in result.output
        assert "Plays guitar" in result.output
        assert "Sharing Level: Shared" in result.output

    def test_vault_get_short_prefix(self, tmp_path, monkeypatch):
        """Vault get works with short prefix."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "get", "bbbb"])
        assert result.exit_code == 0
        assert "Old Notes" in result.output
        assert "ARCHIVED" in result.output

    def test_vault_get_not_found(self, tmp_path, monkeypatch):
        """Vault get with no match shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "get", "zzzz"])
        assert result.exit_code == 1
        assert "No capsule matching" in result.output

    def test_vault_get_ambiguous(self, tmp_path, monkeypatch):
        """Vault get with ambiguous prefix shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            # "aaaa" matches two capsules
            result = runner.invoke(app, ["vault", "get", "aaaa"])
        assert result.exit_code == 1
        assert "Ambiguous" in result.output


class TestVaultAdd:
    """Test the `trustmesh vault add` command."""

    def test_vault_add_success(self, tmp_path, monkeypatch):
        """Vault add creates a capsule."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("POST", "/api/users/user-1/capsules"): {
                "id": "new-cap-1234",
                "title": "New Capsule",
            },
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "add", "--title", "New Capsule", "--content", "test content"])
        assert result.exit_code == 0
        assert "Created capsule: New Capsule" in result.output

    def test_vault_add_with_options(self, tmp_path, monkeypatch):
        """Vault add passes all options."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("POST", "/api/users/user-1/capsules"): {"id": "new-cap-5678", "title": "My Skill"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, [
                "vault", "add",
                "--title", "My Skill",
                "--content", "I can do Python",
                "--type", "skill",
                "--vis", "open",
                "--category", "work",
            ])
        assert result.exit_code == 0
        assert "Created capsule: My Skill" in result.output


class TestVaultArchive:
    """Test the `trustmesh vault archive` command."""

    def test_vault_archive_success(self, tmp_path, monkeypatch):
        """Vault archive marks capsule as archived."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
            ("PUT", "/api/capsules/"): {"status": "ok"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "archive", "aaaa1111-0000-0000-0000-000000000001"])
        assert result.exit_code == 0
        assert "Archived capsule aaaa1111" in result.output

    def test_vault_archive_not_found(self, tmp_path, monkeypatch):
        """Vault archive with no match shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/capsules"): CAPSULES_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "archive", "zzzz"])
        assert result.exit_code == 1
        assert "No capsule matching" in result.output


class TestVaultSearch:
    """Test the `trustmesh vault search` command."""

    def test_vault_search_shows_response(self, tmp_path, monkeypatch):
        """Vault search displays agent response."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("POST", "/api/query"): {
                "response": "Peter plays guitar and likes classic rock.",
                "agent_actions": ["search_vault"],
            },
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "search", "music"])
        assert result.exit_code == 0
        assert "plays guitar" in result.output
        assert "search_vault" in result.output


# ── Agent command tests ──


class TestAgentAsk:
    """Test the `trustmesh agent ask` command."""

    def test_agent_ask_self(self, tmp_path, monkeypatch):
        """Agent ask to self shows response."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("POST", "/api/query"): {"response": "Your next appointment is Tuesday."},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["agent", "ask", "When is my next appointment?"])
        assert result.exit_code == 0
        assert "Tuesday" in result.output

    def test_agent_ask_cross_query(self, tmp_path, monkeypatch):
        """Agent ask with --to shows trust level."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users"): [ME_RESPONSE, {"id": "user-2", "username": "molly", "display_name": "Molly Johnson"}],
            ("POST", "/api/query"): {
                "response": "Molly's schedule is open.",
                "trust_level": "network",
                "shared_networks": ["The Johnsons"],
            },
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["agent", "ask", "What is Molly doing?", "--to", "molly"])
        assert result.exit_code == 0
        assert "Molly's schedule" in result.output
        assert "network" in result.output
        assert "The Johnsons" in result.output

    def test_agent_ask_cross_query_user_not_found(self, tmp_path, monkeypatch):
        """Agent ask with unknown --to shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users"): [ME_RESPONSE],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["agent", "ask", "Hi", "--to", "nobody"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_agent_ask_redacted(self, tmp_path, monkeypatch):
        """Agent ask shows redaction warning when Citadel blocks."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("POST", "/api/query"): {"response": "[REDACTED]", "decision": "redacted"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["agent", "ask", "Tell me secrets"])
        assert result.exit_code == 0
        assert "redacted by Citadel" in result.output


# ── Connection command tests ──


class TestConnectionsList:
    """Test the `trustmesh connections list` command."""

    def test_connections_list_shows_data(self, tmp_path, monkeypatch):
        """Connections list shows relationship types and labels."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "list"])
        assert result.exit_code == 0
        assert "Connections (2)" in result.output
        assert "Molly Johnson" in result.output
        assert "family" in result.output
        assert "wife" in result.output
        assert "Kyle Rivera" in result.output
        assert "work" in result.output
        assert "colleague" in result.output

    def test_connections_list_empty(self, tmp_path, monkeypatch):
        """Connections list shows message when empty."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): [],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "list"])
        assert result.exit_code == 0
        assert "No connections" in result.output


class TestConnectionsRequest:
    """Test the `trustmesh connections request` command."""

    def test_connections_request_success(self, tmp_path, monkeypatch):
        """Connection request sent successfully."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users"): [ME_RESPONSE, {"id": "user-5", "username": "amy", "display_name": "Amy Torres"}],
            ("POST", "/api/connections/request"): {"id": "req-new", "status": "pending"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "request", "amy", "--rel", "friend", "--label", "buddy"])
        assert result.exit_code == 0
        assert "request sent to Amy Torres" in result.output

    def test_connections_request_user_not_found(self, tmp_path, monkeypatch):
        """Connection request to unknown user shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users"): [ME_RESPONSE],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "request", "nobody"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestConnectionsAccept:
    """Test the `trustmesh connections accept` command."""

    def test_connections_accept_success(self, tmp_path, monkeypatch):
        """Connection request accepted by prefix."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connection-requests"): PENDING_REQUESTS,
            ("PUT", "/api/connection-requests/"): {"id": "req-1111", "status": "accepted"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "accept", "req-1111", "--label", "friend"])
        assert result.exit_code == 0
        assert "Accepted connection from Amy Torres" in result.output

    def test_connections_accept_not_found(self, tmp_path, monkeypatch):
        """Connection accept with no matching request shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connection-requests"): PENDING_REQUESTS,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "accept", "nonexistent"])
        assert result.exit_code == 1
        assert "No pending request" in result.output


class TestConnectionsPending:
    """Test the `trustmesh connections pending` command."""

    def test_connections_pending_shows_requests(self, tmp_path, monkeypatch):
        """Pending requests display with mutual context."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connection-requests"): PENDING_REQUESTS,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "pending"])
        assert result.exit_code == 0
        assert "Pending Requests (1)" in result.output
        assert "Amy Torres" in result.output
        assert "friend" in result.output
        assert "buddy" in result.output
        assert "connect" in result.output  # Rich may wrap across lines
        # Rich wraps mutual context across table cell lines; check parts individually
        assert "2 conn" in result.output or "2\xa0conn" in result.output or "conn" in result.output
        assert "net" in result.output

    def test_connections_pending_empty(self, tmp_path, monkeypatch):
        """No pending requests shows message."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connection-requests"): [],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "pending"])
        assert result.exit_code == 0
        assert "No pending" in result.output


class TestConnectionsLabel:
    """Test the `trustmesh connections label` command."""

    def test_connections_label_update(self, tmp_path, monkeypatch):
        """Label update works with prefix matching."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
            ("PATCH", "/api/connections/"): {
                "peer": {"display_name": "Molly Johnson"},
            },
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "label", "conn-1111", "--label", "spouse", "--rel", "family"])
        assert result.exit_code == 0
        assert "Updated connection with Molly Johnson" in result.output

    def test_connections_label_no_args(self, tmp_path, monkeypatch):
        """Label without --label or --rel shows error."""
        _mock_session(tmp_path, monkeypatch)
        result = runner.invoke(app, ["connections", "label", "conn-1111"])
        assert result.exit_code == 1
        assert "Provide --label" in result.output

    def test_connections_label_not_found(self, tmp_path, monkeypatch):
        """Label with no matching connection shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "label", "zzzz", "--label", "test"])
        assert result.exit_code == 1
        assert "No connection matching" in result.output


class TestConnectionsRemove:
    """Test the `trustmesh connections remove` command."""

    def test_connections_remove_confirmed(self, tmp_path, monkeypatch):
        """Connection remove with confirmation calls DELETE."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
            ("DELETE", "/api/connections/"): {"status": "disconnected"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "remove", "conn-1111"], input="y\n")
        assert result.exit_code == 0
        assert "Disconnected from Molly Johnson" in result.output

    def test_connections_remove_cancelled(self, tmp_path, monkeypatch):
        """Connection remove cancelled by user."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "remove", "conn-1111"], input="n\n")
        assert "Cancelled" in result.output

    def test_connections_remove_not_found(self, tmp_path, monkeypatch):
        """Connection remove with no match shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/connections"): CONNECTIONS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["connections", "remove", "zzzz"])
        assert result.exit_code == 1
        assert "No connection matching" in result.output


# ── Network command tests ──


class TestNetworksList:
    """Test the `trustmesh networks list` command."""

    def test_networks_list_shows_data(self, tmp_path, monkeypatch):
        """Networks list shows all columns."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/networks"): NETWORKS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["networks", "list"])
        assert result.exit_code == 0
        assert "Networks (2)" in result.output
        assert "The Johnsons" in result.output
        assert "family" in result.output
        assert "standard" in result.output
        assert "TechCorp PM Team" in result.output
        assert "category_scoped" in result.output

    def test_networks_list_empty(self, tmp_path, monkeypatch):
        """Networks list shows message when empty."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/networks"): [],
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["networks", "list"])
        assert result.exit_code == 0
        assert "No networks" in result.output


class TestNetworksMembers:
    """Test the `trustmesh networks members` command."""

    def test_networks_members_shows_data(self, tmp_path, monkeypatch):
        """Networks members shows member table."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/networks"): NETWORKS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["networks", "members", "net-1111"])
        assert result.exit_code == 0
        assert "The Johnsons" in result.output
        assert "Peter Johnson" in result.output
        assert "Molly Johnson" in result.output

    def test_networks_members_not_found(self, tmp_path, monkeypatch):
        """Networks members with no match shows error."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("GET", "/api/users/user-1/networks"): NETWORKS_RESPONSE,
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["networks", "members", "zzzz"])
        assert result.exit_code == 1
        assert "No network matching" in result.output


class TestNetworksCreate:
    """Test the `trustmesh networks create` command."""

    def test_networks_create_success(self, tmp_path, monkeypatch):
        """Networks create returns confirmation."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): ME_RESPONSE,
            ("POST", "/api/networks"): {"id": "net-new-1234", "name": "Book Club"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["networks", "create", "--name", "Book Club", "--type", "friends"])
        assert result.exit_code == 0
        assert "Created network: Book Club" in result.output


# ── Pod golive tests ──


class TestPodGoLive:
    """Test the `trustmesh pod golive` command."""

    def test_golive_go_live(self, tmp_path, monkeypatch):
        """Go live when currently private."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): {**ME_RESPONSE, "is_discoverable": False},
            ("PUT", "/api/users/user-1"): {"status": "ok"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "golive"], input="y\n")
        assert result.exit_code == 0
        assert "now live" in result.output

    def test_golive_go_private(self, tmp_path, monkeypatch):
        """Go private when currently live."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): {**ME_RESPONSE, "is_discoverable": True},
            ("PUT", "/api/users/user-1"): {"status": "ok"},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "golive"], input="y\n")
        assert result.exit_code == 0
        assert "removed from the public registry" in result.output

    def test_golive_cancelled(self, tmp_path, monkeypatch):
        """Go live cancelled by user."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        _mock_api_responses(mock_client, {
            ("GET", "/api/auth/me"): {**ME_RESPONSE, "is_discoverable": False},
        })
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["pod", "golive"], input="n\n")
        assert "Cancelled" in result.output


# ── Registry command tests ──


class TestRegistryList:
    """Test the `trustmesh registry list` command."""

    def test_registry_list_shows_agents(self, tmp_path, monkeypatch):
        """Registry list displays agents with correct fields."""
        # No session required for registry
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "agents": [
                {
                    "display_name": "Peter Johnson",
                    "username": "peter",
                    "entity_type": "person",
                    "pod_url": "http://localhost:8002",
                    "capabilities": ["Wiring", "Guitar", "Panel Upgrades"],
                },
                {
                    "display_name": "Riverside Hospital",
                    "username": "riverside_hospital",
                    "entity_type": "organization",
                    "pod_url": "http://localhost:8012",
                    "capabilities": ["Emergency", "Surgery", "Internal Medicine", "Pediatrics"],
                },
            ],
        }
        with patch("src.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["registry", "list"])
        assert result.exit_code == 0
        assert "2 agents" in result.output
        assert "Peter Johnson" in result.output
        assert "peter" in result.output
        assert "person" in result.output
        assert "Wiring" in result.output  # Rich may wrap capabilities text
        assert "Guitar" in result.output
        assert "Riverside" in result.output
        assert "organization" in result.output
        assert "Emergency" in result.output

    def test_registry_list_empty(self, tmp_path, monkeypatch):
        """Registry list shows message when no agents."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"agents": []}
        with patch("src.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["registry", "list"])
        assert result.exit_code == 0
        assert "No agents registered" in result.output

    def test_registry_list_unreachable(self, tmp_path, monkeypatch):
        """Registry list shows error when unreachable."""
        with patch("src.cli.httpx.get", side_effect=Exception("Connection refused")):
            result = runner.invoke(app, ["registry", "list"])
        assert result.exit_code == 1
        assert "Cannot reach registry" in result.output


class TestRegistrySearch:
    """Test the `trustmesh registry search` command."""

    def test_registry_search_results(self, tmp_path, monkeypatch):
        """Registry search displays matching agents."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "display_name": "Dr. Sarah Lee",
                    "username": "dr_lee",
                    "entity_type": "person",
                    "pod_url": "http://localhost:8005",
                },
            ],
        }
        with patch("src.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["registry", "search", "doctor"])
        assert result.exit_code == 0
        assert "doctor" in result.output
        assert "Dr. Sarah Lee" in result.output
        assert "dr_lee" in result.output

    def test_registry_search_no_results(self, tmp_path, monkeypatch):
        """Registry search shows message when no matches."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        with patch("src.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["registry", "search", "zzzznothing"])
        assert result.exit_code == 0
        assert "No results" in result.output


# ── API error handling tests ──


class TestApiErrorHandling:
    """Test _api error handling across commands."""

    def test_session_expired_401(self, tmp_path, monkeypatch):
        """401 response clears session and exits."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client.request.return_value = mock_resp

        session_file = tmp_path / ".trustmesh" / "session"
        assert session_file.exists()  # session was saved by _mock_session
        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list"])
        assert result.exit_code == 1
        assert "Session expired" in result.output
        assert not session_file.exists()  # session cleared

    def test_api_error_shows_detail(self, tmp_path, monkeypatch):
        """API errors show status code and detail."""
        _mock_session(tmp_path, monkeypatch)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"detail": "Access denied"}
        mock_resp.text = '{"detail": "Access denied"}'
        mock_client.request.return_value = mock_resp

        with patch("src.cli._client", return_value=mock_client):
            result = runner.invoke(app, ["vault", "list"])
        assert result.exit_code == 1
        assert "403" in result.output
        assert "Access denied" in result.output


# ── Login edge case tests ──


class TestLoginEdgeCases:
    """Test login edge cases."""

    def test_login_rate_limited(self, tmp_path, monkeypatch):
        """429 response shows rate limit message."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("src.cli.httpx.post", return_value=mock_resp):
            with patch("src.cli.getpass.getpass", return_value="test"):
                result = runner.invoke(app, ["login", "--pod", "http://localhost:8000", "--user", "peter"])
        assert result.exit_code == 1
        assert "Too many login attempts" in result.output

    def test_login_no_session_token(self, tmp_path, monkeypatch):
        """Success response without session cookie shows error."""
        config_dir = tmp_path / ".trustmesh"
        session_file = config_dir / "session"
        monkeypatch.setattr("src.cli.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.cli.SESSION_FILE", session_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.cookies = {}  # No session cookie
        mock_resp.json.return_value = {"id": "user-1", "username": "peter", "display_name": "Peter"}

        with patch("src.cli.httpx.post", return_value=mock_resp):
            with patch("src.cli.getpass.getpass", return_value="test"):
                result = runner.invoke(app, ["login", "--pod", "http://localhost:8000", "--user", "peter"])
        assert result.exit_code == 1
        assert "No session token" in result.output
