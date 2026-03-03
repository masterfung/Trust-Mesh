"""Pod federation routes — discovery, peering, cross-pod queries, and A2A messaging."""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.auth import get_current_user_id
from src.database import async_session, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from src.federation import (
    POD_NAME,
    POD_URL,
    cleanup_ghosts_for_pod,
    connect_to_peer,
    discover_remote_agents,
    get_or_create_ghost_user,
    get_pod_info,
    lookup_ghost_by_did,
    ping_peer,
    send_pool_invite,
)
from src.models import Agent, Connection, Network, NetworkMembership, PeerPod, PoolInviteToken, User
from src.rate_limit import check_query_rate, record_query
from src.federation_auth import verify_federation_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pod", tags=["pod"])

MAX_QUESTION_CHARS = 2000
MAX_DID_CHARS = 100
MAX_POD_URL_CHARS = 500


# ── Schemas ──

class PeerConnectRequest(BaseModel):
    url: str


class RemoteQueryRequest(BaseModel):
    from_did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)
    from_pod: str = Field(..., min_length=1, max_length=MAX_POD_URL_CHARS)
    to_username: str = Field(..., min_length=1, max_length=50)
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)


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
    network_id: str = Field(..., min_length=1, max_length=36)
    invite_token: str = Field(..., min_length=1, max_length=128)
    from_pod: str = Field(..., min_length=1, max_length=MAX_POD_URL_CHARS)
    username: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)


class PoolInviteSendRequest(BaseModel):
    """Outbound pool invite to a remote pod."""
    network_id: str = Field(..., min_length=1, max_length=36)
    target_pod_url: str = Field(..., min_length=1, max_length=MAX_POD_URL_CHARS)
    target_username: str = Field(..., min_length=1, max_length=50)
    target_display_name: str = Field(..., min_length=1, max_length=100)
    target_did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)


GHOST_CAP_PER_NETWORK = 20
MAX_GHOSTS_PER_POD = 100
POOL_SYNC_SECRET = os.getenv("TRUSTMESH_POOL_SYNC_SECRET", "")


async def require_auth_or_federation_secret(request: Request) -> str:
    """Accept EITHER session cookie auth OR X-Pool-Sync-Secret header.

    This lets peer mutation endpoints work for both:
    - Local users (authenticated via session cookie)
    - The orchestrator / peer pods (authenticated via shared secret)
    """
    # Try session auth first
    from src.auth import validate_session, get_session_token
    token = get_session_token(request)
    if token:
        user_id = validate_session(token)
        if user_id:
            return user_id

    # Fall back to federation secret
    if POOL_SYNC_SECRET:
        auth_header = request.headers.get("X-Pool-Sync-Secret", "")
        if secrets.compare_digest(auth_header, POOL_SYNC_SECRET):
            return "__federation__"

    raise HTTPException(401, "Authentication required (session or federation secret)")


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
async def add_peer(req: PeerConnectRequest, auth_id: str = Depends(require_auth_or_federation_secret)):
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
async def remove_peer(peer_id: str, auth_id: str = Depends(require_auth_or_federation_secret)):
    """Disconnect from a peer pod and clean up ghost users from that pod."""
    async with async_session() as db:
        result = await db.execute(select(PeerPod).where(PeerPod.id == peer_id))
        pod = result.scalar_one_or_none()
        if not pod:
            raise HTTPException(404, "Peer not found")
        # Clean up ghost users from this peer pod
        cleanup_stats = await cleanup_ghosts_for_pod(db, pod.url)
        await db.delete(pod)
        await db.commit()
        return {"status": "removed", "peer_url": pod.url, "cleanup": cleanup_stats}


@router.post("/peers/{peer_id}/ping")
async def ping_peer_endpoint(peer_id: str, auth_id: str = Depends(require_auth_or_federation_secret)):
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
async def receive_remote_query(req: RemoteQueryRequest, request: Request):
    """Handle an incoming gossip query from a remote pod.

    The remote pod sends the querying agent's DID. We look up the target
    user locally and run the gossip pipeline. Remote queries without a local
    connection get 'public' trust level (only "open" capsules visible).
    """
    # SECURITY: Dual rate limit by DID and source IP to prevent DID rotation bypass.
    client_ip = request.client.host if request.client else "unknown"
    async with async_session() as db:
        # Find target user on this pod
        result = await db.execute(select(User).where(User.username == req.to_username))
        target_user = result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(404, f"User '{req.to_username}' not found on this pod")

        # SECURITY: Rate limit inbound cross-pod queries by DID
        rate_ok, rate_reason = check_query_rate(req.from_did, target_user.id, "public")
        if not rate_ok:
            raise HTTPException(429, rate_reason)
        record_query(req.from_did, target_user.id)

        # SECURITY: Also rate limit by source IP (best-effort)
        ip_rate_ok, ip_rate_reason = check_query_rate(f"ip:{client_ip}", target_user.id, "public")
        if not ip_rate_ok:
            raise HTTPException(429, ip_rate_reason)
        record_query(f"ip:{client_ip}", target_user.id)

        # Find the requesting agent by DID (may be on a remote pod)
        agent_result = await db.execute(select(Agent).where(Agent.did == req.from_did))
        requesting_agent = agent_result.scalar_one_or_none()

        if requesting_agent:
            # Agent exists locally (maybe they have an account here too) — use normal gossip
            from src.gossip import query_agent
            response = await query_agent(db, requesting_agent.owner_id, target_user.id, req.question)
            if isinstance(response, dict):
                response["pod_name"] = POD_NAME
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
                raise HTTPException(403, "DID spoofing detected: pod URL mismatch")
            else:
                # SECURITY: Ghost trust elevation requires a valid signature proving
                # the caller controls the from_did key (prevents arbitrary DID spoofing).
                if not ghost.remote_pod_url:
                    logger.warning(f"Ghost {ghost.id} missing remote_pod_url; refusing trust elevation")
                    from src.gossip import query_agent_public
                    response = await query_agent_public(
                        db, target_user.id, req.question, req.from_did, req.from_pod
                    )
                    if isinstance(response, dict):
                        response["pod_name"] = POD_NAME
                    return response

                raw_body = await request.body()
                auth = verify_federation_request(from_did=req.from_did, body=raw_body, headers=request.headers)
                if auth.status == "missing":
                    # Backward-compatible: unsigned federation requests stay public.
                    from src.gossip import query_agent_public
                    response = await query_agent_public(
                        db, target_user.id, req.question, req.from_did, req.from_pod
                    )
                    if isinstance(response, dict):
                        response["pod_name"] = POD_NAME
                    return response
                if auth.status != "valid":
                    raise HTTPException(403, f"Invalid federation signature: {auth.reason or 'invalid'}")

                # Ghost found + pod verified + signature valid — use full query_agent with ghost's user ID
                from src.gossip import query_agent
                response = await query_agent(db, ghost.id, target_user.id, req.question)
                if isinstance(response, dict):
                    response["pod_name"] = POD_NAME
                return response

        # Remote agent with no ghost — public trust only
        from src.gossip import query_agent_public
        response = await query_agent_public(db, target_user.id, req.question, req.from_did, req.from_pod)
        if isinstance(response, dict):
            response["pod_name"] = POD_NAME
        return response


# ── A2A Protocol Endpoint ──

@router.post("/a2a")
async def a2a_message(req: A2ARequest, request: Request):
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
    if len(question) > MAX_QUESTION_CHARS:
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32602, "message": f"Message too long (max {MAX_QUESTION_CHARS} chars)"},
        }

    metadata = req.params.metadata
    from_did = metadata.from_did or "anonymous"

    # SECURITY: Dual rate limit by DID and source IP to prevent DID rotation bypass.
    client_ip = request.client.host if request.client else "unknown"

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

        # SECURITY: Rate limit inbound A2A messages by DID
        rate_ok, rate_reason = check_query_rate(from_did, target_user.id, "public")
        if not rate_ok:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32000, "message": rate_reason},
            }
        record_query(from_did, target_user.id)

        # SECURITY: Also rate limit by source IP (best-effort)
        ip_rate_ok, ip_rate_reason = check_query_rate(f"ip:{client_ip}", target_user.id, "public")
        if not ip_rate_ok:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32000, "message": ip_rate_reason},
            }
        record_query(f"ip:{client_ip}", target_user.id)

        # Check if the requester has a local account (higher trust)
        agent_result = await db.execute(select(Agent).where(Agent.did == from_did))
        requesting_agent = agent_result.scalar_one_or_none()

        if requesting_agent:
            from src.gossip import query_agent
            response = await query_agent(db, requesting_agent.owner_id, target_user.id, question)
        else:
            # Check for ghost user (elevated trust via pool membership)
            ghost = await lookup_ghost_by_did(db, from_did)
            if ghost:
                # SECURITY: Verify requesting pod matches ghost's stored pod URL
                from_pod = metadata.from_pod or ""
                if ghost.remote_pod_url and from_pod.rstrip("/") != ghost.remote_pod_url.rstrip("/"):
                    logger.warning(
                        f"A2A DID spoofing: {from_did} claims {from_pod}, "
                        f"ghost registered from {ghost.remote_pod_url}"
                    )
                    # Fall through to public trust (don't use ghost elevation)
                    from src.gossip import query_agent_public
                    response = await query_agent_public(db, target_user.id, question, from_did, "a2a")
                else:
                    # SECURITY: Ghost trust elevation requires a valid federation signature.
                    if not ghost.remote_pod_url:
                        logger.warning(f"A2A ghost {ghost.id} missing remote_pod_url; refusing trust elevation")
                        from src.gossip import query_agent_public
                        response = await query_agent_public(db, target_user.id, question, from_did, "a2a")
                    else:
                        raw_body = await request.body()
                        auth = verify_federation_request(from_did=from_did, body=raw_body, headers=request.headers)
                        if auth.status == "missing":
                            from src.gossip import query_agent_public
                            response = await query_agent_public(db, target_user.id, question, from_did, "a2a")
                        elif auth.status != "valid":
                            # JSON-RPC style error payload (keep HTTP 200 for A2A clients).
                            return {
                                "jsonrpc": "2.0",
                                "id": req.id,
                                "error": {"code": -32000, "message": f"Invalid federation signature: {auth.reason or 'invalid'}"},
                            }
                        else:
                            from src.gossip import query_agent
                            response = await query_agent(db, ghost.id, target_user.id, question)
            else:
                from src.gossip import query_agent_public
                response = await query_agent_public(db, target_user.id, question, from_did, "a2a")

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
    """No-op: pool membership alone grants network trust via resolve_trust_level().
    Connection rows are no longer needed for ghost users.
    """
    pass


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

        # SECURITY: Bind token to the intended sender pod URL (defense in depth if token is leaked)
        if invite_token.target_pod_url and req.from_pod.rstrip("/") != invite_token.target_pod_url.rstrip("/"):
            raise HTTPException(403, "Invite token is not valid for this sender pod")

        # SECURITY: Ensure network_id matches the token's network_id (avoid confusing/misrouted invites)
        if req.network_id != invite_token.network_id:
            raise HTTPException(400, "Invite network_id does not match invite token")

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

        # Check per-network ghost cap
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

        # Check global ghost cap
        total_ghosts = await db.execute(
            select(func.count()).select_from(User).where(User.is_remote == True)  # noqa: E712
        )
        if total_ghosts.scalar() >= MAX_GHOSTS_PER_POD:
            raise HTTPException(429, "Pod has reached maximum remote user capacity")

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

    1. Verifies auth user is the network owner
    2. Generates a one-time invite token for the remote pod
    3. Creates a ghost user locally for the remote user
    4. Sends the invite to the remote pod (they create a ghost for us)
    """
    async with async_session() as db:
        # SECURITY: Only the network owner can send pool invites
        net_result = await db.execute(
            select(Network).where(Network.id == req.network_id)
        )
        network = net_result.scalar_one_or_none()
        if not network:
            raise HTTPException(404, "Network not found")
        if network.owner_id != auth_user_id:
            raise HTTPException(403, "Only the network owner can send pool invites")

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


# ── Pool Sync (Orchestrator-driven pool formation) ──

class PoolSyncMember(BaseModel):
    did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)
    pod_url: str = Field(..., min_length=1, max_length=MAX_POD_URL_CHARS)
    username: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)


class PoolSyncRequest(BaseModel):
    """Accept pool membership from orchestrator or remote pod."""
    network_name: str
    network_type: str = "custom"
    pool_type: str = "standard"
    shared_categories: list[str] | None = None
    context: str = "personal"
    description: str = ""
    creator_pod_url: str
    members: list[PoolSyncMember]


@router.post("/pool-sync")
async def pool_sync(req: PoolSyncRequest, request: Request):
    """Accept pool membership from the orchestrator.

    Creates or finds the network locally, creates ghost users for remote members,
    adds everyone to the network, and creates connections between local user and ghosts.
    Requires TRUSTMESH_POOL_SYNC_SECRET to be set and provided via X-Pool-Sync-Secret header.
    """
    # SECURITY: Require pre-shared secret to prevent arbitrary ghost injection
    if not POOL_SYNC_SECRET:
        raise HTTPException(503, "Pool sync not configured — set TRUSTMESH_POOL_SYNC_SECRET")
    auth_header = request.headers.get("X-Pool-Sync-Secret", "")
    if not secrets.compare_digest(auth_header, POOL_SYNC_SECRET):
        raise HTTPException(403, "Invalid pool sync secret")

    async with async_session() as db:
        # Find the local user (the one that's not a ghost on this pod)
        local_users = await db.execute(
            select(User).where(User.is_remote == False)  # noqa: E712
        )
        local_user = local_users.scalars().first()
        if not local_user:
            raise HTTPException(500, "No local user found on this pod")

        # Create or find the network
        existing_net = await db.execute(
            select(Network).where(Network.name == req.network_name)
        )
        network = existing_net.scalar_one_or_none()

        if not network:
            import json as _json
            network = Network(
                owner_id=local_user.id,
                name=req.network_name,
                description=req.description,
                network_type=req.network_type,
                pool_type=req.pool_type,
                shared_categories=_json.dumps(req.shared_categories) if req.shared_categories else None,
                context=req.context,
                is_public=req.pool_type == "public_registry",
                join_policy="invite_only",
            )
            db.add(network)
            await db.flush()

        # Ensure local user is a member
        existing_mem = await db.execute(
            select(NetworkMembership).where(
                NetworkMembership.network_id == network.id,
                NetworkMembership.user_id == local_user.id,
            )
        )
        if not existing_mem.scalar_one_or_none():
            db.add(NetworkMembership(
                network_id=network.id,
                user_id=local_user.id,
                role="member",
            ))

        # SECURITY: Enforce ghost caps correctly for multi-member sync.
        # We compute how many *new* ghosts and memberships would be added before writing.
        remote_members = [
            m for m in req.members
            if m.pod_url.rstrip("/") != POD_URL.rstrip("/")
        ]
        remote_dids = {m.did for m in remote_members if m.did}

        if "" in remote_dids:
            raise HTTPException(400, "Invalid member DID")

        # Current global ghost count
        total_ghosts_res = await db.execute(
            select(func.count()).select_from(User).where(User.is_remote == True)  # noqa: E712
        )
        total_ghosts = int(total_ghosts_res.scalar() or 0)

        # Which DIDs already exist as ghosts?
        existing_ghost_dids_res = await db.execute(
            select(User.remote_did).where(
                User.is_remote == True,  # noqa: E712
                User.remote_did.in_(list(remote_dids)),
            )
        )
        existing_ghost_dids = {d for d in existing_ghost_dids_res.scalars().all() if d}
        new_ghosts_needed = len(remote_dids - existing_ghost_dids)
        if total_ghosts + new_ghosts_needed > MAX_GHOSTS_PER_POD:
            raise HTTPException(429, "Pod has reached maximum remote user capacity")

        # Current per-network remote membership count
        current_net_remote_res = await db.execute(
            select(func.count()).select_from(NetworkMembership).join(
                User, NetworkMembership.user_id == User.id
            ).where(
                NetworkMembership.network_id == network.id,
                User.is_remote == True,  # noqa: E712
            )
        )
        current_net_remote = int(current_net_remote_res.scalar() or 0)

        # Which remote DIDs already have memberships in this network?
        existing_net_remote_dids_res = await db.execute(
            select(User.remote_did).select_from(NetworkMembership).join(
                User, NetworkMembership.user_id == User.id
            ).where(
                NetworkMembership.network_id == network.id,
                User.is_remote == True,  # noqa: E712
            )
        )
        existing_net_remote_dids = {d for d in existing_net_remote_dids_res.scalars().all() if d}
        new_net_members_needed = len(remote_dids - existing_net_remote_dids)
        if current_net_remote + new_net_members_needed > GHOST_CAP_PER_NETWORK:
            raise HTTPException(
                429,
                f"Network has reached the maximum of {GHOST_CAP_PER_NETWORK} remote members",
            )

        # Create ghost users for remote members and add them to the network
        ghost_count = 0
        for member in remote_members:
            # Skip if this member IS the local user (same pod URL check)
            # (remote_members already filtered, so this is just belt-and-suspenders)
            if member.pod_url.rstrip("/") == POD_URL.rstrip("/"):
                continue

            ghost = await get_or_create_ghost_user(
                db, member.username, member.display_name,
                member.did, member.pod_url,
            )

            # Add ghost to network if not already a member
            existing_ghost_mem = await db.execute(
                select(NetworkMembership).where(
                    NetworkMembership.network_id == network.id,
                    NetworkMembership.user_id == ghost.id,
                )
            )
            if not existing_ghost_mem.scalar_one_or_none():
                db.add(NetworkMembership(
                    network_id=network.id,
                    user_id=ghost.id,
                    role="remote_member",
                ))
                await db.flush()

            # Create auto-accepted connections
            await _create_ghost_connections(db, ghost.id, network.id)
            ghost_count += 1

        await db.commit()

        return {
            "status": "synced",
            "network_name": network.name,
            "network_id": network.id,
            "local_user": local_user.username,
            "ghost_members_added": ghost_count,
        }


# ── Federation Message Delivery ──

class DeliverMessageRequest(BaseModel):
    from_did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)
    from_pod: str = Field(..., min_length=1, max_length=MAX_POD_URL_CHARS)
    to_username: str = Field(..., min_length=1, max_length=50)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=10_000)
    scope: str = "direct"
    expires_in_hours: int | None = None
    sender_username: str = Field(..., min_length=1, max_length=50)
    sender_display_name: str = Field(..., min_length=1, max_length=100)
    federation_signature: str = ""


@router.post("/messages/deliver")
async def deliver_message(
    req: DeliverMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive a federated message delivery from a remote pod.

    Security:
    - Rate limited by from_did
    - DID spoofing check via ghost.remote_pod_url
    - Federation signature required (ed25519)
    - Trust: recipient must be connected to or share a pool with the sender
    """
    from datetime import timedelta

    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limit by from_did
    rate_ok, rate_reason = check_query_rate(req.from_did, f"deliver:{req.to_username}", "public")
    if not rate_ok:
        raise HTTPException(429, rate_reason)
    record_query(req.from_did, f"deliver:{req.to_username}")

    # 2. Resolve recipient — local, non-remote user
    result = await db.execute(
        select(User).where(User.username == req.to_username, User.is_remote == False)  # noqa: E712
    )
    recipient = result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(404, f"User '{req.to_username}' not found")

    # 3. Ghost lookup + DID spoofing check
    ghost = await lookup_ghost_by_did(db, req.from_did)
    if ghost:
        if ghost.remote_pod_url and req.from_pod.rstrip("/") != ghost.remote_pod_url.rstrip("/"):
            logger.warning(
                "Federated message delivery DID spoofing: %s claims pod %s, ghost registered from %s",
                req.from_did, req.from_pod, ghost.remote_pod_url,
            )
            raise HTTPException(403, "DID spoofing detected: pod URL mismatch")

    # 4. Verify federation signature (reject unsigned)
    raw_body = await request.body()
    auth = verify_federation_request(from_did=req.from_did, body=raw_body, headers=request.headers)
    if auth.status not in ("valid", "missing"):
        raise HTTPException(403, f"Invalid federation signature: {auth.reason or 'invalid'}")
    if auth.status == "missing":
        # Require signature for message delivery (unlike query which has backward-compat mode)
        raise HTTPException(403, "Federation signature required for message delivery")

    # 5. Trust check: sender (ghost) must be connected or pool-member
    if ghost:
        from src.trust import resolve_trust_level
        trust, _ = await resolve_trust_level(db, ghost.id, recipient.id)
        if trust not in ("connected", "network", "private"):
            raise HTTPException(403, "Insufficient trust level for message delivery")
    else:
        raise HTTPException(403, "Sender ghost not found — complete pool setup before messaging")

    # 6. Encrypt body for recipient
    import uuid
    import hashlib
    from src import transit_bridge, message_bridge

    msg_id = str(uuid.uuid4()).replace("-", "")[:32]
    aad = f"message:{msg_id}"
    body_bytes = req.body.encode("utf-8")
    body_hash = hashlib.sha256(body_bytes).hexdigest()

    if transit_bridge.has_key(recipient.id):
        body_enc = transit_bridge.encrypt(recipient.id, body_bytes, aad=aad)
        rekey_needed = False
    else:
        # Recipient offline — encrypt with pod KEK, rekey on next login
        from src.main import _POD_KEK
        from src.crypto import encrypt as crypto_encrypt
        body_enc = crypto_encrypt(body_bytes, _POD_KEK)
        rekey_needed = True

    # 7. Compute expires_at
    expires_at = None
    if req.expires_in_hours:
        from datetime import timedelta
        expires_dt = datetime.now(timezone.utc) + timedelta(hours=req.expires_in_hours)
        expires_at = expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    message_bridge.create_message(
        message_id=msg_id,
        sender_id=ghost.id,
        sender_username=req.sender_username,
        sender_display_name=req.sender_display_name,
        sender_pod_url=req.from_pod,
        recipient_id=recipient.id,
        subject=req.subject,
        body_encrypted=body_enc,
        body_hash=body_hash,
        scope=req.scope,
        trust_level=trust,
        expires_at=expires_at,
        rekey_needed=rekey_needed,
    )

    # 8. Notification
    from src.models import Notification
    notif = Notification(
        user_id=recipient.id,
        notification_type="message_received",
        title=f"Message from {req.sender_display_name}: {req.subject[:80]}",
        body=req.subject,
        related_id=msg_id,
    )
    db.add(notif)
    await db.commit()

    return {"delivered": True, "message_id": msg_id}
