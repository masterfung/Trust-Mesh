"""Pod federation routes — discovery, peering, and cross-pod queries."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.database import async_session
from src.federation import (
    POD_NAME,
    POD_URL,
    connect_to_peer,
    discover_remote_agents,
    get_pod_info,
    ping_peer,
)
from src.models import Agent, PeerPod, User

router = APIRouter(prefix="/api/pod", tags=["pod"])


# ── Schemas ──

class PeerConnectRequest(BaseModel):
    url: str


class RemoteQueryRequest(BaseModel):
    from_did: str
    from_pod: str
    to_username: str
    question: str


# ── This Pod ──

@router.get("")
async def pod_info():
    """Return this pod's identity, agents, and status. No auth required — public info."""
    return await get_pod_info()


# ── Peer Management ──

@router.get("/peers")
async def list_peers():
    """List all known peer pods."""
    async with async_session() as db:
        result = await db.execute(select(PeerPod).order_by(PeerPod.created_at))
        peers = result.scalars().all()
        return {
            "pod_name": POD_NAME,
            "pod_url": POD_URL,
            "peers": [
                {
                    "id": p.id,
                    "name": p.name,
                    "url": p.url,
                    "status": p.status,
                    "agent_count": p.agent_count,
                    "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in peers
            ],
        }


@router.post("/peers")
async def add_peer(req: PeerConnectRequest):
    """Connect to a peer pod. Bidirectional — also registers us with the peer."""
    peer_url = req.url.rstrip("/")

    # Don't connect to ourselves
    if peer_url == POD_URL:
        raise HTTPException(400, "Cannot peer with yourself")

    async with async_session() as db:
        pod = await connect_to_peer(db, peer_url)
        if not pod:
            raise HTTPException(502, f"Could not reach peer at {peer_url}")
        return {
            "status": "connected",
            "peer": {
                "id": pod.id,
                "name": pod.name,
                "url": pod.url,
                "agent_count": pod.agent_count,
                "status": pod.status,
            },
        }


@router.delete("/peers/{peer_id}")
async def remove_peer(peer_id: str):
    """Disconnect from a peer pod."""
    async with async_session() as db:
        result = await db.execute(select(PeerPod).where(PeerPod.id == peer_id))
        pod = result.scalar_one_or_none()
        if not pod:
            raise HTTPException(404, "Peer not found")
        await db.delete(pod)
        await db.commit()
        return {"status": "removed", "peer_url": pod.url}


@router.post("/peers/{peer_id}/ping")
async def ping_peer_endpoint(peer_id: str):
    """Ping a peer pod and update its status."""
    async with async_session() as db:
        result = await db.execute(select(PeerPod).where(PeerPod.id == peer_id))
        pod = result.scalar_one_or_none()
        if not pod:
            raise HTTPException(404, "Peer not found")

        info = await ping_peer(pod.url)
        if info:
            pod.status = "active"
            pod.agent_count = info.get("agent_count", 0)
            pod.last_seen_at = datetime.now(timezone.utc)
        else:
            pod.status = "unreachable"
        await db.commit()
        return {"status": pod.status, "info": info}


# ── Cross-Pod Discovery ──

@router.get("/discover")
async def discover_agents():
    """Discover agents across all connected peer pods + this pod.

    Returns a unified view of all agents in the federation.
    """
    # Local agents
    local_info = await get_pod_info()
    local_agents = local_info["agents"]
    for a in local_agents:
        a["_pod"] = {"name": POD_NAME, "url": POD_URL, "is_local": True}

    # Remote agents from peers
    async with async_session() as db:
        remote_agents = await discover_remote_agents(db)

    for a in remote_agents:
        if "_pod" in a:
            a["_pod"]["is_local"] = False

    return {
        "total": len(local_agents) + len(remote_agents),
        "local_count": len(local_agents),
        "remote_count": len(remote_agents),
        "agents": local_agents + remote_agents,
    }


# ── Cross-Pod Gossip ──

@router.post("/query")
async def receive_remote_query(req: RemoteQueryRequest):
    """Handle an incoming gossip query from a remote pod.

    The remote pod sends the querying agent's DID. We look up the target
    user locally and run the gossip pipeline. Remote queries without a local
    connection get 'public' trust level (only "open" capsules visible).
    """
    async with async_session() as db:
        # Find target user on this pod
        result = await db.execute(select(User).where(User.username == req.to_username))
        target_user = result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(404, f"User '{req.to_username}' not found on this pod")

        # Find the requesting agent by DID (may be on a remote pod)
        agent_result = await db.execute(select(Agent).where(Agent.did == req.from_did))
        requesting_agent = agent_result.scalar_one_or_none()

        if requesting_agent:
            # Agent exists locally (maybe they have an account here too) — use normal gossip
            from src.gossip import query_agent
            from src.main import vault_keys
            response = await query_agent(db, requesting_agent.owner_id, target_user.id, "What do you know?", vault_keys)
            return response
        else:
            # Remote agent — run gossip with public trust level
            from src.gossip import query_agent_public
            from src.main import vault_keys
            response = await query_agent_public(db, target_user.id, req.question, req.from_did, req.from_pod, vault_keys)
            return response
