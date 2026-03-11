"""TrustMesh MCP Server — expose TrustMesh tools via Model Context Protocol.

Session-authenticated: reads ~/.trustmesh/session (created by `trustmesh login`).
Falls back to unauthenticated mode using TRUSTMESH_API_URL if no session exists.

Run standalone (stdio transport, for Claude Desktop / Cursor / Claude Code):
    cd trustmesh-core && uv run python -m src.mcp_server

Via CLI:
    trustmesh mcp serve

Add to Claude Desktop config:
    {
      "mcpServers": {
        "trustmesh": {
          "command": "uv",
          "args": ["--directory", "/path/to/trustmesh-core", "run", "trustmesh", "mcp", "serve"]
        }
      }
    }
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx
from mcp.server.fastmcp import FastMCP


# ── Session management ──

SESSION_FILE = Path.home() / ".trustmesh" / "session"


def _load_session() -> dict | None:
    """Load session from env var (channel token) or ~/.trustmesh/session (CLI)."""
    # TRUSTMESH_TOKEN: Bearer channel token for ZeroClaw/NullClaw integration
    token = os.getenv("TRUSTMESH_TOKEN")
    if token:
        return {
            "pod_url": os.getenv("TRUSTMESH_API_URL", "http://localhost:9000"),
            "token": token,
            "auth_type": "bearer",
        }

    # Fall back to session file (created by `trustmesh login`)
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        if "pod_url" in data and "token" in data:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _make_client(session: dict | None) -> httpx.Client:
    """Create httpx client, with Bearer token or session cookie if available."""
    if session:
        auth_type = session.get("auth_type", "cookie")
        if auth_type == "bearer":
            return httpx.Client(
                base_url=session["pod_url"],
                headers={"Authorization": f"Bearer {session['token']}"},
                timeout=60.0,
            )
        return httpx.Client(
            base_url=session["pod_url"],
            cookies={"trustmesh_session": session["token"]},
            timeout=60.0,
        )
    # Fallback: no auth, use env var
    base = os.getenv("TRUSTMESH_API_URL", "http://localhost:9000")
    return httpx.Client(base_url=base, timeout=60.0)


def _api(session: dict | None, method: str, path: str, **kwargs) -> dict | list:
    """Make an API call, return parsed JSON."""
    with _make_client(session) as client:
        resp = client.request(method, path, **kwargs)
    if resp.status_code == 401:
        raise RuntimeError("Session expired. Run `trustmesh login` to re-authenticate.")
    resp.raise_for_status()
    return resp.json()


def _get_me(session: dict | None) -> dict:
    """Get current user info. Requires session."""
    if not session:
        raise RuntimeError("Not logged in. Run `trustmesh login` first.")
    return _api(session, "GET", "/api/auth/me")


# ── Server factory ──

def _get_session(explicit: dict | None = None) -> dict | None:
    """Get session, re-reading from disk to pick up login changes."""
    if explicit is not None:
        return explicit
    return _load_session()


def create_mcp_server(session: dict | None = None) -> FastMCP:
    """Create a FastMCP server, optionally bound to a TrustMesh session.

    If session is None, attempts to load from ~/.trustmesh/session on each call.
    Unauthenticated tools (pod info, health, registry) work without a session.
    Authenticated tools (vault, agent, connections) require a session.
    """
    # Store explicit session if provided; otherwise re-read from disk each call
    _explicit_session = session

    def _s():
        """Get fresh session, re-reading from disk to pick up login changes."""
        return _get_session(_explicit_session)

    mcp = FastMCP(
        "TrustMesh",
        instructions=(
            "TrustMesh is a trust-aware knowledge sharing platform for personal AI agents. "
            "Use these tools to search your vault, save knowledge, query agents, "
            "and explore your trust network. All operations respect trust boundaries. "
            "Vault and agent tools require authentication via `trustmesh login`."
        ),
    )

    # ── Authenticated Tools (require session) ──

    @mcp.tool()
    def search_vault(query: str) -> str:
        """Search your knowledge vault for capsules matching a query.

        Uses semantic search + AI agent to find and summarize relevant knowledge
        from your encrypted vault. Self-query with full private access.
        """
        me = _get_me(_s())
        result = _api(_s(),"POST", "/api/query", json={
            "from_user_id": me["id"],
            "to_user_id": me["id"],
            "question": query,
        })
        response_text = result.get("response", "No results found.")
        actions = result.get("agent_actions", [])
        parts = [response_text]
        if actions:
            parts.append(f"\nAgent actions: {json.dumps(actions)}")
        return "\n".join(parts)

    @mcp.tool()
    def save_to_vault(
        title: str,
        content: str,
        capsule_type: str = "memory",
        visibility: str = "private",
        category: str | None = None,
    ) -> str:
        """Save new knowledge to your vault as an encrypted capsule.

        Args:
            title: Title for the knowledge capsule
            content: The knowledge content to save
            capsule_type: Type (memory, note, document, preference, health, financial, legal)
            visibility: private (only you), internal (trusted connections), open (anyone)
            category: Optional tag (health, work, personal, finance, etc.)
        """
        me = _get_me(_s())
        payload = {
            "capsule_type": capsule_type,
            "title": title,
            "content": content,
            "visibility": visibility,
        }
        if category:
            payload["category"] = category
        result = _api(_s(),"POST", f"/api/users/{me['id']}/capsules", json=payload)
        return f"Saved: {result['title']} (ID: {result['id'][:8]}, visibility: {result['visibility']})"

    @mcp.tool()
    def list_capsules(capsule_type: str | None = None, visibility: str | None = None) -> str:
        """List knowledge capsules in your vault.

        Args:
            capsule_type: Filter by type (memory, note, document, preference, health, etc.)
            visibility: Filter by visibility (private, internal, open)
        """
        me = _get_me(_s())
        capsules = _api(_s(),"GET", f"/api/users/{me['id']}/capsules")
        if capsule_type:
            capsules = [c for c in capsules if c.get("capsule_type") == capsule_type]
        if visibility:
            capsules = [c for c in capsules if c.get("visibility") == visibility]

        if not capsules:
            return "No capsules found."

        lines = [f"Found {len(capsules)} capsules:\n"]
        for c in capsules:
            archived = " [ARCHIVED]" if c.get("is_archived") else ""
            lines.append(
                f"- {c['title']} ({c.get('capsule_type', '?')}, {c.get('visibility', '?')}){archived}"
                f"\n  ID: {c['id'][:8]}  Category: {c.get('category', 'none')}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def ask_agent(question: str, target_user: str | None = None) -> str:
        """Ask your AI agent a question, or cross-query another user's agent.

        Self-queries have full vault access. Cross-queries are trust-filtered:
        only knowledge matching your trust level is accessible.

        Args:
            question: The question to ask
            target_user: Username to cross-query (omit for self-query)
        """
        me = _get_me(_s())

        if target_user:
            users = _api(_s(),"GET", "/api/users")
            target = next((u for u in users if u["username"] == target_user), None)
            if not target:
                return f"User '{target_user}' not found."
            to_user_id = target["id"]
        else:
            to_user_id = me["id"]

        result = _api(_s(),"POST", "/api/query", json={
            "from_user_id": me["id"],
            "to_user_id": to_user_id,
            "question": question,
        })

        parts = []
        if target_user:
            parts.append(f"Trust level: {result.get('trust_level', '?')}")
            networks = result.get("shared_networks", [])
            if networks:
                parts.append(f"Shared networks: {', '.join(networks)}")

        parts.append(result.get("response", "No response"))

        if result.get("decision") == "redacted":
            parts.append("\n[REDACTED by Citadel security scan]")

        return "\n".join(parts)

    @mcp.tool()
    def list_connections() -> str:
        """List your trust connections with their status and user types."""
        me = _get_me(_s())
        connections = _api(_s(),"GET", f"/api/users/{me['id']}/connections")

        if not connections:
            return "No connections."

        lines = [f"You have {len(connections)} connections:\n"]
        for c in connections:
            peer = c.get("peer", {})
            since = c.get("accepted_at", "")[:10] if c.get("accepted_at") else "?"
            lines.append(
                f"- {peer.get('display_name', '?')} (@{peer.get('username', '?')}) "
                f"[{peer.get('user_type', 'person')}] since {since}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def list_networks() -> str:
        """List your trust networks/pools with member counts."""
        me = _get_me(_s())
        networks = _api(_s(),"GET", f"/api/users/{me['id']}/networks")

        if not networks:
            return "No networks."

        lines = [f"You belong to {len(networks)} networks:\n"]
        for n in networks:
            members = n.get("members", [])
            member_names = [m.get("display_name", "?") for m in members]
            lines.append(
                f"- {n['name']} ({n.get('pool_type', 'standard')}, {len(members)} members)"
                f"\n  Members: {', '.join(member_names)}"
            )
        return "\n".join(lines)

    # ── Memory API Tools (via Zig HTTP server) ──

    @mcp.tool()
    def memory_store(
        content: str,
        title: str = "Untitled",
        category: str = "general",
        visibility: str = "private",
    ) -> str:
        """Store a memory capsule directly via the Memory API (Zig fast path).

        Simpler than save_to_vault — goes through the Zig HTTP server's
        /api/memory/store endpoint for minimal-latency writes.

        Args:
            content: The knowledge content to store
            title: Short title for the memory
            category: Category tag (health, work, personal, finance, etc.)
            visibility: private (only you), internal (trusted), open (anyone)
        """
        result = _api(_s(), "POST", "/api/memory/store", json={
            "content": content,
            "title": title,
            "category": category,
            "visibility": visibility,
        })
        return f"Stored: {result.get('id', '?')[:8]} ({result.get('status', 'unknown')})"

    @mcp.tool()
    def memory_recall(query: str, top_k: int = 5) -> str:
        """Recall memories matching a query via FTS5 search (Zig fast path).

        Uses the Zig HTTP server's /api/memory/recall endpoint for
        trust-filtered full-text search with Porter stemming.

        Args:
            query: Search query (supports natural language)
            top_k: Maximum number of results to return
        """
        result = _api(_s(), "POST", "/api/memory/recall", json={
            "query": query,
            "top_k": top_k,
        })
        results = result.get("results", [])
        if not results:
            return "No memories found."
        lines = [f"Found {len(results)} result(s):\n"]
        for r in results:
            lines.append(f"- {r.get('title', '?')} [{r.get('category', '?')}]")
            content = r.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"  {content}\n")
        return "\n".join(lines)

    @mcp.tool()
    def init_pod(username: str, password: str, display_name: str = "", user_type: str = "person") -> str:
        """Initialize a new TrustMesh pod with the first user account.

        Creates user + agent + ed25519 DID + encrypted vault. Only works
        on a running pod that hasn't been initialized yet.

        Args:
            username: Username (2-32 chars, alphanumeric)
            password: Password (12+ chars, upper + lower + digit)
            display_name: Human-readable name (optional, defaults to username)
            user_type: Entity type (person, organization, government)
        """
        payload = {
            "username": username,
            "password": password,
            "user_type": user_type,
        }
        if display_name:
            payload["display_name"] = display_name

        result = _api(_s(), "POST", "/api/onboard/init", json=payload)
        return (
            f"Pod initialized!\n"
            f"  User: {result.get('username', '?')}\n"
            f"  DID: {result.get('did', '?')}\n"
            f"  User ID: {result.get('user_id', '?')[:8]}..."
        )

    # ── Public Tools (work without session) ──

    @mcp.tool()
    def pod_status() -> str:
        """Get current pod health, providers, agents, and peer information."""
        health = _api(_s(),"GET", "/health/full")
        pod_info = _api(_s(),"GET", "/api/pod")
        peers_data = _api(_s(),"GET", "/api/pod/peers")

        parts = [
            f"Pod: {pod_info.get('pod_name', '?')} ({pod_info.get('pod_url', '')})",
            f"Health: {health.get('status', 'unknown')}",
            f"Agents: {pod_info.get('agent_count', 0)}",
        ]

        providers = health.get("providers", {})
        if providers:
            prov_lines = []
            for name, val in providers.items():
                if isinstance(val, bool):
                    prov_lines.append(f"  {name}: {'ON' if val else 'off'}")
                elif isinstance(val, dict):
                    active = val.get("reachable") or val.get("enabled") or val.get("active")
                    prov_lines.append(f"  {name}: {'ON' if active else 'off'}")
            parts.append("Providers:\n" + "\n".join(prov_lines))

        peers = peers_data.get("peers", [])
        if peers:
            peer_lines = [
                f"  {p.get('name', '?')} ({p.get('url', '')}) [{p.get('status', '?')}]"
                for p in peers
            ]
            parts.append(f"Peers ({len(peers)}):\n" + "\n".join(peer_lines))
        else:
            parts.append("Peers: none")

        return "\n".join(parts)

    @mcp.tool()
    def discover_agents(query: str = "", capability: str = "", user_type: str = "") -> str:
        """Discover agents on the pod or search the public registry.

        Args:
            query: Search by name or keyword
            capability: Filter by capability/skill
            user_type: Filter by type (person, organization, government)
        """
        # Try local registry first
        params = {}
        if query:
            params["q"] = query
        if capability:
            params["capability"] = capability
        if user_type:
            params["user_type"] = user_type

        qs = "&".join(f"{k}={v}" for k, v in params.items())
        path = f"/api/registry/search?{qs}" if qs else "/api/registry/agents"

        try:
            result = _api(_s(),"GET", path)
        except Exception:
            # Fallback to external registry
            registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:9100")
            try:
                resp = httpx.get(f"{registry_url}/api/search", params={"q": query or ""}, timeout=10)
                result = resp.json()
            except Exception:
                return f"Cannot reach registry."

        agents = result.get("results", result.get("agents", result if isinstance(result, list) else []))
        if not agents:
            return "No agents found."

        lines = [f"Found {len(agents)} agent(s):\n"]
        for a in agents:
            skills = ", ".join(s.get("name", "") for s in a.get("skills", []))
            pools = ", ".join(a.get("pools", []))
            lines.append(f"- {a.get('display_name', '?')} (@{a.get('username', '?')}, {a.get('user_type', '?')})")
            if a.get("bio"):
                lines.append(f"  {a['bio']}")
            if skills:
                lines.append(f"  Skills: {skills}")
            if pools:
                lines.append(f"  Networks: {pools}")
            if a.get("did"):
                lines.append(f"  DID: {a['did']}")
            lines.append("")
        return "\n".join(lines)

    @mcp.tool()
    def health_check() -> str:
        """Check the health status of the TrustMesh pod and its providers."""
        result = _api(_s(),"GET", "/health/full")
        providers = result.get("providers", {})

        lines = [f"Status: {result.get('status', 'unknown')}\n"]
        for name, info in providers.items():
            if isinstance(info, bool):
                lines.append(f"- {name}: {'active' if info else 'inactive'}")
            elif isinstance(info, dict):
                active = info.get("enabled", info.get("reachable", info.get("active", False)))
                detail = info.get("provider", "")
                status = "active" if active else "inactive"
                if detail:
                    status += f" ({detail})"
                lines.append(f"- {name}: {status}")
        return "\n".join(lines)

    # ── Resources ──

    @mcp.resource("trustmesh://profile")
    def get_profile() -> str:
        """Your TrustMesh profile: name, type, networks, and connection summary."""
        if not _s():
            return "Not logged in. Run `trustmesh login` first."
        me = _get_me(_s())
        connections = _api(_s(),"GET", f"/api/users/{me['id']}/connections")
        networks = _api(_s(),"GET", f"/api/users/{me['id']}/networks")

        parts = [
            f"User: {me['display_name']} (@{me['username']})",
            f"Type: {me.get('user_type', 'person')}",
            f"Pod: {_s()['pod_url']}",
            f"Connections: {len(connections)}",
            f"Networks: {len(networks)}",
        ]
        if networks:
            parts.append("\nNetworks:")
            for n in networks:
                parts.append(f"  - {n['name']} ({len(n.get('members', []))} members)")
        if me.get("bio"):
            parts.append(f"\nBio: {me['bio']}")
        return "\n".join(parts)

    @mcp.resource("trustmesh://vault/summary")
    def get_vault_summary() -> str:
        """Summary of your knowledge vault: capsule counts by type and visibility."""
        if not _s():
            return "Not logged in. Run `trustmesh login` first."
        me = _get_me(_s())
        capsules = _api(_s(),"GET", f"/api/users/{me['id']}/capsules")

        by_type: dict[str, int] = {}
        by_vis: dict[str, int] = {}
        archived = 0
        for c in capsules:
            t = c.get("capsule_type", "unknown")
            v = c.get("visibility", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            by_vis[v] = by_vis.get(v, 0) + 1
            if c.get("is_archived"):
                archived += 1

        parts = [f"Vault: {len(capsules)} capsules ({archived} archived)\n"]
        if by_type:
            parts.append("By type:")
            for t, count in sorted(by_type.items()):
                parts.append(f"  {t}: {count}")
        if by_vis:
            parts.append("By visibility:")
            for v, count in sorted(by_vis.items()):
                parts.append(f"  {v}: {count}")
        return "\n".join(parts)

    @mcp.resource("trustmesh://pod/info")
    def pod_info_resource() -> str:
        """Current pod identity, agents, and configuration."""
        return json.dumps(_api(_s(),"GET", "/api/pod"), indent=2)

    return mcp


# ── Entry Points ──

# Module-level server for `mcp.run()` compatibility
# Pass None so session is re-read from disk on each tool call (picks up login changes)
mcp = create_mcp_server()


def main():
    """Run the TrustMesh MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
