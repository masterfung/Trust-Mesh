"""TrustMesh CLI — power-user interface to TrustMesh pods.

Usage:
    trustmesh login --pod http://localhost:8000
    trustmesh status
    trustmesh vault search "allergies"
    trustmesh agent ask "What does Peter like to eat?"
    trustmesh mcp serve
"""

import getpass
import json
import os
import stat
import sys
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

# ── App setup ──

app = typer.Typer(
    name="trustmesh",
    help="TrustMesh CLI — trust-aware knowledge sharing for personal AI agents.",
    no_args_is_help=True,
)
vault_app = typer.Typer(help="Manage knowledge capsules in your vault.")
agent_app = typer.Typer(help="Interact with your AI agent.")
conn_app = typer.Typer(help="Manage trust connections.")
net_app = typer.Typer(help="Manage trust networks/pools.")
pod_app = typer.Typer(help="Pod federation management.")
reg_app = typer.Typer(help="Public registry operations.")
mcp_app = typer.Typer(help="MCP server for Claude Desktop / Cursor integration.")

app.add_typer(vault_app, name="vault")
app.add_typer(agent_app, name="agent")
app.add_typer(conn_app, name="connections")
app.add_typer(net_app, name="networks")
app.add_typer(pod_app, name="pod")
app.add_typer(reg_app, name="registry")
app.add_typer(mcp_app, name="mcp")

console = Console()

# ── Session management ──

CONFIG_DIR = Path.home() / ".trustmesh"
CONFIG_FILE = CONFIG_DIR / "config.toml"
SESSION_FILE = CONFIG_DIR / "session"


def _ensure_config_dir():
    """Create ~/.trustmesh/ with 0700 permissions."""
    CONFIG_DIR.mkdir(mode=0o700, exist_ok=True)


def _save_session(pod_url: str, token: str, user_id: str, username: str):
    """Store session token securely."""
    _ensure_config_dir()
    data = {"pod_url": pod_url, "token": token, "user_id": user_id, "username": username}
    SESSION_FILE.write_text(json.dumps(data))
    SESSION_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _load_session() -> dict | None:
    """Load session from disk. Returns None if no session."""
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        if "pod_url" in data and "token" in data:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _clear_session():
    """Delete session file."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def _client(session: dict | None = None) -> httpx.Client:
    """Create an httpx client with session cookie attached."""
    if session is None:
        session = _load_session()
    if not session:
        console.print("[red]Not logged in. Run: trustmesh login[/red]")
        raise typer.Exit(1)
    return httpx.Client(
        base_url=session["pod_url"],
        cookies={"trustmesh_session": session["token"]},
        timeout=120.0,
    )


def _require_session() -> dict:
    """Load session or exit with error."""
    session = _load_session()
    if not session:
        console.print("[red]Not logged in. Run: trustmesh login[/red]")
        raise typer.Exit(1)
    return session


def _api(method: str, path: str, session: dict | None = None, **kwargs) -> dict:
    """Make an API call, handle common errors."""
    s = session or _require_session()
    with _client(s) as client:
        resp = client.request(method, path, **kwargs)
    if resp.status_code == 401:
        console.print("[red]Session expired. Run: trustmesh login[/red]")
        _clear_session()
        raise typer.Exit(1)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        console.print(f"[red]Error {resp.status_code}: {detail}[/red]")
        raise typer.Exit(1)
    return resp.json()


# ── Auth commands ──

@app.command()
def login(
    pod: str = typer.Option("http://localhost:8000", "--pod", "-p", help="Pod URL"),
    user: str = typer.Option(None, "--user", "-u", help="Username"),
):
    """Authenticate with a TrustMesh pod."""
    if not user:
        user = typer.prompt("Username")
    password = getpass.getpass("Password: ")

    pod_url = pod.rstrip("/")
    try:
        resp = httpx.post(
            f"{pod_url}/api/auth/login",
            json={"username": user, "password": password},
            timeout=15.0,
        )
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to {pod_url}[/red]")
        raise typer.Exit(1)

    if resp.status_code == 401:
        console.print("[red]Invalid username or password[/red]")
        raise typer.Exit(1)
    if resp.status_code == 429:
        console.print("[red]Too many login attempts. Try again later.[/red]")
        raise typer.Exit(1)
    if resp.status_code >= 400:
        console.print(f"[red]Login failed: {resp.text}[/red]")
        raise typer.Exit(1)

    # Extract session token from Set-Cookie header
    token = resp.cookies.get("trustmesh_session")
    if not token:
        console.print("[red]No session token received[/red]")
        raise typer.Exit(1)

    user_data = resp.json()
    _save_session(pod_url, token, user_data["id"], user_data["username"])
    console.print(f"[green]Logged in as {user_data['display_name']} ({user_data['username']})[/green]")
    console.print(f"  Pod: {pod_url}")


@app.command()
def logout():
    """Clear session and log out."""
    session = _load_session()
    if session:
        try:
            with _client(session) as client:
                client.post("/api/auth/logout")
        except Exception:
            pass
    _clear_session()
    console.print("[green]Logged out.[/green]")


@app.command()
def status():
    """Show pod health, current user, agent identity (DID, public key), and registry status."""
    session = _require_session()
    # Health check (no auth needed)
    try:
        health = httpx.get(f"{session['pod_url']}/health/full", timeout=10).json()
    except Exception:
        health = {"status": "unreachable"}

    console.print(f"[bold]Pod:[/bold] {session['pod_url']}")
    status_color = "green" if health.get("status") == "ok" else "red"
    console.print(f"[bold]Health:[/bold] [{status_color}]{health.get('status', 'unknown')}[/{status_color}]")

    providers = health.get("providers", {})
    if providers:
        console.print("[bold]Providers:[/bold]")
        for name, val in providers.items():
            if isinstance(val, bool):
                icon = "[green]ON[/green]" if val else "[dim]off[/dim]"
                console.print(f"  {name}: {icon}")
            elif isinstance(val, dict):
                active = val.get("reachable") or val.get("enabled") or val.get("active")
                icon = "[green]ON[/green]" if active else "[dim]off[/dim]"
                console.print(f"  {name}: {icon}")

    # Current user info
    me = _api("GET", f"/api/auth/me", session=session)
    console.print(f"\n[bold]User:[/bold] {me['display_name']} (@{me['username']})")
    console.print(f"[bold]Type:[/bold] {me.get('user_type', 'person')}")
    console.print(f"[bold]Context:[/bold] {me.get('active_context', 'all')}")

    # Agent identity (DID, public key)
    try:
        agent_card = _api("GET", f"/api/users/{me['id']}/agent/card", session=session)
        console.print(f"\n[bold]Agent Identity:[/bold]")
        console.print(f"  DID: {agent_card.get('did', '[dim]none[/dim]')}")
        pub_key = agent_card.get("public_key_b64")
        if pub_key:
            # Truncate for display
            display_key = pub_key[:20] + "..." if len(pub_key) > 20 else pub_key
            console.print(f"  Public Key: {display_key}")
        else:
            console.print(f"  Public Key: [dim]not set[/dim]")
        console.print(f"  Capabilities: {', '.join(agent_card.get('capabilities', []))}")
        skills = agent_card.get("skills", [])
        if skills:
            skill_names = [s.get("name", "?") for s in skills]
            console.print(f"  Skills: {', '.join(skill_names)}")
    except Exception:
        console.print(f"\n[bold]Agent Identity:[/bold] [dim]unavailable[/dim]")

    # Pod agent card (federation identity)
    try:
        pod_card = httpx.get(f"{session['pod_url']}/.well-known/agent-card.json", timeout=5).json()
        tm = pod_card.get("trustmesh", {})
        console.print(f"\n[bold]Federation:[/bold]")
        console.print(f"  Pod Name: {tm.get('pod_name', '?')}")
        console.print(f"  Protocol: {tm.get('protocol', '?')}")
        console.print(f"  A2A URL: {pod_card.get('url', '?')}")
        console.print(f"  Auth: {', '.join(pod_card.get('authentication', {}).get('schemes', []))}")
    except Exception:
        console.print(f"\n[bold]Federation:[/bold] [dim]agent card unavailable[/dim]")

    # Registry connectivity
    registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:8100")
    try:
        reg_resp = httpx.get(f"{registry_url}/api/agents", timeout=5)
        if reg_resp.status_code == 200:
            reg_data = reg_resp.json()
            agent_count = reg_data.get("count", len(reg_data.get("agents", reg_data if isinstance(reg_data, list) else [])))
            console.print(f"\n[bold]Registry:[/bold] [green]connected[/green] ({registry_url})")
            console.print(f"  Registered agents: {agent_count}")
        else:
            console.print(f"\n[bold]Registry:[/bold] [yellow]error {reg_resp.status_code}[/yellow] ({registry_url})")
    except Exception:
        console.print(f"\n[bold]Registry:[/bold] [dim]not reachable[/dim] ({registry_url})")

    # Capsule count
    capsules = _api("GET", f"/api/users/{me['id']}/capsules", session=session)
    console.print(f"\n[bold]Capsules:[/bold] {len(capsules)}")

    # Peers
    try:
        peers_data = _api("GET", "/api/pod/peers", session=session)
        peers = peers_data.get("peers", [])
        active = sum(1 for p in peers if p.get("status") == "active")
        console.print(f"[bold]Peers:[/bold] {len(peers)} ({active} active)"  )
    except Exception:
        pass


@app.command()
def whoami():
    """Show session info: user, pod, DID, public key, trust networks."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    console.print(f"[bold]{me['display_name']}[/bold] (@{me['username']})")
    console.print(f"Pod: {session['pod_url']}")
    console.print(f"Type: {me.get('user_type', 'person')}")
    console.print(f"ID: {me['id']}")

    # Agent identity
    try:
        agent_card = _api("GET", f"/api/users/{me['id']}/agent/card", session=session)
        console.print(f"\n[bold]Identity:[/bold]")
        console.print(f"  DID: {agent_card.get('did', 'none')}")
        pub_key = agent_card.get("public_key_b64", "")
        if pub_key:
            console.print(f"  Public Key (ed25519): {pub_key}")
        console.print(f"  Capabilities: {', '.join(agent_card.get('capabilities', []))}")
    except Exception:
        pass

    # Networks
    networks = _api("GET", f"/api/users/{me['id']}/networks", session=session)
    if networks:
        console.print(f"\n[bold]Networks ({len(networks)}):[/bold]")
        for n in networks:
            members = len(n.get("members", []))
            console.print(f"  {n['name']} ({n.get('pool_type', 'standard')}, {members} members)")

    # Connections
    connections = _api("GET", f"/api/users/{me['id']}/connections", session=session)
    if connections:
        console.print(f"\n[bold]Connections ({len(connections)}):[/bold]")
        for c in connections:
            peer = c.get("peer", {})
            console.print(f"  {peer.get('display_name', '?')} (@{peer.get('username', '?')})")


# ── Vault commands ──

@vault_app.command("search")
def vault_search(query: str = typer.Argument(..., help="Search query")):
    """Search your knowledge vault using semantic search."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    result = _api("POST", "/api/query", session=session, json={
        "from_user_id": me["id"],
        "to_user_id": me["id"],
        "question": query,
    })
    console.print(f"\n[bold]Agent response:[/bold]")
    console.print(result.get("response", "No response"))
    if result.get("agent_actions"):
        console.print(f"\n[dim]Actions: {', '.join(str(a) for a in result['agent_actions'])}[/dim]")


@vault_app.command("list")
def vault_list(
    capsule_type: str = typer.Option(None, "--type", "-t", help="Filter by type"),
    visibility: str = typer.Option(None, "--vis", "-v", help="Filter by visibility"),
):
    """List capsules in your vault."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    capsules = _api("GET", f"/api/users/{me['id']}/capsules", session=session)

    if capsule_type:
        capsules = [c for c in capsules if c.get("capsule_type") == capsule_type]
    if visibility:
        capsules = [c for c in capsules if c.get("visibility") == visibility]

    if not capsules:
        console.print("[dim]No capsules found.[/dim]")
        return

    vis_display = {"private": "Private", "internal": "Shared", "shareable": "Shared (grant)", "open": "Open"}
    table = Table(title=f"Vault ({len(capsules)} capsules)")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Title", style="bold")
    table.add_column("Type")
    table.add_column("Sharing Level")
    table.add_column("Category")
    table.add_column("Shared With")
    table.add_column("Archived")

    for c in capsules:
        net_names = c.get("network_names", [])
        shared_with = ", ".join(net_names) if net_names else ""
        table.add_row(
            c["id"][:8],
            c["title"],
            c.get("capsule_type", ""),
            vis_display.get(c.get("visibility", ""), c.get("visibility", "")),
            c.get("category", ""),
            shared_with,
            "yes" if c.get("is_archived") else "",
        )
    console.print(table)


@vault_app.command("get")
def vault_get(capsule_id: str = typer.Argument(..., help="Capsule ID (or prefix)")):
    """Show a single capsule (decrypted)."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    capsules = _api("GET", f"/api/users/{me['id']}/capsules", session=session)

    # Match by prefix
    matches = [c for c in capsules if c["id"].startswith(capsule_id)]
    if not matches:
        console.print(f"[red]No capsule matching '{capsule_id}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous prefix — {len(matches)} matches. Be more specific.[/yellow]")
        raise typer.Exit(1)

    vis_display = {"private": "Private", "internal": "Shared", "shareable": "Shared (grant)", "open": "Open"}
    c = matches[0]
    console.print(f"[bold]{c['title']}[/bold]")
    console.print(f"ID: {c['id']}")
    owner_name = c.get("owner_display_name")
    if owner_name:
        console.print(f"Owner: {owner_name}")
    console.print(f"Type: {c.get('capsule_type', '')}  Sharing Level: {vis_display.get(c.get('visibility', ''), c.get('visibility', ''))}")
    console.print(f"Category: {c.get('category', '')}  Context: {c.get('context', '')}")
    net_names = c.get("network_names", [])
    if net_names:
        console.print(f"Shared with: {', '.join(net_names)}")
    if c.get("is_archived"):
        console.print("[yellow]ARCHIVED[/yellow]")
    console.print(f"\n{c.get('content', '')}")


@vault_app.command("add")
def vault_add(
    title: str = typer.Option(..., "--title", "-t", help="Capsule title"),
    content: str = typer.Option(..., "--content", "-c", help="Capsule content"),
    capsule_type: str = typer.Option("memory", "--type", help="Capsule type"),
    visibility: str = typer.Option("private", "--vis", help="Visibility: private|internal|open"),
    category: str = typer.Option(None, "--category", help="Category tag"),
):
    """Add a new capsule to your vault."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    payload = {
        "capsule_type": capsule_type,
        "title": title,
        "content": content,
        "visibility": visibility,
    }
    if category:
        payload["category"] = category
    result = _api("POST", f"/api/users/{me['id']}/capsules", session=session, json=payload)
    console.print(f"[green]Created capsule: {result['title']} ({result['id'][:8]})[/green]")


@vault_app.command("archive")
def vault_archive(capsule_id: str = typer.Argument(..., help="Capsule ID")):
    """Archive a capsule (soft-delete)."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    # Find full ID by prefix
    capsules = _api("GET", f"/api/users/{me['id']}/capsules", session=session)
    matches = [c for c in capsules if c["id"].startswith(capsule_id)]
    if not matches:
        console.print(f"[red]No capsule matching '{capsule_id}'[/red]")
        raise typer.Exit(1)

    full_id = matches[0]["id"]
    _api("PUT", f"/api/capsules/{full_id}", session=session, json={"is_archived": True})
    console.print(f"[green]Archived capsule {full_id[:8]}[/green]")


# ── Agent commands ──

@agent_app.command("ask")
def agent_ask(
    question: str = typer.Argument(..., help="Question to ask"),
    to: str = typer.Option(None, "--to", help="Username to cross-query"),
):
    """Ask your agent a question (or cross-query another user's agent)."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)

    if to:
        # Look up target user
        users = _api("GET", "/api/users", session=session)
        target = next((u for u in users if u["username"] == to), None)
        if not target:
            console.print(f"[red]User '{to}' not found[/red]")
            raise typer.Exit(1)
        to_user_id = target["id"]
    else:
        to_user_id = me["id"]

    with console.status("Thinking..."):
        result = _api("POST", "/api/query", session=session, json={
            "from_user_id": me["id"],
            "to_user_id": to_user_id,
            "question": question,
        })

    if to:
        console.print(f"[dim]Trust: {result.get('trust_level', '?')} | Networks: {', '.join(result.get('shared_networks', []))}[/dim]")
    console.print(f"\n{result.get('response', 'No response')}")

    if result.get("decision") == "redacted":
        console.print("\n[yellow]Response was redacted by Citadel security scan.[/yellow]")


@agent_app.command("chat")
def agent_chat():
    """Interactive chat with your agent (streaming responses)."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    history: list[dict] = []

    console.print(f"[bold]Chat with {me['display_name']}'s Agent[/bold]")
    console.print("[dim]Type 'quit' or Ctrl+C to exit.[/dim]\n")

    while True:
        try:
            question = console.input("[bold blue]You:[/bold blue] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if question.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break
        if not question.strip():
            continue

        # Stream via SSE
        s = session
        try:
            with httpx.Client(
                base_url=s["pod_url"],
                cookies={"trustmesh_session": s["token"]},
                timeout=120.0,
            ) as client:
                with client.stream(
                    "POST", "/api/query/stream",
                    json={
                        "from_user_id": me["id"],
                        "to_user_id": me["id"],
                        "question": question,
                        "conversation_history": history,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        console.print(f"[red]Error {resp.status_code}[/red]")
                        continue

                    console.print("[bold green]Agent:[/bold green] ", end="")
                    full_text = ""
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type")
                        if etype == "text":
                            chunk = event.get("data", "")
                            print(chunk, end="", flush=True)
                            full_text += chunk
                        elif etype == "tool":
                            tool_info = event.get("data", "")
                            console.print(f"\n  [dim]Tool: {tool_info}[/dim]", end="")
                        elif etype == "error":
                            console.print(f"\n[red]{event.get('data', 'Error')}[/red]")
                        elif etype == "done":
                            pass
                    print()  # newline after stream

                    # Update history for multi-turn
                    if full_text:
                        history.append({"role": "user", "content": question})
                        history.append({"role": "assistant", "content": full_text})
        except httpx.ConnectError:
            console.print("[red]Connection lost.[/red]")
            break


# ── Connection commands ──

@conn_app.command("list")
def connections_list():
    """List your trust connections."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    connections = _api("GET", f"/api/users/{me['id']}/connections", session=session)

    if not connections:
        console.print("[dim]No connections.[/dim]")
        return

    table = Table(title=f"Connections ({len(connections)})")
    table.add_column("Peer", style="bold")
    table.add_column("Type")
    table.add_column("Since")
    table.add_column("ID", style="dim", max_width=8)

    for c in connections:
        peer = c.get("peer", {})
        table.add_row(
            peer.get("display_name", "?"),
            peer.get("user_type", ""),
            c.get("accepted_at", "")[:10] if c.get("accepted_at") else "",
            c["id"][:8],
        )
    console.print(table)


@conn_app.command("request")
def connections_request(
    username: str = typer.Argument(..., help="Username to connect with"),
    message: str = typer.Option(None, "--message", "-m", help="Connection message"),
):
    """Send a connection request."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    users = _api("GET", "/api/users", session=session)
    target = next((u for u in users if u["username"] == username), None)
    if not target:
        console.print(f"[red]User '{username}' not found[/red]")
        raise typer.Exit(1)

    payload = {"from_user_id": me["id"], "to_user_id": target["id"]}
    if message:
        payload["message"] = message
    _api("POST", "/api/connections/request", session=session, json=payload)
    console.print(f"[green]Connection request sent to {target['display_name']}[/green]")


@conn_app.command("accept")
def connections_accept(request_id: str = typer.Argument(..., help="Connection request ID")):
    """Accept a pending connection request."""
    session = _require_session()
    _api("PUT", f"/api/connection-requests/{request_id}", session=session, json={"status": "accepted"})
    console.print("[green]Connection accepted.[/green]")


@conn_app.command("remove")
def connections_remove(connection_id: str = typer.Argument(..., help="Connection ID")):
    """Remove a connection."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    # Find connection by prefix
    connections = _api("GET", f"/api/users/{me['id']}/connections", session=session)
    matches = [c for c in connections if c["id"].startswith(connection_id)]
    if not matches:
        console.print(f"[red]No connection matching '{connection_id}'[/red]")
        raise typer.Exit(1)
    full_id = matches[0]["id"]
    # The delete endpoint doesn't exist as a simple DELETE on connection ID,
    # so we remove the member from the network or just inform the user.
    console.print(f"[yellow]Connection removal is managed via the web UI (connection {full_id[:8]})[/yellow]")


# ── Network commands ──

@net_app.command("list")
def networks_list():
    """List your trust networks/pools."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    networks = _api("GET", f"/api/users/{me['id']}/networks", session=session)

    if not networks:
        console.print("[dim]No networks.[/dim]")
        return

    table = Table(title=f"Networks ({len(networks)})")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Pool")
    table.add_column("Members")
    table.add_column("ID", style="dim", max_width=8)

    for n in networks:
        table.add_row(
            n["name"],
            n.get("network_type", ""),
            n.get("pool_type", "standard"),
            str(len(n.get("members", []))),
            n["id"][:8],
        )
    console.print(table)


@net_app.command("members")
def networks_members(network_id: str = typer.Argument(..., help="Network ID (or prefix)")):
    """Show members of a network."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    networks = _api("GET", f"/api/users/{me['id']}/networks", session=session)
    matches = [n for n in networks if n["id"].startswith(network_id)]
    if not matches:
        console.print(f"[red]No network matching '{network_id}'[/red]")
        raise typer.Exit(1)
    n = matches[0]

    console.print(f"[bold]{n['name']}[/bold] ({n.get('pool_type', 'standard')})")
    members = n.get("members", [])
    if not members:
        console.print("[dim]No members.[/dim]")
        return

    table = Table()
    table.add_column("Name", style="bold")
    table.add_column("Username")
    table.add_column("Type")

    for m in members:
        table.add_row(m.get("display_name", "?"), m.get("username", ""), m.get("user_type", ""))
    console.print(table)


@net_app.command("create")
def networks_create(
    name: str = typer.Option(..., "--name", "-n", help="Network name"),
    network_type: str = typer.Option("custom", "--type", "-t", help="Network type"),
    pool_type: str = typer.Option("standard", "--pool", help="Pool type"),
    description: str = typer.Option("", "--desc", "-d", help="Description"),
):
    """Create a new trust network."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    result = _api("POST", "/api/networks", session=session, json={
        "owner_id": me["id"],
        "name": name,
        "network_type": network_type,
        "pool_type": pool_type,
        "description": description,
    })
    console.print(f"[green]Created network: {result['name']} ({result['id'][:8]})[/green]")


# ── Pod commands ──

@pod_app.command("info")
def pod_info():
    """Show current pod status and identity."""
    session = _require_session()
    info = _api("GET", "/api/pod", session=session)
    console.print(f"[bold]Pod:[/bold] {info.get('pod_name', '?')}")
    console.print(f"[bold]URL:[/bold] {info.get('pod_url', '?')}")
    console.print(f"[bold]Agents:[/bold] {info.get('agent_count', 0)}")
    if info.get("agents"):
        for a in info["agents"]:
            console.print(f"  {a.get('display_name', '?')} (@{a.get('username', '?')})")


@pod_app.command("peers")
def pod_peers():
    """List peer pods in the federation."""
    session = _require_session()
    data = _api("GET", "/api/pod/peers", session=session)
    peers = data.get("peers", [])

    console.print(f"[bold]This pod:[/bold] {data.get('pod_name', '?')} ({data.get('pod_url', '')})")

    if not peers:
        console.print("[dim]No peer pods connected.[/dim]")
        return

    table = Table(title=f"Peers ({len(peers)})")
    table.add_column("Name", style="bold")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Agents")
    table.add_column("Last Seen")

    for p in peers:
        status_color = "green" if p.get("status") == "active" else "red"
        table.add_row(
            p.get("name", "?"),
            p.get("url", ""),
            f"[{status_color}]{p.get('status', '?')}[/{status_color}]",
            str(p.get("agent_count", 0)),
            p.get("last_seen_at", "")[:19] if p.get("last_seen_at") else "",
        )
    console.print(table)


@pod_app.command("connect")
def pod_connect(url: str = typer.Argument(..., help="Peer pod URL")):
    """Connect to a peer pod."""
    session = _require_session()
    result = _api("POST", "/api/pod/peers", session=session, json={"url": url})
    peer = result.get("peer", {})
    console.print(f"[green]Connected to {peer.get('name', '?')} ({peer.get('url', '')})[/green]")


@pod_app.command("disconnect")
def pod_disconnect(peer_id: str = typer.Argument(..., help="Peer pod ID (from `pod peers`)")):
    """Disconnect from a peer pod and clean up its ghost users."""
    session = _require_session()
    result = _api("DELETE", f"/api/pod/peers/{peer_id}", session=session)
    cleanup = result.get("cleanup", {})
    console.print(f"[green]Disconnected from {result.get('peer_url', '?')}[/green]")
    ghosts = cleanup.get("ghosts_removed", 0)
    if ghosts:
        console.print(f"  Cleaned up {ghosts} ghost user(s), {cleanup.get('connections_removed', 0)} connection(s), {cleanup.get('memberships_removed', 0)} membership(s)")


@pod_app.command("discover")
def pod_discover():
    """Discover agents across the federation."""
    session = _require_session()
    data = _api("GET", "/api/pod/discover", session=session)
    console.print(f"[bold]Total agents:[/bold] {data.get('total', 0)} (local: {data.get('local_count', 0)}, remote: {data.get('remote_count', 0)})")

    agents = data.get("agents", [])
    if not agents:
        return

    table = Table(title="Federation Agents")
    table.add_column("Name", style="bold")
    table.add_column("Username")
    table.add_column("Type")
    table.add_column("Pod")
    table.add_column("Local")

    for a in agents:
        pod_info = a.get("_pod", {})
        table.add_row(
            a.get("display_name", "?"),
            a.get("username", ""),
            a.get("user_type", ""),
            pod_info.get("name", "?"),
            "yes" if pod_info.get("is_local") else "",
        )
    console.print(table)


@pod_app.command("golive")
def pod_golive():
    """Toggle Go Live — register or remove your agent from the public registry."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    is_live = me.get("is_discoverable", False)

    if is_live:
        console.print(f"\n  Your agent is currently [green]live[/green] in the public registry.\n")
        confirm = typer.confirm("Go private? Your agent will be removed from the public registry")
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
        _api("PUT", f"/api/users/{me['id']}", session=session, json={"is_discoverable": False})
        console.print("\n  [yellow]Done.[/yellow] Your agent has been removed from the public registry.")
    else:
        console.print(f"\n  Your agent is currently [dim]private[/dim].\n")
        console.print("  Going live will make your name, DID, and pod URL publicly visible.")
        console.print("  Anyone can discover your agent in the registry.\n")
        confirm = typer.confirm("Confirm — go live in the public registry?")
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
        _api("PUT", f"/api/users/{me['id']}", session=session, json={"is_discoverable": True})
        console.print("\n  [green]Done.[/green] Your agent is now live in the public registry!")


# ── Registry commands ──

@reg_app.command("list")
def registry_list():
    """List agents in the public registry."""
    session = _require_session()
    # Registry runs on :8100 by default, or same pod
    registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:8100")
    try:
        resp = httpx.get(f"{registry_url}/api/agents", timeout=10)
        data = resp.json()
    except Exception:
        console.print(f"[red]Cannot reach registry at {registry_url}[/red]")
        raise typer.Exit(1)

    agents = data if isinstance(data, list) else data.get("agents", [])
    if not agents:
        console.print("[dim]No agents registered.[/dim]")
        return

    table = Table(title=f"Public Registry ({len(agents)} agents)")
    table.add_column("Name", style="bold")
    table.add_column("Pod")
    table.add_column("URL")
    table.add_column("Agents")

    for a in agents:
        table.add_row(
            a.get("pod_name", "?"),
            a.get("pod_url", ""),
            a.get("agent_card_url", ""),
            str(a.get("agent_count", 0)),
        )
    console.print(table)


@reg_app.command("search")
def registry_search(query: str = typer.Argument(..., help="Search query")):
    """Search the public registry for agents."""
    registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:8100")
    try:
        resp = httpx.get(f"{registry_url}/api/search", params={"q": query}, timeout=10)
        data = resp.json()
    except Exception:
        console.print(f"[red]Cannot reach registry at {registry_url}[/red]")
        raise typer.Exit(1)

    results = data if isinstance(data, list) else data.get("results", [])
    if not results:
        console.print(f"[dim]No results for '{query}'[/dim]")
        return

    for r in results:
        console.print(f"  [bold]{r.get('pod_name', '?')}[/bold] — {r.get('pod_url', '')}")


# ── MCP serve ──

@mcp_app.command("serve")
def mcp_serve():
    """Start the TrustMesh MCP server on stdio (for Claude Desktop, Cursor, etc.)."""
    session = _load_session()
    if not session:
        console.print("[red]Not logged in. Run: trustmesh login[/red]", file=sys.stderr)
        raise typer.Exit(1)

    # Import and run the MCP server
    from src.mcp_server import create_mcp_server
    import asyncio

    mcp_server = create_mcp_server(session)
    asyncio.run(mcp_server.run_stdio_async())


# ── Entry point ──

if __name__ == "__main__":
    app()
