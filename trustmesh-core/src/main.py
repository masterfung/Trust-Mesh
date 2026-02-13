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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, or_

from src.crypto import decrypt, derive_vault_key, public_key_to_b64
from src.database import async_session, init_db
from src.models import Agent, Connection, Network, NetworkMembership, User, parse_profile_data
from src.routes import audit, briefing, capsules, connections, emergency, intake, invites, networks, notifications, queries, services, tasks, users
from src.schemas import GraphEdge, GraphNetwork, GraphNode, GraphResponse

# In-memory vault key store (user_id -> decrypted vault master key)
# Populated at startup from seed data or on user login
vault_keys: dict[str, bytes] = {}

DEMO_PASSWORD = "TrustMesh-demo-2026"


async def _load_vault_keys():
    """Load vault keys for demo users only (seeded with known demo password).

    Non-demo users get their vault keys loaded on login via their real password.
    """
    async with async_session() as db:
        result = await db.execute(select(User).where(User.is_demo == True))  # noqa: E712
        for user in result.scalars().all():
            if user.vault_key_salt and user.encrypted_vault_key:
                try:
                    derived_key, _ = derive_vault_key(DEMO_PASSWORD, user.vault_key_salt)
                    master_key = decrypt(user.encrypted_vault_key, derived_key)
                    vault_keys[user.id] = master_key
                except Exception:
                    pass  # Skip users with bad keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB + load vault keys on startup."""
    await init_db()
    await _load_vault_keys()
    yield


app = FastAPI(
    title="TrustMesh Core",
    description="Trust-aware knowledge sharing for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3050", "http://localhost:3000"],
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


@app.post("/api/demo/warmup")
async def demo_warmup():
    """Reload vault keys for all demo users. Called by graph page before running scenarios."""
    await _load_vault_keys()
    return {"status": "ok", "keys_loaded": len(vault_keys)}


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

        # Nodes: only peers
        user_result = await db.execute(
            select(User).where(User.id.in_(peer_ids)).order_by(User.display_name)
        )
        visible_users = user_result.scalars().all()

        edges = [
            GraphEdge(source=c.from_user_id, target=c.to_user_id)
            for c in user_connections
        ]

        # Networks: only those user is a member of
        mem_result = await db.execute(
            select(NetworkMembership.network_id).where(NetworkMembership.user_id == user_id)
        )
        my_network_ids = set(mem_result.scalars().all())
    else:
        # Full graph: all users, connections, networks
        user_result = await db.execute(select(User).order_by(User.display_name))
        visible_users = user_result.scalars().all()

        conn_result = await db.execute(
            select(Connection).where(Connection.status == "accepted")
        )
        edges = [
            GraphEdge(source=c.from_user_id, target=c.to_user_id)
            for c in conn_result.scalars().all()
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
        graph_networks.append(GraphNetwork(
            id=n.id, name=n.name, network_type=n.network_type,
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


@app.get("/.well-known/agent.json")
async def agent_discovery():
    """A2A agent discovery endpoint — lists all agents with DIDs and capabilities."""
    async with async_session() as db:
        result = await db.execute(
            select(Agent, User).join(User, Agent.owner_id == User.id).order_by(User.display_name)
        )
        agents = []
        for agent, user in result.all():
            capabilities = ["knowledge-query", "trust-aware-sharing"]
            if user.user_type == "service":
                capabilities.extend(["quote-request", "availability-check"])
                # Check if this is a healthcare service (has medical skills in profile)
                pd = parse_profile_data(user.profile_data)
                if pd:
                    skill_categories = [s.get("category", "") for s in pd.get("skills", [])]
                    if "medical" in skill_categories:
                        capabilities.append("emergency-access")

            agents.append({
                "name": agent.name,
                "did": agent.did,
                "public_key_b64": public_key_to_b64(agent.public_key) if agent.public_key else None,
                "owner": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "user_type": user.user_type,
                },
                "capabilities": capabilities,
                "url": f"/api/users/{user.id}/agent/a2a",
                "protocol": "trustmesh/1.0",
            })

        return {
            "protocol": "trustmesh/1.0",
            "agents": agents,
            "total": len(agents),
        }
