"""TrustMesh CLI — power-user interface to TrustMesh pods.

Usage:
    trustmesh login --pod http://localhost:9000
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
tl_app = typer.Typer(help="Timeline engine — view and manage entries.")

app.add_typer(vault_app, name="vault")
app.add_typer(agent_app, name="agent")
app.add_typer(conn_app, name="connections")
app.add_typer(net_app, name="networks")
app.add_typer(pod_app, name="pod")
app.add_typer(reg_app, name="registry")
app.add_typer(mcp_app, name="mcp")
app.add_typer(tl_app, name="timeline")

console = Console()

# ── Session management ──

CONFIG_DIR = Path.home() / ".trustmesh"
CONFIG_FILE = CONFIG_DIR / "config.toml"
SESSION_FILE = CONFIG_DIR / "session"


def _ensure_config_dir():
    """Create ~/.trustmesh/ with 0700 permissions."""
    CONFIG_DIR.mkdir(mode=0o700, exist_ok=True)


def _save_session(pod_url: str, token: str, user_id: str, username: str, csrf_token: str = ""):
    """Store session token securely."""
    _ensure_config_dir()
    data = {"pod_url": pod_url, "token": token, "user_id": user_id, "username": username, "csrf_token": csrf_token}
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
    """Create an httpx client with session cookie + CSRF header attached."""
    if session is None:
        session = _load_session()
    if not session:
        console.print("[red]Not logged in. Run: trustmesh login[/red]")
        raise typer.Exit(1)
    headers = {}
    cookies: dict = {"trustmesh_session": session["token"]}
    if csrf := session.get("csrf_token"):
        headers["X-CSRF-Token"] = csrf
        cookies["trustmesh_csrf"] = csrf  # double-submit: cookie must match header
    return httpx.Client(
        base_url=session["pod_url"],
        cookies=cookies,
        headers=headers,
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

def _find_multipod_for_username(username: str) -> str | None:
    """If multi-pod is running, find the pod port for a given username."""
    for port in range(9001, 9017):
        try:
            resp = httpx.get(f"http://localhost:{port}/api/pod", timeout=1.0)
            if resp.status_code == 200:
                agents = resp.json().get("agents", [])
                if agents and agents[0].get("owner_username") == username:
                    return f"http://localhost:{port}"
        except Exception:
            continue
    return None


def _any_multipod_running() -> list[tuple[int, str]]:
    """Quick scan: return list of (port, pod_name) for running multi-pods."""
    found = []
    for port in range(9001, 9017):
        try:
            resp = httpx.get(f"http://localhost:{port}/health", timeout=0.5)
            if resp.status_code == 200:
                found.append(port)
                if len(found) >= 2:
                    return found  # At least 2 = definitely multi-pod
        except Exception:
            continue
    return found


@app.command()
def login(
    pod: str = typer.Option("http://localhost:9000", "--pod", "-p", help="Pod URL"),
    user: str = typer.Option(None, "--user", "-u", help="Username"),
):
    """Authenticate with a TrustMesh pod."""
    if not user:
        user = typer.prompt("Username")

    pod_url = pod.rstrip("/")
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        password = getpass.getpass("Password: ")

        try:
            resp = httpx.post(
                f"{pod_url}/api/auth/login",
                json={"username": user, "password": password},
                timeout=15.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            # If default port failed, check if multi-pod is running
            if pod_url == "http://localhost:9000" and _any_multipod_running():
                console.print(f"[yellow]No pod on :9000, but multi-pod federation is running.[/yellow]")
                # Try to find the right pod for this username
                match = _find_multipod_for_username(user)
                if match:
                    console.print(f"[green]Found your pod: {match}[/green]")
                    pod_url = match
                    # Retry with the correct pod
                    try:
                        resp = httpx.post(
                            f"{pod_url}/api/auth/login",
                            json={"username": user, "password": password},
                            timeout=15.0,
                        )
                    except (httpx.ConnectError, httpx.TimeoutException):
                        console.print(f"[red]Cannot connect to {pod_url}[/red]")
                        raise typer.Exit(1)
                else:
                    console.print(f"[dim]Could not find a pod for @{user}. Run 'trustmesh pods' to see available pods.[/dim]")
                    raise typer.Exit(1)
            else:
                console.print(f"[red]Cannot connect to {pod_url} — is the backend running?[/red]")
                console.print("[dim]Start with: ./dev.sh start  OR  ./multi-pod.sh demo[/dim]")
                raise typer.Exit(1)

        if resp.status_code == 429:
            console.print("[red]Too many login attempts. Try again later.[/red]")
            raise typer.Exit(1)

        if resp.status_code == 401:
            remaining = max_attempts - attempt
            if remaining > 0:
                console.print(f"[yellow]Wrong username or password. {remaining} attempt{'s' if remaining > 1 else ''} remaining.[/yellow]")
                # Let them fix the username too
                retry_user = typer.prompt("Username", default=user)
                if retry_user != user:
                    user = retry_user
                continue
            else:
                console.print("[red]Login failed after 3 attempts.[/red]")
                raise typer.Exit(1)

        if resp.status_code >= 400:
            console.print(f"[red]Login failed: {resp.text}[/red]")
            raise typer.Exit(1)

        # Success — extract session token + CSRF token
        token = resp.cookies.get("trustmesh_session")
        if not token:
            console.print("[red]No session token received[/red]")
            raise typer.Exit(1)

        csrf_token = resp.cookies.get("trustmesh_csrf", "")
        user_data = resp.json()
        _save_session(pod_url, token, user_data["id"], user_data["username"], csrf_token)
        console.print(f"\n[green]Logged in as {user_data['display_name']} ({user_data['username']})[/green]")
        console.print(f"  Pod: {pod_url}")
        console.print()
        console.print("[dim]Quick start:[/dim]")
        console.print("  [cyan]trustmesh whoami[/cyan]          — your identity & networks")
        console.print("  [cyan]trustmesh vault list[/cyan]      — browse your capsules")
        console.print("  [cyan]trustmesh agent chat[/cyan]      — talk to your AI agent")
        console.print("  [cyan]trustmesh agent ask \"...\"[/cyan] — one-shot question")
        console.print("  [cyan]trustmesh connections list[/cyan] — your trust connections")
        return


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
    if isinstance(providers, dict) and providers:
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
    registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:9100")
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
def init(
    pod: str = typer.Option("http://localhost:9000", "--pod", "-p", help="Pod URL"),
    username: str = typer.Option(None, "--username", "-u", help="Username for the new account"),
    display_name: str = typer.Option(None, "--display-name", "-n", help="Display name"),
    user_type: str = typer.Option("person", "--type", "-t", help="Entity type: person, organization, government"),
    pod_name: str = typer.Option(None, "--pod-name", help="Pod name (for config)"),
):
    """Initialize a new TrustMesh pod — create the first user account.

    This calls POST /api/onboard/init on the running Zig server to create a user,
    agent, ed25519 keypair, and vault key. The pod must be running.

    Example:
        trustmesh init --username molly --pod-name "Molly's Pod"
    """
    pod_url = pod.rstrip("/")

    # Check pod is reachable
    try:
        health = httpx.get(f"{pod_url}/api/onboard/status", timeout=5.0)
        if health.status_code == 200:
            data = health.json()
            if data.get("initialized"):
                console.print(f"[yellow]Pod already initialized ({data.get('user_count', '?')} users).[/yellow]")
                console.print("[dim]Run 'trustmesh login' to sign in.[/dim]")
                raise typer.Exit(0)
    except (httpx.ConnectError, httpx.TimeoutException):
        console.print(f"[red]Cannot connect to {pod_url} — is the Zig server running?[/red]")
        console.print("[dim]Start with: ./dev.sh start[/dim]")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception:
        pass  # Non-fatal — proceed with init attempt

    if not username:
        username = typer.prompt("Username (2-50 chars)")
    if not display_name:
        display_name = typer.prompt("Display name", default=username)

    # Password with confirmation
    for _ in range(3):
        password = getpass.getpass("Password (12+ chars, upper+lower+digit): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            console.print("[yellow]Passwords don't match. Try again.[/yellow]")
            continue
        break
    else:
        console.print("[red]Too many failed attempts.[/red]")
        raise typer.Exit(1)

    if password != confirm:
        console.print("[red]Passwords don't match.[/red]")
        raise typer.Exit(1)

    # Call onboard endpoint
    try:
        resp = httpx.post(
            f"{pod_url}/api/onboard/init",
            json={
                "username": username,
                "password": password,
                "display_name": display_name,
                "user_type": user_type,
            },
            timeout=30.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException):
        console.print(f"[red]Cannot connect to {pod_url}[/red]")
        raise typer.Exit(1)

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        console.print(f"[red]Init failed: {detail}[/red]")
        raise typer.Exit(1)

    result = resp.json()
    user_id = result.get("user_id", "")
    did = result.get("did", "")

    # Save session from response cookie or token
    token = resp.cookies.get("trustmesh_session") or result.get("session_token", "")
    if token:
        csrf_token = resp.cookies.get("trustmesh_csrf", "")
        _save_session(pod_url, token, user_id, username, csrf_token)

    # Write config.toml
    _ensure_config_dir()
    config_data = {
        "pod_url": pod_url,
        "pod_name": pod_name or f"{display_name}'s Pod",
        "username": username,
        "did": did,
    }
    CONFIG_FILE.write_text(
        "\n".join(f'{k} = "{v}"' for k, v in config_data.items()) + "\n"
    )

    console.print()
    console.print(f"[green bold]Pod initialized![/green bold]")
    console.print(f"  User:    {display_name} (@{username})")
    console.print(f"  DID:     {did}")
    console.print(f"  Pod:     {pod_url}")
    console.print(f"  Config:  {CONFIG_FILE}")
    console.print()
    console.print("[dim]You're now logged in. Try:[/dim]")
    console.print("  [cyan]trustmesh whoami[/cyan]")
    console.print("  [cyan]trustmesh vault list[/cyan]")
    console.print("  [cyan]trustmesh agent chat[/cyan]")


@app.command()
def pods():
    """Scan local ports 8001-8016 for running TrustMesh pods. Use with multi-pod setup."""
    table = Table(title="Local TrustMesh Pods")
    table.add_column("Port", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Login command", style="dim")

    found = 0
    for port in range(9001, 9017):
        url = f"http://localhost:{port}"
        try:
            resp = httpx.get(f"{url}/api/pod", timeout=1.5)
            if resp.status_code != 200:
                continue
            data = resp.json()
            # Use agent owner info (more accurate than pod_name in multi-pod)
            agents = data.get("agents", [])
            if agents:
                agent = agents[0]
                name = agent.get("owner_display_name", data.get("pod_name", "?"))
                user_type = agent.get("user_type", "person")
                username = agent.get("owner_username", "")
            else:
                name = data.get("pod_name", "?")
                user_type = "?"
                username = ""
            table.add_row(
                str(port),
                f"{name} (@{username})" if username else name,
                user_type,
                "[green]online[/green]",
                f"trustmesh login --pod {url}",
            )
            found += 1
        except (httpx.ConnectError, httpx.TimeoutException):
            continue
        except Exception:
            continue

    if found == 0:
        console.print("[dim]No pods found on ports 8001-8016.[/dim]")
        console.print("[dim]Start multi-pod: ./multi-pod.sh demo[/dim]")
        return

    console.print(table)

    # Show current session if any
    session = _load_session()
    if session:
        console.print(f"\n[dim]Current session: {session.get('username', '?')}@{session['pod_url']}[/dim]")
    else:
        console.print(f"\n[dim]Not logged in. Pick a pod above and run the login command.[/dim]")


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

    # Check if any capsule has network sharing or archived state
    has_networks = any(c.get("network_names") for c in capsules)
    has_archived = any(c.get("is_archived") for c in capsules)

    table = Table(title=f"Vault ({len(capsules)} capsules)")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Title", style="bold")
    table.add_column("Type")
    table.add_column("Sharing Level")
    table.add_column("Category")
    if has_networks:
        table.add_column("Shared With")
    if has_archived:
        table.add_column("Archived")

    for c in capsules:
        row = [
            c["id"][:8],
            c["title"],
            c.get("capsule_type", ""),
            vis_display.get(c.get("visibility", ""), c.get("visibility", "")),
            c.get("category", ""),
        ]
        if has_networks:
            net_names = c.get("network_names", [])
            row.append(", ".join(net_names) if net_names else "")
        if has_archived:
            row.append("yes" if c.get("is_archived") else "")
        table.add_row(*row)
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
    table.add_column("Relationship", style="cyan")
    table.add_column("Label", style="magenta")
    table.add_column("Type")
    table.add_column("Since")
    table.add_column("ID", style="dim", max_width=8)

    for c in connections:
        peer = c.get("peer", {})
        table.add_row(
            peer.get("display_name", "?"),
            c.get("relationship_type", "") or "",
            c.get("my_label", "") or "",
            peer.get("user_type", ""),
            c.get("accepted_at", "")[:10] if c.get("accepted_at") else "",
            c["id"][:8],
        )
    console.print(table)


@conn_app.command("request")
def connections_request(
    username: str = typer.Argument(..., help="Username to connect with"),
    message: str = typer.Option(None, "--message", "-m", help="Connection message"),
    relationship: str = typer.Option(None, "--rel", "-r", help="Relationship type: family|friend|work|healthcare|neighbor|emergency|other"),
    label: str = typer.Option(None, "--label", "-l", help="Your label for this person (e.g. 'spouse', 'boss')"),
):
    """Send a connection request."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    users = _api("GET", "/api/users", session=session)
    target = next((u for u in users if u["username"] == username), None)
    if not target:
        console.print(f"[red]User '{username}' not found[/red]")
        raise typer.Exit(1)

    payload: dict = {"from_user_id": me["id"], "to_user_id": target["id"]}
    if message:
        payload["message"] = message
    if relationship:
        payload["relationship_type"] = relationship
    if label:
        payload["from_label"] = label
    _api("POST", "/api/connections/request", session=session, json=payload)
    console.print(f"[green]Connection request sent to {target['display_name']}[/green]")


@conn_app.command("accept")
def connections_accept(
    request_id: str = typer.Argument(..., help="Connection request ID (or prefix)"),
    label: str = typer.Option(None, "--label", "-l", help="Your label for this person (e.g. 'colleague', 'friend')"),
):
    """Accept a pending connection request."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    # Support prefix matching
    requests = _api("GET", f"/api/users/{me['id']}/connection-requests", session=session)
    matches = [r for r in requests if r["id"].startswith(request_id)]
    if not matches:
        console.print(f"[red]No pending request matching '{request_id}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous prefix — {len(matches)} matches. Be more specific.[/yellow]")
        raise typer.Exit(1)
    req = matches[0]
    payload: dict = {"status": "accepted"}
    if label:
        payload["to_label"] = label
    _api("PUT", f"/api/connection-requests/{req['id']}", session=session, json=payload)
    from_name = req.get("from_user", {}).get("display_name", "?") if req.get("from_user") else "?"
    console.print(f"[green]Accepted connection from {from_name}.[/green]")


@conn_app.command("pending")
def connections_pending():
    """Show incoming connection requests waiting for your response."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    requests = _api("GET", f"/api/users/{me['id']}/connection-requests", session=session)

    if not requests:
        console.print("[dim]No pending connection requests.[/dim]")
        return

    table = Table(title=f"Pending Requests ({len(requests)})")
    table.add_column("From", style="bold")
    table.add_column("Relationship", style="cyan")
    table.add_column("Their Label", style="magenta")
    table.add_column("Message")
    table.add_column("Mutual", style="dim")
    table.add_column("ID", style="dim", max_width=8)

    for r in requests:
        from_user = r.get("from_user", {}) or {}
        mutual_parts = []
        mc = r.get("mutual_connections", 0)
        mn = r.get("mutual_networks", 0)
        if mc:
            mutual_parts.append(f"{mc} conn")
        if mn:
            mutual_parts.append(f"{mn} net")
        table.add_row(
            from_user.get("display_name", "?"),
            r.get("relationship_type", "") or "",
            r.get("from_label", "") or "",
            r.get("message", "") or "",
            ", ".join(mutual_parts) if mutual_parts else "",
            r["id"][:8],
        )
    console.print(table)
    console.print(f"\n[dim]Accept: trustmesh connections accept <ID> [--label 'your label'][/dim]")


@conn_app.command("label")
def connections_label(
    connection_id: str = typer.Argument(..., help="Connection ID (or prefix)"),
    label: str = typer.Option(None, "--label", "-l", help="Your label for this person"),
    relationship: str = typer.Option(None, "--rel", "-r", help="Relationship type"),
):
    """Update your label or relationship type on a connection."""
    if not label and not relationship:
        console.print("[red]Provide --label and/or --rel to update.[/red]")
        raise typer.Exit(1)
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    connections = _api("GET", f"/api/users/{me['id']}/connections", session=session)
    matches = [c for c in connections if c["id"].startswith(connection_id)]
    if not matches:
        console.print(f"[red]No connection matching '{connection_id}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous prefix — {len(matches)} matches.[/yellow]")
        raise typer.Exit(1)
    conn = matches[0]
    payload: dict = {}
    if label:
        payload["my_label"] = label
    if relationship:
        payload["relationship_type"] = relationship
    result = _api("PATCH", f"/api/connections/{conn['id']}/label", session=session, json=payload)
    peer_name = result.get("peer", {}).get("display_name", "?") if result.get("peer") else "?"
    console.print(f"[green]Updated connection with {peer_name}.[/green]")


@conn_app.command("remove")
def connections_remove(connection_id: str = typer.Argument(..., help="Connection ID (or prefix)")):
    """Remove a connection (disconnect from someone)."""
    session = _require_session()
    me = _api("GET", "/api/auth/me", session=session)
    connections = _api("GET", f"/api/users/{me['id']}/connections", session=session)
    matches = [c for c in connections if c["id"].startswith(connection_id)]
    if not matches:
        console.print(f"[red]No connection matching '{connection_id}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous prefix — {len(matches)} matches. Be more specific.[/yellow]")
        raise typer.Exit(1)
    conn = matches[0]
    peer_name = conn.get("peer", {}).get("display_name", "?")
    confirm = typer.confirm(f"Disconnect from {peer_name}?")
    if not confirm:
        console.print("[dim]Cancelled.[/dim]")
        raise typer.Exit()
    _api("DELETE", f"/api/connections/{conn['id']}", session=session)
    console.print(f"[green]Disconnected from {peer_name}.[/green]")


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
            console.print(f"  {a.get('owner_display_name', '?')} (@{a.get('owner_username', '?')})")


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
        pod_meta = a.get("_pod", {})
        # Local agents have owner_display_name; remote A2A agents have name
        name = a.get("owner_display_name") or a.get("name", "?")
        username = a.get("owner_username", "")
        user_type = a.get("user_type", "")
        table.add_row(
            name,
            username,
            user_type,
            pod_meta.get("name", "?"),
            "yes" if pod_meta.get("is_local") else "",
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
    # Registry is public — no session required
    registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:9100")
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
    table.add_column("Username")
    table.add_column("Type")
    table.add_column("Pod URL")
    table.add_column("Capabilities", max_width=30)

    for a in agents:
        caps = a.get("capabilities", [])
        table.add_row(
            a.get("display_name", "?"),
            a.get("username", ""),
            a.get("entity_type", ""),
            a.get("pod_url", ""),
            ", ".join(caps[:3]) + ("..." if len(caps) > 3 else "") if caps else "",
        )
    console.print(table)


@reg_app.command("search")
def registry_search(query: str = typer.Argument(..., help="Search query")):
    """Search the public registry for agents."""
    registry_url = os.environ.get("TRUSTMESH_REGISTRY_URL", "http://localhost:9100")
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

    table = Table(title=f"Search: \"{query}\" ({len(results)} results)")
    table.add_column("Name", style="bold")
    table.add_column("Username")
    table.add_column("Type")
    table.add_column("Pod URL")

    for r in results:
        table.add_row(
            r.get("display_name", "?"),
            r.get("username", ""),
            r.get("entity_type", ""),
            r.get("pod_url", ""),
        )
    console.print(table)


# ── Timeline commands ──

TRIGGER_DISPLAY = {
    "cron": "cron",
    "event": "event",
    "absence": "absence",
    "time": "time",
}


@tl_app.command("list")
def timeline_list(
    state: str = typer.Option(None, "--state", "-s", help="Filter by state (active, pending, dormant, etc.)"),
):
    """List all timeline entries with trigger, hook, and dependency info."""
    session = _require_session()
    entries = _api("GET", "/api/timeline/entries", session=session)

    if state:
        entries = [e for e in entries if e.get("state_name", "").lower() == state.lower()]

    if not entries:
        console.print("[dim]No entries found.[/dim]")
        return

    # Sort by salience descending
    entries.sort(key=lambda e: e.get("salience", 0), reverse=True)

    table = Table(title=f"Timeline ({len(entries)} entries)")
    table.add_column("Label", style="bold", max_width=30)
    table.add_column("State")
    table.add_column("Type", style="dim")
    table.add_column("Category")
    table.add_column("Trigger", style="cyan")
    table.add_column("Hook", style="magenta")
    table.add_column("Deps", style="dim")
    table.add_column("Sal", justify="right")
    table.add_column("Vis")

    for e in entries:
        state_name = e.get("state_name", "?")
        state_colors = {"ACTIVE": "green", "PENDING": "yellow", "DORMANT": "dim", "FAILED": "red", "COMPLETED": "green"}
        sc = state_colors.get(state_name, "")

        trigger = ""
        if e.get("trigger_kind"):
            trigger = e["trigger_kind"]
            if e.get("trigger_detail"):
                trigger += f": {e['trigger_detail']}"

        hook = e.get("hook_summary") or ""
        deps = str(e.get("dep_count", 0)) if e.get("dep_count", 0) > 0 else ""
        sal = f"{round(e.get('salience', 0) * 100)}%"
        vis_names = {"PRIVATE": "priv", "INTERNAL": "intl", "OPEN": "open"}
        vis = vis_names.get(e.get("visibility_name", ""), "?")

        table.add_row(
            e.get("label", "?"),
            f"[{sc}]{state_name}[/{sc}]" if sc else state_name,
            e.get("entry_type_name", "?"),
            e.get("category", ""),
            trigger,
            hook,
            deps,
            sal,
            vis,
        )
    console.print(table)


@tl_app.command("state")
def timeline_state():
    """Show the timeline engine's current state and health."""
    session = _require_session()
    state = _api("GET", "/api/timeline/state", session=session)

    running = state.get("is_running", False)
    status_str = "[green]Running[/green]" if running else "[red]Stopped[/red]"
    console.print(f"[bold]Engine Status:[/bold] {status_str}")
    console.print(f"[bold]Tick:[/bold] #{state.get('tick_count', 0)}")
    console.print()

    console.print("[bold]Entry Counts:[/bold]")
    console.print(f"  Active:    {state.get('active_count', 0)}")
    console.print(f"  Pending:   {state.get('pending_count', 0)}")
    console.print(f"  Dormant:   {state.get('dormant_count', 0)}")
    console.print(f"  Failed:    {state.get('failed_count', 0)}")
    console.print(f"  Total:     {state.get('total_count', 0)}")

    signals = state.get("signals", [])
    if signals:
        console.print(f"\n[bold]Signals ({len(signals)}):[/bold]")
        for s in signals:
            sev = s.get("severity", "info")
            color = "yellow" if sev == "warning" else "red" if sev == "error" else "blue"
            console.print(f"  [{color}]{sev.upper()}[/{color}]: {s.get('message', '')}")


@tl_app.command("show")
def timeline_show(entry_id: str = typer.Argument(..., help="Entry ID (or prefix)")):
    """Show detailed info for a single timeline entry."""
    session = _require_session()
    # Fetch all entries and prefix-match
    entries = _api("GET", "/api/timeline/entries", session=session)
    matches = [e for e in entries if e["id"].startswith(entry_id)]
    if not matches:
        console.print(f"[red]No entry matching '{entry_id}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous prefix — {len(matches)} matches. Be more specific.[/yellow]")
        raise typer.Exit(1)

    e = matches[0]
    console.print(f"[bold]{e['label']}[/bold]")
    console.print(f"ID: {e['id']}")
    console.print(f"State: {e.get('state_name', '?')}  ({e.get('state', '?')})")
    console.print(f"Type: {e.get('entry_type_name', '?')}")
    console.print(f"Category: {e.get('category', '?')}")
    console.print(f"Visibility: {e.get('visibility_name', '?')}")
    console.print(f"Salience: {round(e.get('salience', 0) * 100)}%")

    if e.get("trigger_kind"):
        trigger_str = e["trigger_kind"]
        if e.get("trigger_detail"):
            trigger_str += f": {e['trigger_detail']}"
        console.print(f"Trigger: {trigger_str}")

    if e.get("hook_summary"):
        console.print(f"Hook: {e['hook_summary']}")

    if e.get("dep_count", 0) > 0:
        console.print(f"Dependencies: {e['dep_count']}")


@tl_app.command("tick")
def timeline_tick():
    """Manually advance the timeline engine by one tick."""
    session = _require_session()
    result = _api("POST", "/api/timeline/tick", session=session)
    console.print(f"[green]Tick #{result.get('tick_count', '?')}[/green]")
    next_wake = result.get("next_wake_at", 0)
    if next_wake > 0:
        import time as _time
        delta_sec = max(0, (next_wake - int(_time.time() * 1000)) // 1000)
        console.print(f"Next wake: in {delta_sec}s")


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
