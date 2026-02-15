"""Tests for TrustMesh CLI — session management, commands, and MCP server creation."""

import asyncio
import json
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
        assert "Invalid username or password" in result.output
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
                    "display_name": "Peter Johnson",
                    "username": "peter",
                    "user_type": "person",
                    "_pod": {"name": "Peter's Pod", "is_local": True},
                },
                {
                    "display_name": "Sarah Johnson",
                    "username": "sarah",
                    "user_type": "person",
                    "_pod": {"name": "Sarah's Pod", "is_local": False},
                },
                {
                    "display_name": "TechCorp",
                    "username": "techcorp",
                    "user_type": "organization",
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
