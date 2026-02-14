"""TrustMesh MCP Server — expose TrustMesh tools via Model Context Protocol.

Run standalone (stdio transport, for Claude Code / MCP clients):
    cd trustmesh-core && uv run python -m src.mcp_server

Add to Claude Code config (~/.claude.json or project .mcp.json):
    {
      "mcpServers": {
        "trustmesh": {
          "command": "uv",
          "args": ["run", "python", "-m", "src.mcp_server"],
          "cwd": "/path/to/trustmesh-core"
        }
      }
    }

Requires TrustMesh backend running on TRUSTMESH_API_URL (default: http://localhost:8000).
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="TrustMesh",
    instructions="TrustMesh personal AI agent tools — search agents, query knowledge, manage capsules, and discover services on the pod.",
)

API_BASE = os.getenv("TRUSTMESH_API_URL", "http://localhost:8000")


async def _api_get(path: str) -> dict:
    """Make a GET request to the TrustMesh API."""
    import httpx
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()


async def _api_post(path: str, data: dict) -> dict:
    """Make a POST request to the TrustMesh API."""
    import httpx
    async with httpx.AsyncClient(base_url=API_BASE, timeout=60) as client:
        resp = await client.post(path, json=data)
        resp.raise_for_status()
        return resp.json()


# ── Tools ──


@mcp.tool()
async def discover_agents(
    query: str = "",
    capability: str = "",
    user_type: str = "",
) -> str:
    """Search for agents on the TrustMesh pod by name, capability, or type.

    Returns a list of discoverable agents with their skills, pools, and DID.
    Use this to find people, organizations, or government agents you can interact with.
    """
    params = {}
    if query:
        params["q"] = query
    if capability:
        params["capability"] = capability
    if user_type:
        params["user_type"] = user_type

    qs = "&".join(f"{k}={v}" for k, v in params.items())
    path = f"/api/registry/search?{qs}" if qs else "/api/registry/agents"
    result = await _api_get(path)

    agents = result.get("results", result.get("agents", []))
    if not agents:
        return "No agents found matching your criteria."

    lines = [f"Found {len(agents)} agent(s):\n"]
    for a in agents:
        skills = ", ".join(s.get("name", "") for s in a.get("skills", []))
        pools = ", ".join(a.get("pools", []))
        lines.append(f"- **{a['display_name']}** (@{a['username']}, {a['user_type']})")
        if a.get("bio"):
            lines.append(f"  {a['bio']}")
        if skills:
            lines.append(f"  Skills: {skills}")
        if pools:
            lines.append(f"  Networks: {pools}")
        lines.append(f"  DID: `{a['did']}`")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def query_agent(
    question: str,
    target_username: str,
    from_user_id: str = "",
    to_user_id: str = "",
) -> str:
    """Ask a question to a specific agent on the TrustMesh pod.

    The response is filtered by trust level — you'll only see information
    the target has made accessible to you based on your trust relationship.

    Args:
        question: The question to ask
        target_username: Username of the agent to query (e.g., "peter", "molly")
        from_user_id: Your user ID (if known)
        to_user_id: Target user ID (if known, otherwise target_username is used)
    """
    # If we have user IDs, use the direct query API
    if from_user_id and to_user_id:
        result = await _api_post("/api/query", {
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "question": question,
        })
        response = result.get("response", "No response received.")
        trust = result.get("trust_level", "unknown")
        decision = result.get("decision", "unknown")
        return f"**Trust Level**: {trust} | **Decision**: {decision}\n\n{response}"

    # Otherwise use A2A endpoint
    result = await _api_post("/api/pod/a2a", {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "mcp-query",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": question}],
            },
            "metadata": {"to_username": target_username},
        },
    })

    if "error" in result:
        return f"Error: {result['error'].get('message', 'Unknown error')}"

    task = result.get("result", {})
    status = task.get("status", {}).get("state", "unknown")
    trust_level = task.get("metadata", {}).get("trust_level", "unknown")

    # Extract response text from artifacts
    artifacts = task.get("artifacts", [])
    text = ""
    for artifact in artifacts:
        for part in artifact.get("parts", []):
            if part.get("type") == "text":
                text += part.get("text", "")

    if not text:
        text = f"Query {status}. No response text available."

    return f"**Trust Level**: {trust_level} | **Status**: {status}\n\n{text}"


@mcp.tool()
async def get_pod_info() -> str:
    """Get information about this TrustMesh pod — name, URL, protocol, and registered agents."""
    result = await _api_get("/api/pod")
    agents = result.get("agents", [])
    agent_list = ", ".join(a.get("owner_username", "?") for a in agents) if agents else "none"

    return (
        f"**Pod**: {result.get('pod_name', 'Unknown')}\n"
        f"**URL**: {result.get('pod_url', 'Unknown')}\n"
        f"**Protocol**: {result.get('protocol', 'Unknown')}\n"
        f"**Agents**: {result.get('agent_count', 0)} ({agent_list})"
    )


@mcp.tool()
async def lookup_agent(did: str) -> str:
    """Look up a specific agent by their DID (Decentralized Identifier).

    Returns detailed info about the agent including skills, pools, and pod location.
    """
    result = await _api_get(f"/api/registry/lookup/{did}")

    skills = ", ".join(s.get("name", "") for s in result.get("skills", []))
    pools = ", ".join(result.get("pools", []))
    pod = result.get("pod", {})

    lines = [
        f"**{result['display_name']}** (@{result['username']})",
        f"**Type**: {result['user_type']}",
        f"**DID**: `{result['did']}`",
    ]
    if result.get("bio"):
        lines.append(f"**Bio**: {result['bio']}")
    if skills:
        lines.append(f"**Skills**: {skills}")
    if pools:
        lines.append(f"**Networks**: {pools}")
    if pod:
        lines.append(f"**Pod**: {pod.get('name', '?')} ({pod.get('url', '?')})")

    return "\n".join(lines)


@mcp.tool()
async def list_services() -> str:
    """List available service providers (organizations, hospitals, etc.) on the pod."""
    result = await _api_get("/api/services")

    if not result:
        return "No service providers available."

    lines = [f"Found {len(result)} service provider(s):\n"]
    for sp in result:
        lines.append(f"- **{sp['display_name']}** ({sp['user_type']})")
        if sp.get("bio"):
            lines.append(f"  {sp['bio']}")
        card = sp.get("agent_card")
        if card and card.get("skills"):
            skill_names = ", ".join(s.get("name", "") for s in card["skills"][:5])
            lines.append(f"  Services: {skill_names}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def health_check() -> str:
    """Check the health status of the TrustMesh pod and its providers."""
    result = await _api_get("/health/full")
    providers = result.get("providers", {})

    lines = [f"**Status**: {result.get('status', 'unknown')}\n"]
    for name, info in providers.items():
        if isinstance(info, bool):
            status = "active" if info else "inactive"
            lines.append(f"- **{name}**: {status}")
        elif isinstance(info, dict):
            active = info.get("enabled", info.get("reachable", info.get("active", False)))
            detail = info.get("provider", "")
            status = "active" if active else "inactive"
            if detail:
                status += f" ({detail})"
            lines.append(f"- **{name}**: {status}")

    return "\n".join(lines)


# ── Resources ──


@mcp.resource("trustmesh://pod/info")
async def pod_info_resource() -> str:
    """Current pod identity and agent list."""
    return json.dumps(await _api_get("/api/pod"), indent=2)


@mcp.resource("trustmesh://registry/agents")
async def registry_agents_resource() -> str:
    """All discoverable agents on the pod."""
    return json.dumps(await _api_get("/api/registry/agents"), indent=2)


# ── Entry Point ──


def main():
    """Run the TrustMesh MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
