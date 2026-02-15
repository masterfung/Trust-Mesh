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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, or_

from src.crypto import decrypt, decrypt_text, derive_vault_key, public_key_to_b64
from src.database import async_session, init_db
from src.models import Agent, Connection, KnowledgeCapsule, Network, NetworkMembership, User, parse_profile_data
from src.routes import audit, briefing, capsules, connections, emergency, fhir, intake, invites, networks, notifications, pin, pod, queries, registry, services, tasks, users
from src.schemas import GraphEdge, GraphNetwork, GraphNode, GraphResponse

# In-memory vault key store (user_id -> decrypted vault master key)
# Populated at startup from seed data or on user login
vault_keys: dict[str, bytes] = {}

# In-memory PIN auth tokens (token -> {user_id, expires_at, created_at})
# Short-lived (5 min) tokens for governance changes after PIN verification
pin_tokens: dict[str, dict] = {}

DEMO_PASSWORD = "TrustMesh-demo-2026"


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


async def _rebuild_embeddings():
    """Rebuild ChromaDB embeddings from DB for all users with loaded vault keys."""
    from src.embeddings import reset_collection, upsert_capsule_embedding

    reset_collection()
    async with async_session() as db:
        result = await db.execute(select(KnowledgeCapsule))
        count = 0
        for cap in result.scalars().all():
            vk = vault_keys.get(cap.owner_id)
            if not vk:
                continue
            try:
                text = decrypt_text(cap.content_encrypted, vk)
                upsert_capsule_embedding(
                    cap.id,
                    f"{cap.title}: {text}",
                    {"capsule_id": cap.id, "owner_id": cap.owner_id, "visibility": cap.visibility},
                )
                count += 1
            except Exception:
                pass
    print(f"Rebuilt {count} embeddings.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB + load vault keys + rebuild embeddings on startup."""
    import asyncio
    await init_db()
    await _load_vault_keys()
    await _rebuild_embeddings()
    # Auto-register discoverable agents with the public registry (fire-and-forget)
    from src.federation import sync_discoverable_agents_to_registry
    asyncio.create_task(sync_discoverable_agents_to_registry())
    yield


app = FastAPI(
    title="TrustMesh Core",
    description="Trust-aware knowledge sharing for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3050", "http://localhost:3000",
        # Multi-pod federation: allow cross-pod requests from any localhost port
        *[f"http://localhost:{p}" for p in range(8001, 8017)],
        "http://localhost:8100",  # Public registry
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(audit.router)
app.include_router(pin.router)
app.include_router(fhir.router)
app.include_router(pod.router)
app.include_router(registry.router)


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
        secure=False,
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
    net_result = await db.execute(net_query)
    graph_networks = []
    for n in net_result.scalars().all():
        mem_result = await db.execute(
            select(NetworkMembership.user_id).where(NetworkMembership.network_id == n.id)
        )
        # Parse shared_categories from JSON string
        shared_cats = None
        if n.shared_categories:
            import json as _json
            try:
                shared_cats = _json.loads(n.shared_categories) if isinstance(n.shared_categories, str) else n.shared_categories
            except (ValueError, TypeError):
                shared_cats = None
        graph_networks.append(GraphNetwork(
            id=n.id, name=n.name, network_type=n.network_type,
            pool_type=n.pool_type, shared_categories=shared_cats,
            members=list(mem_result.scalars().all()),
        ))

    return GraphResponse(nodes=nodes, edges=edges, networks=graph_networks)


@app.get("/api/graph", response_model=GraphResponse)
async def get_graph():
    """Full trust graph (demo/admin view): all users, connections, networks."""
    async with async_session() as db:
        return await _build_graph(db)


@app.get("/api/graph/{user_id}", response_model=GraphResponse)
async def get_user_graph(user_id: str):
    """User-scoped trust graph: only this user's connections and networks."""
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
