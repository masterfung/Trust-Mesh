"""TrustMesh Core — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, or_

from src.crypto import decrypt, derive_vault_key
from src.database import async_session, init_db
from src.models import Connection, Network, NetworkMembership, User
from src.routes import capsules, connections, networks, queries, users
from src.schemas import GraphEdge, GraphNetwork, GraphNode, GraphResponse

# In-memory vault key store (user_id -> decrypted vault master key)
# Populated at startup from seed data or on user login
vault_keys: dict[str, bytes] = {}

DEMO_PASSWORD = "trustmesh-demo"


async def _load_vault_keys():
    """Load vault keys for all users using the demo password."""
    async with async_session() as db:
        result = await db.execute(select(User))
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
    allow_origins=["*"],
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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trustmesh-core"}


@app.get("/api/graph", response_model=GraphResponse)
async def get_graph():
    """Full trust graph: users as nodes, connections as edges, networks as groups."""
    async with async_session() as db:
        # Nodes: all users
        user_result = await db.execute(select(User).order_by(User.display_name))
        all_users = user_result.scalars().all()
        nodes = [
            GraphNode(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                bio=u.bio,
            )
            for u in all_users
        ]

        # Edges: accepted connections
        conn_result = await db.execute(
            select(Connection).where(Connection.status == "accepted")
        )
        all_connections = conn_result.scalars().all()
        edges = [
            GraphEdge(source=c.from_user_id, target=c.to_user_id)
            for c in all_connections
        ]

        # Networks with members
        net_result = await db.execute(select(Network))
        all_networks = net_result.scalars().all()
        graph_networks = []
        for n in all_networks:
            mem_result = await db.execute(
                select(NetworkMembership.user_id).where(
                    NetworkMembership.network_id == n.id
                )
            )
            member_ids = list(mem_result.scalars().all())
            graph_networks.append(
                GraphNetwork(
                    id=n.id,
                    name=n.name,
                    network_type=n.network_type,
                    members=member_ids,
                )
            )

        return GraphResponse(nodes=nodes, edges=edges, networks=graph_networks)
