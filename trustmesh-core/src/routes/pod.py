"""Pod federation routes — discovery, peering, cross-pod queries, and A2A messaging."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from src.auth import get_current_user_id
from src.database import async_session
from src.federation import (
    POD_NAME,
    POD_URL,
    connect_to_peer,
    discover_remote_agents,
    get_or_create_ghost_user,
    get_pod_info,
    lookup_ghost_by_did,
    ping_peer,
    send_pool_invite,
)
from src.models import Agent, Connection, Network, NetworkMembership, PeerPod, PoolInviteToken, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pod", tags=["pod"])


# ── Schemas ──

class PeerConnectRequest(BaseModel):
    url: str


class RemoteQueryRequest(BaseModel):
    from_did: str
    from_pod: str
    to_username: str
    question: str


class A2AMessagePart(BaseModel):
    type: str = "text"
    text: str = ""


class A2AMessage(BaseModel):
    role: str = "user"
    parts: list[A2AMessagePart] = []


class A2AMetadata(BaseModel):
    from_did: str | None = None
    from_pod: str | None = None
    trust_context: str = "public"
    to_username: str | None = None


class A2AParams(BaseModel):
    message: A2AMessage
    metadata: A2AMetadata = A2AMetadata()


class A2ARequest(BaseModel):
    """A2A JSON-RPC compatible request."""
    jsonrpc: str = "2.0"
    method: str = "message/send"
    id: str | int | None = None
    params: A2AParams


class PoolInviteRequest(BaseModel):
    """Inbound pool invite from a remote pod."""
    network_id: str
    invite_token: str
    from_pod: str
    username: str
    display_name: str
    did: str


class PoolInviteSendRequest(BaseModel):
    """Outbound pool invite to a remote pod."""
    network_id: str
    target_pod_url: str
    target_username: str
    target_display_name: str
    target_did: str


GHOST_CAP_PER_NETWORK = 20


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
            response = await query_agent(db, requesting_agent.owner_id, target_user.id, req.question, vault_keys)
            return response

        # Check for ghost user with this DID — enables elevated trust for pool members
        ghost = await lookup_ghost_by_did(db, req.from_did)
        if ghost:
            # SECURITY: Verify requesting pod matches ghost's stored pod URL
            # Prevents Pod C from spoofing Pod B's DID to get Pod B's trust level
            if ghost.remote_pod_url and req.from_pod.rstrip("/") != ghost.remote_pod_url.rstrip("/"):
                logger.warning(
                    f"DID spoofing attempt: {req.from_did} claims pod {req.from_pod} "
                    f"but ghost registered from {ghost.remote_pod_url}"
                )
            else:
                # Ghost found + pod verified! Use full query_agent with ghost's user ID
                from src.gossip import query_agent
                from src.main import vault_keys
                response = await query_agent(db, ghost.id, target_user.id, req.question, vault_keys)
                return response

        # Remote agent with no ghost — public trust only
        from src.gossip import query_agent_public
        from src.main import vault_keys
        response = await query_agent_public(db, target_user.id, req.question, req.from_did, req.from_pod, vault_keys)
        return response


# ── A2A Protocol Endpoint ──

@router.post("/a2a")
async def a2a_message(req: A2ARequest):
    """A2A-compatible JSON-RPC message endpoint.

    This makes our agent card's URL actually functional. Any A2A-compatible
    agent can send messages here following the A2A protocol spec.

    Supported methods:
    - message/send: Send a message to an agent on this pod
    """
    if req.method != "message/send":
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32601, "message": f"Method '{req.method}' not supported"},
        }

    # Extract the text from the message parts
    text_parts = [p.text for p in req.params.message.parts if p.type == "text" and p.text]
    if not text_parts:
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32602, "message": "No text content in message"},
        }
    question = " ".join(text_parts)

    metadata = req.params.metadata
    from_did = metadata.from_did or "anonymous"

    async with async_session() as db:
        # If a target username is specified, query that user
        if metadata.to_username:
            result = await db.execute(select(User).where(User.username == metadata.to_username))
            target_user = result.scalar_one_or_none()
            if not target_user:
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "error": {"code": -32602, "message": f"User '{metadata.to_username}' not found"},
                }
        else:
            # No target specified — route to the first agent (pod default)
            result = await db.execute(select(User).order_by(User.created_at).limit(1))
            target_user = result.scalar_one_or_none()
            if not target_user:
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "error": {"code": -32602, "message": "No agents available on this pod"},
                }

        # Check if the requester has a local account (higher trust)
        agent_result = await db.execute(select(Agent).where(Agent.did == from_did))
        requesting_agent = agent_result.scalar_one_or_none()

        if requesting_agent:
            from src.gossip import query_agent
            from src.main import vault_keys
            response = await query_agent(db, requesting_agent.owner_id, target_user.id, question, vault_keys)
        else:
            # Check for ghost user (elevated trust via pool membership)
            ghost = await lookup_ghost_by_did(db, from_did)
            if ghost:
                from src.gossip import query_agent
                from src.main import vault_keys
                response = await query_agent(db, ghost.id, target_user.id, question, vault_keys)
            else:
                from src.gossip import query_agent_public
                from src.main import vault_keys
                response = await query_agent_public(db, target_user.id, question, from_did, "a2a", vault_keys)

    # Format as A2A Task response
    return {
        "jsonrpc": "2.0",
        "id": req.id,
        "result": {
            "id": response.get("id", "task-1"),
            "status": {
                "state": "completed" if response.get("decision") != "denied" else "failed",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": response.get("response", "")}],
                },
            },
            "metadata": {
                "trust_level": response.get("trust_level", "public"),
                "decision": response.get("decision", "allowed"),
                "latency_ms": response.get("latency_ms", 0),
                "pod_name": POD_NAME,
                "pod_url": POD_URL,
            },
        },
    }


# ── Cross-Pod Pool Invitations ──

async def _create_ghost_connections(db, ghost_user_id: str, network_id: str):
    """Create auto-accepted connections between a ghost user and all local members of a network.

    This is what makes resolve_trust_level() return "network" trust for the ghost.
    """
    # Get all local (non-ghost) members of this network
    result = await db.execute(
        select(NetworkMembership.user_id).where(NetworkMembership.network_id == network_id)
    )
    member_ids = set(result.scalars().all())
    member_ids.discard(ghost_user_id)  # Don't connect to self

    now = datetime.now(timezone.utc)
    for member_id in member_ids:
        # Check if connection already exists
        existing = await db.execute(
            select(Connection).where(
                ((Connection.from_user_id == ghost_user_id) & (Connection.to_user_id == member_id))
                | ((Connection.from_user_id == member_id) & (Connection.to_user_id == ghost_user_id))
            )
        )
        if existing.scalar_one_or_none():
            continue
        conn = Connection(
            from_user_id=ghost_user_id,
            to_user_id=member_id,
            context="both",
            status="accepted",
            accepted_at=now,
        )
        db.add(conn)


@router.post("/pool-invite")
async def receive_pool_invite(req: PoolInviteRequest):
    """Receive a pool invitation from a remote pod.

    Creates a ghost user for the remote sender and adds them to the specified
    network with auto-accepted connections to all local members.
    """
    async with async_session() as db:
        # Verify invite token exists and is valid
        token_result = await db.execute(
            select(PoolInviteToken).where(
                PoolInviteToken.token == req.invite_token,
                PoolInviteToken.status == "pending",
            )
        )
        invite_token = token_result.scalar_one_or_none()
        if not invite_token:
            raise HTTPException(403, "Invalid or expired invite token")

        # Check expiry (handle both tz-aware and naive datetimes from SQLite)
        expires = invite_token.expires_at
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            invite_token.status = "expired"
            await db.commit()
            raise HTTPException(403, "Invite token has expired")

        # Verify the network exists locally
        net_result = await db.execute(
            select(Network).where(Network.id == invite_token.network_id)
        )
        network = net_result.scalar_one_or_none()
        if not network:
            raise HTTPException(404, "Network not found")

        # Check ghost cap
        ghost_count = await db.execute(
            select(func.count()).select_from(NetworkMembership).join(
                User, NetworkMembership.user_id == User.id
            ).where(
                NetworkMembership.network_id == network.id,
                User.is_remote == True,  # noqa: E712
            )
        )
        if ghost_count.scalar() >= GHOST_CAP_PER_NETWORK:
            raise HTTPException(429, f"Network has reached the maximum of {GHOST_CAP_PER_NETWORK} remote members")

        # Create or get ghost user
        ghost = await get_or_create_ghost_user(
            db, req.username, req.display_name, req.did, req.from_pod
        )

        # Add ghost to network if not already a member
        existing_mem = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.network_id == network.id,
                NetworkMembership.user_id == ghost.id,
            )
        )
        if not existing_mem.scalar_one_or_none():
            membership = NetworkMembership(
                network_id=network.id,
                user_id=ghost.id,
                role="remote_member",
            )
            db.add(membership)
            await db.flush()

        # Create auto-accepted connections with all local members
        await _create_ghost_connections(db, ghost.id, network.id)

        # Consume the invite token
        invite_token.status = "consumed"

        await db.commit()

        return {
            "status": "accepted",
            "ghost_user_id": ghost.id,
            "network_name": network.name,
        }


@router.post("/pool-invite/send")
async def send_pool_invite_endpoint(
    req: PoolInviteSendRequest,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Send a pool invitation to a remote user on another pod.

    1. Verifies auth user is a member of the network
    2. Generates a one-time invite token for the remote pod
    3. Creates a ghost user locally for the remote user
    4. Sends the invite to the remote pod (they create a ghost for us)
    """
    async with async_session() as db:
        # Verify the user is a member of the network
        mem_result = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.network_id == req.network_id,
                NetworkMembership.user_id == auth_user_id,
            )
        )
        if not mem_result.scalar_one_or_none():
            raise HTTPException(403, "You are not a member of this network")

        # Get network info
        net_result = await db.execute(
            select(Network).where(Network.id == req.network_id)
        )
        network = net_result.scalar_one_or_none()
        if not network:
            raise HTTPException(404, "Network not found")

        # Generate one-time invite token for the remote pod to call us back
        token_str = secrets.token_hex(32)
        invite_token = PoolInviteToken(
            network_id=req.network_id,
            token=token_str,
            target_pod_url=req.target_pod_url.rstrip("/"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(invite_token)

        # Create ghost user locally for the remote user
        ghost = await get_or_create_ghost_user(
            db, req.target_username, req.target_display_name,
            req.target_did, req.target_pod_url,
        )

        # Add ghost to network if not already a member
        existing_mem = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.network_id == req.network_id,
                NetworkMembership.user_id == ghost.id,
            )
        )
        if not existing_mem.scalar_one_or_none():
            membership = NetworkMembership(
                network_id=req.network_id,
                user_id=ghost.id,
                role="remote_member",
            )
            db.add(membership)
            await db.flush()

        # Create auto-accepted connections with local members
        await _create_ghost_connections(db, ghost.id, req.network_id)

        await db.commit()

        # Get local user info to send to the remote pod
        user_result = await db.execute(select(User).where(User.id == auth_user_id))
        local_user = user_result.scalar_one()
        agent_result = await db.execute(select(Agent).where(Agent.owner_id == auth_user_id))
        local_agent = agent_result.scalar_one_or_none()

        # Send invite to remote pod (they'll create a ghost for us)
        remote_result = await send_pool_invite(
            req.target_pod_url,
            req.network_id,
            token_str,
            local_user.username,
            local_user.display_name,
            local_agent.did if local_agent else "",
        )

        return {
            "status": "sent",
            "ghost_user_id": ghost.id,
            "network_name": network.name,
            "remote_acknowledged": remote_result is not None,
            "invite_token": token_str,
        }
