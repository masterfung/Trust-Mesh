"""TrustMesh Core — FastAPI application entry point."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (one level up from trustmesh-core/)
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Fallback: try trustmesh-core/.env
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.auth import get_current_user_id

from src.csrf import CSRFMiddleware
from src.middleware import ProxySecretMiddleware, RateLimitHeadersMiddleware
from sqlalchemy import select, or_

from src.crypto import decrypt, derive_vault_key, public_key_to_b64
from src.database import async_session, init_db
from src.models import Agent, Connection, KnowledgeCapsule, Network, NetworkMembership, User, parse_profile_data
from src.routes import _internal, audit, briefing, capsules, channels, connections, emergency, fhir, intake, invites, live, memory, messages, networks, notifications, pin, pod, queries, registry, research, services, tasks, timeline, users
from src.schemas import GraphEdge, GraphNetwork, GraphNode, GraphResponse

# Transit-backed vault key store. Keys live in Zig memory (secureZero on removal).
# This dict-like wrapper delegates to the transit bridge for backward compat.
from src import transit_bridge as _transit


class _TransitKeyStore:
    """Dict-like wrapper around the Zig transit engine.

    Supports `vault_keys[uid]`, `vault_keys.get(uid)`, `uid in vault_keys`,
    `vault_keys.pop(uid)`, and `len(vault_keys)`.

    Keys are stored in Zig; __getitem__ raises KeyError (never returns raw key).
    Callers should use transit_bridge.encrypt()/decrypt() instead.
    """

    def __init__(self):
        self._user_ids: set[str] = set()

    def __setitem__(self, user_id: str, key: bytes):
        _transit._ensure_init()
        _transit.store_key(user_id, key)
        self._user_ids.add(user_id)
        # Best-effort zero the Python copy
        _transit._zero_bytes(key)

    def __contains__(self, user_id: str) -> bool:
        _transit._ensure_init()
        return _transit.has_key(user_id)

    def get(self, user_id: str, default=None):
        """Return a sentinel that signals 'key is available' or default.

        LEGACY COMPAT: Some code paths check `vault_keys.get(uid)` for truthiness.
        We return a non-None sentinel bytes object (not the real key).
        The actual encrypt/decrypt should go through transit_bridge.
        """
        _transit._ensure_init()
        if _transit.has_key(user_id):
            return b"__transit__"  # sentinel — not the real key
        return default

    def pop(self, user_id: str, *args):
        _transit._ensure_init()
        had = _transit.has_key(user_id)
        _transit.remove_user(user_id)
        self._user_ids.discard(user_id)
        if had:
            return b"__transit__"
        if args:
            return args[0]
        raise KeyError(user_id)

    def clear(self):
        """Remove all keys from transit engine (secureZero each)."""
        _transit._ensure_init()
        for uid in list(self._user_ids):
            _transit.remove_user(uid)
        self._user_ids.clear()

    def __len__(self):
        return len(self._user_ids)

    def __repr__(self):
        return f"<TransitKeyStore users={len(self._user_ids)}>"


vault_keys: dict[str, bytes] = _TransitKeyStore()  # type: ignore[assignment]

# Pod-level Key Encryption Key — used to encrypt messages for offline recipients.
# Re-encryption with the recipient's vault key happens on their next login.
# Loaded/generated once at startup, never leaves Python memory.
_POD_KEK: bytes = b""

# In-memory PIN auth tokens (token -> {user_id, expires_at, created_at})
# Short-lived (5 min) tokens for governance changes after PIN verification
pin_tokens: dict[str, dict] = {}

DEMO_PASSWORD = "TrustMesh-demo-2026"


def _init_pod_kek() -> None:
    """Load pod KEK from disk, or generate and persist a new one."""
    global _POD_KEK
    import base64
    import secrets

    env_kek = os.getenv("TRUSTMESH_POD_KEK")
    if env_kek:
        _POD_KEK = base64.b64decode(env_kek)
        return

    kek_path = Path(os.getenv("TRUSTMESH_DB", "./trustmesh.db")).parent / "pod_kek.bin"
    if kek_path.exists():
        _POD_KEK = kek_path.read_bytes()
    else:
        _POD_KEK = secrets.token_bytes(32)
        kek_path.write_bytes(_POD_KEK)


async def _load_vault_keys():
    """Load vault keys for demo users only (seeded with known demo password).

    Non-demo users get their vault keys loaded on login via their real password.
    """
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.is_demo == True, User.is_remote == False)  # noqa: E712
        )
        for user in result.scalars().all():
            if user.vault_key_salt and user.encrypted_vault_key:
                try:
                    derived_key, _ = derive_vault_key(DEMO_PASSWORD, user.vault_key_salt)
                    master_key = decrypt(user.encrypted_vault_key, derived_key)
                    vault_keys[user.id] = master_key
                except Exception:
                    pass  # Skip users with bad keys


async def _init_fts_index():
    """Initialize FTS5 index and rebuild from DB for all users with loaded vault keys."""
    from src.embeddings import init_fts, reset_collections, upsert_capsule_embedding

    db_path = os.getenv("TRUSTMESH_DB", "./trustmesh.db")
    init_fts(db_path)
    reset_collections()
    async with async_session() as db:
        result = await db.execute(select(KnowledgeCapsule))
        count = 0
        for cap in result.scalars().all():
            if not _transit.has_key(cap.owner_id):
                continue
            try:
                text = _transit.decrypt_text(cap.owner_id, cap.content_encrypted)
                upsert_capsule_embedding(
                    cap.id,
                    f"{cap.title}: {text}",
                    {"capsule_id": cap.id, "owner_id": cap.owner_id, "visibility": cap.visibility},
                    category=cap.category or "general",
                )
                count += 1
            except Exception:
                pass
    print(f"Indexed {count} capsules in FTS5.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB + load vault keys + build FTS5 index + Zig subsystems."""
    import asyncio
    await init_db()
    # Initialize transit engine before loading vault keys
    _transit.init()
    await _load_vault_keys()
    await _init_fts_index()
    # Initialize Zig session store and rate limiter
    from src.auth import _init_sessions
    from src.rate_limit import _init_rate_limits
    from src.trust import set_db_handle
    from src.embeddings import _db_handle as fts_db_handle
    _init_sessions()
    _init_rate_limits()
    set_db_handle(fts_db_handle)
    # Initialize credential store tables (idempotent)
    from src.credential_bridge import init_tables as credential_init_tables
    credential_init_tables()
    # Initialize message store tables (idempotent) + load/generate pod KEK
    from src.message_bridge import init_tables as message_init_tables
    message_init_tables()
    _init_pod_kek()
    # Auto-register discoverable agents with the public registry (save handle for clean shutdown)
    from src.federation import sync_discoverable_agents_to_registry
    _sync_task = asyncio.create_task(sync_discoverable_agents_to_registry())
    # Start the PodOS Timeline auto-tick loop (fire-and-forget)
    from src.routes.timeline import start_auto_tick
    asyncio.create_task(start_auto_tick())
    # Start data lifecycle loop (capsule expiry, auto-archive)
    from src.lifecycle import start_lifecycle_loop
    asyncio.create_task(start_lifecycle_loop())
    # Log active model stack on startup
    import logging as _logging
    _log = _logging.getLogger(__name__)
    from src.model_router import get_router as _get_router
    _router = _get_router()
    _log.info(
        "Model stack — main: %s  tee: %s",
        "gemini-3.1-pro-preview" if _router.has_gemini else "claude-sonnet-4-6",
        _router.tee_provider_name or "none (sensitive → anthropic fallback)",
    )
    yield
    # Shutdown: cancel the registry-sync task if still running
    _sync_task.cancel()
    try:
        await _sync_task
    except (asyncio.CancelledError, Exception):
        pass
    # Shutdown: stop the timeline engine and Zig subsystems
    from src.routes.timeline import stop_auto_tick
    await stop_auto_tick()
    from src.lifecycle import stop_lifecycle_loop
    await stop_lifecycle_loop()
    from src.auth import _deinit_sessions
    from src.rate_limit import _deinit_rate_limits
    _deinit_sessions()
    _deinit_rate_limits()
    from src.citadel import close_citadel_client
    await close_citadel_client()
    _transit.deinit()


app = FastAPI(
    title="TrustMesh Core",
    description="Trust-aware knowledge sharing for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitHeadersMiddleware)
app.add_middleware(ProxySecretMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3050", "http://localhost:3000",
        "http://127.0.0.1:3050", "http://127.0.0.1:3000",  # Explicit IPv4 (Chrome may use 127.0.0.1)
        "http://localhost:9000",  # User's own pod
        "http://127.0.0.1:9000",
        # Multi-pod federation: allow cross-pod requests from any localhost port
        *[f"http://localhost:{p}" for p in range(9001, 9017)],
        *[f"http://127.0.0.1:{p}" for p in range(9001, 9017)],
        "http://localhost:9100",  # Public registry
        "http://127.0.0.1:9100",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-Pool-Sync-Secret", "Cookie"],
    max_age=3600,
)

# Register route modules
app.include_router(users.router)
app.include_router(connections.router)
app.include_router(networks.router)
app.include_router(capsules.router)
app.include_router(queries.router)
app.include_router(tasks.router)
app.include_router(notifications.router)
app.include_router(briefing.router)
app.include_router(services.router)
app.include_router(invites.router)
app.include_router(intake.router)
app.include_router(emergency.router)
app.include_router(emergency.beacon_router)
app.include_router(audit.router)
app.include_router(pin.router)
app.include_router(fhir.router)
app.include_router(pod.router)
app.include_router(registry.router)
app.include_router(timeline.router)
app.include_router(live.router)
app.include_router(messages.router)
app.include_router(research.router)
app.include_router(channels.router)
app.include_router(memory.router)
app.include_router(_internal.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' "
        "https://agent.tinyfish.ai "
        "https://generativelanguage.googleapis.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    if not os.getenv("TRUSTMESH_DEV_MODE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.post("/api/demo/warmup")
async def demo_warmup(request: Request):
    """Reload vault keys for all demo users and ensure a demo session exists.

    Called by graph page before running scenarios.  If the caller has no valid
    session, we auto-login as the first demo user (peter) so that subsequent
    /api/query calls don't 401.
    """
    from fastapi.responses import JSONResponse
    from src.auth import COOKIE_NAME, create_session, get_session_token, validate_session

    await _load_vault_keys()

    # Check if caller already has a valid session
    token = get_session_token(request)
    existing_user = validate_session(token) if token else None

    if existing_user:
        return {"status": "ok", "keys_loaded": len(vault_keys)}

    # No session — auto-login as first demo user
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.is_demo == True).order_by(User.display_name).limit(1)  # noqa: E712
        )
        demo_user = result.scalar_one_or_none()

    if not demo_user:
        return {"status": "ok", "keys_loaded": len(vault_keys)}

    session_token = create_session(demo_user.id)
    response = JSONResponse(content={
        "status": "ok",
        "keys_loaded": len(vault_keys),
        "auto_login": demo_user.username,
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=not os.getenv("TRUSTMESH_DEV_MODE"),
        max_age=86400,
        path="/",
    )
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trustmesh-core"}


@app.get("/health/full")
async def health_full():
    """Detailed health check showing provider status."""
    from src.model_router import get_router
    from src import citadel as citadel_mod

    router = get_router()
    citadel_up = await citadel_mod.is_citadel_available()

    return {
        "status": "ok",
        "service": "trustmesh-core",
        "providers": {
            "gemini": router.has_gemini,
            "anthropic": bool(router._anthropic),
            "tee": {
                "enabled": router.has_tee,
                "provider": router.tee_provider_name,
            },
            "tavily": bool(os.getenv("TAVILY_API_KEY")),
            "citadel": {
                "configured": bool(os.getenv("CITADEL_URL")),
                "reachable": citadel_up,
                "heuristic_active": True,  # Heuristic fallback is always available
                "active": citadel_up or True,  # Scanning is always active (sidecar or heuristic)
            },
            "google_oauth": bool(os.getenv("GOOGLE_CLIENT_ID")),
        },
    }


async def _build_graph(db, user_id: str | None = None) -> GraphResponse:
    """Build trust graph. If user_id is given, scope to that user's connections and networks only."""

    if user_id:
        # Scoped graph: only nodes connected to this user + networks they belong to
        conn_result = await db.execute(
            select(Connection).where(
                Connection.status == "accepted",
                or_(Connection.from_user_id == user_id, Connection.to_user_id == user_id),
            )
        )
        user_connections = conn_result.scalars().all()

        # Collect all peer IDs + self
        peer_ids = {user_id}
        for c in user_connections:
            peer_ids.add(c.from_user_id)
            peer_ids.add(c.to_user_id)

        # Nodes: only local peers (exclude ghost users from graph)
        user_result = await db.execute(
            select(User).where(
                User.id.in_(peer_ids),
                User.is_remote == False,  # noqa: E712
            ).order_by(User.display_name)
        )
        visible_users = user_result.scalars().all()

        visible_ids = {u.id for u in visible_users}
        edges = [
            GraphEdge(source=c.from_user_id, target=c.to_user_id)
            for c in user_connections
            if c.from_user_id in visible_ids and c.to_user_id in visible_ids
        ]

        # Networks: only those user is a member of
        mem_result = await db.execute(
            select(NetworkMembership.network_id).where(NetworkMembership.user_id == user_id)
        )
        my_network_ids = set(mem_result.scalars().all())
    else:
        # Full graph: all local users (exclude ghost/remote users)
        user_result = await db.execute(
            select(User).where(User.is_remote == False).order_by(User.display_name)  # noqa: E712
        )
        visible_users = user_result.scalars().all()

        visible_ids = {u.id for u in visible_users}
        conn_result = await db.execute(
            select(Connection).where(Connection.status == "accepted")
        )
        edges = [
            GraphEdge(source=c.from_user_id, target=c.to_user_id)
            for c in conn_result.scalars().all()
            if c.from_user_id in visible_ids and c.to_user_id in visible_ids
        ]
        my_network_ids = None  # show all

    nodes = []
    for u in visible_users:
        profile = parse_profile_data(u.profile_data)
        nodes.append(GraphNode(
            id=u.id, username=u.username, display_name=u.display_name,
            bio=u.bio, user_type=u.user_type, profile_data=profile,
        ))

    # Networks with members
    net_query = select(Network)
    if my_network_ids is not None:
        if not my_network_ids:
            return GraphResponse(nodes=nodes, edges=edges, networks=[])
        net_query = net_query.where(Network.id.in_(my_network_ids))
    networks = (await db.execute(net_query)).scalars().all()

    # Batch-fetch all memberships in one query (avoids N+1)
    net_ids = [n.id for n in networks]
    members_by_network: dict[str, list[str]] = {n.id: [] for n in networks}
    if net_ids:
        all_mems = await db.execute(
            select(NetworkMembership.network_id, NetworkMembership.user_id)
            .where(NetworkMembership.network_id.in_(net_ids))
        )
        for net_id, user_id in all_mems.all():
            members_by_network[net_id].append(user_id)

    import json as _json
    graph_networks = []
    for n in networks:
        shared_cats = None
        if n.shared_categories:
            try:
                shared_cats = _json.loads(n.shared_categories) if isinstance(n.shared_categories, str) else n.shared_categories
            except (ValueError, TypeError):
                shared_cats = None
        graph_networks.append(GraphNetwork(
            id=n.id, name=n.name, network_type=n.network_type,
            pool_type=n.pool_type, shared_categories=shared_cats,
            members=members_by_network.get(n.id, []),
        ))

    return GraphResponse(nodes=nodes, edges=edges, networks=graph_networks)


@app.get("/api/graph", response_model=GraphResponse)
async def get_graph():
    """Full trust graph — public endpoint for demo visualization."""
    async with async_session() as db:
        return await _build_graph(db)


@app.get("/api/graph/{user_id}", response_model=GraphResponse)
async def get_user_graph(user_id: str):
    """User-scoped trust graph — public endpoint for demo visualization."""
    async with async_session() as db:
        return await _build_graph(db, user_id=user_id)


async def _build_agent_card() -> dict:
    """Build A2A-compatible agent card for this pod."""
    from src.federation import POD_NAME, POD_URL

    async with async_session() as db:
        result = await db.execute(
            select(Agent, User).join(User, Agent.owner_id == User.id).order_by(User.display_name)
        )
        skills = []
        first_agent = None
        for agent, user in result.all():
            if not first_agent:
                first_agent = (agent, user)

            skill = {
                "id": f"agent-{user.username}",
                "name": f"{user.display_name}'s Knowledge",
                "description": f"Query {user.display_name}'s shared knowledge (trust-level dependent)",
            }
            skills.append(skill)

            if user.user_type in ("service", "organization"):
                pd = parse_profile_data(user.profile_data)
                if pd:
                    skill_categories = [s.get("category", "") for s in pd.get("skills", [])]
                    if "medical" in skill_categories:
                        skills.append({
                            "id": f"emergency-{user.username}",
                            "name": "Emergency Medical Access",
                            "description": f"UCAN-authorized emergency access to {user.display_name}'s health data",
                        })

        # Build A2A-compatible agent card
        pod_did = first_agent[0].did if first_agent else None
        pod_pubkey = public_key_to_b64(first_agent[0].public_key) if first_agent and first_agent[0].public_key else None

        return {
            "name": f"{POD_NAME} Agent",
            "description": f"TrustMesh pod agent for {POD_NAME}",
            "url": f"{POD_URL}/api/pod/a2a",
            "version": "0.1.0",
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
            },
            "authentication": {
                "schemes": ["ucan", "session"],
            },
            "skills": skills,
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "trustmesh": {
                "pod_name": POD_NAME,
                "pod_url": POD_URL,
                "protocol": "trustmesh/0.1",
                "did": pod_did,
                "public_key_b64": pod_pubkey,
                "agent_count": len(skills),
            },
        }


@app.get("/.well-known/agent-card.json")
async def agent_card():
    """A2A-compatible agent card — the primary discovery endpoint for federation."""
    return await _build_agent_card()


@app.get("/.well-known/agent.json")
async def agent_discovery():
    """Legacy agent discovery endpoint — redirects to A2A agent card."""
    return await _build_agent_card()
