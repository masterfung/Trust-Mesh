"""Connection request and management routes."""

import logging

import pydantic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import Connection, ConnectionRequest, NetworkMembership, Notification, User
from src.rate_limit import check_connection_rate, record_connection_request

logger = logging.getLogger(__name__)
from src.schemas import (
    ConnectionLabelUpdate,
    ConnectionRequestCreate,
    ConnectionRequestResponse,
    ConnectionResponse,
    UserPublic,
)

router = APIRouter(prefix="/api", tags=["connections"])


@router.post("/connections/request", response_model=ConnectionRequestResponse)
async def send_connection_request(
    data: ConnectionRequestCreate, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Send a connection request to another user."""
    if auth_user_id != data.from_user_id:
        raise HTTPException(403, "Access denied")
    if data.from_user_id == data.to_user_id:
        raise HTTPException(400, "Cannot connect to yourself")

    # Rate limit check (application-level, NOT Citadel)
    allowed, reason = check_connection_rate(data.from_user_id)
    if not allowed:
        raise HTTPException(429, reason)

    from_user = await db.get(User, data.from_user_id)
    to_user = await db.get(User, data.to_user_id)
    if not from_user or not to_user:
        raise HTTPException(404, "User not found")

    # Check for existing connection
    existing = await db.execute(
        select(Connection).where(
            Connection.status == "accepted",
            or_(
                and_(Connection.from_user_id == data.from_user_id, Connection.to_user_id == data.to_user_id),
                and_(Connection.from_user_id == data.to_user_id, Connection.to_user_id == data.from_user_id),
            ),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Already connected")

    # Check for pending request
    pending = await db.execute(
        select(ConnectionRequest).where(
            ConnectionRequest.status == "pending",
            or_(
                and_(ConnectionRequest.from_user_id == data.from_user_id, ConnectionRequest.to_user_id == data.to_user_id),
                and_(ConnectionRequest.from_user_id == data.to_user_id, ConnectionRequest.to_user_id == data.from_user_id),
            ),
        )
    )
    if pending.scalar_one_or_none():
        raise HTTPException(400, "Connection request already pending")

    req = ConnectionRequest(
        from_user_id=data.from_user_id,
        to_user_id=data.to_user_id,
        message=data.message,
        context=data.context,
        relationship_type=data.relationship_type,
        from_label=data.from_label,
    )
    db.add(req)

    # Notify recipient
    notif = Notification(
        user_id=data.to_user_id,
        notification_type="connection_request",
        title=f"{from_user.display_name} wants to connect",
        body=data.message or f"{from_user.display_name} sent you a connection request.",
        related_id=req.id,
    )
    db.add(notif)

    await db.commit()
    await db.refresh(req)
    record_connection_request(data.from_user_id)
    return ConnectionRequestResponse(
        id=req.id,
        from_user_id=req.from_user_id,
        to_user_id=req.to_user_id,
        message=req.message,
        status=req.status,
        context=req.context,
        relationship_type=req.relationship_type,
        from_label=req.from_label,
        created_at=req.created_at,
        from_user=UserPublic.model_validate(from_user),
        to_user=UserPublic.model_validate(to_user),
    )


@router.get("/users/{user_id}/connections", response_model=list[ConnectionResponse])
async def list_connections(user_id: str, context: str | None = None,
                           db: AsyncSession = Depends(get_db),
                           auth_user_id: str = Depends(get_current_user_id)):
    """List accepted connections for a user. Optional context filter."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    # If no context param, check user's active_context
    if context is None:
        user = await db.get(User, user_id)
        context = user.active_context if user else "all"

    result = await db.execute(
        select(Connection).where(
            Connection.status == "accepted",
            or_(Connection.from_user_id == user_id, Connection.to_user_id == user_id),
        )
    )
    connections = result.scalars().all()

    # Filter by context
    filtered = []
    for conn in connections:
        if context and context != "all":
            if conn.context and conn.context != context:
                continue
        filtered.append(conn)

    # Batch-fetch all peer users in a single query (avoids N+1)
    peer_ids = [
        (conn.to_user_id if conn.from_user_id == user_id else conn.from_user_id)
        for conn in filtered
    ]
    peers_result = await db.execute(select(User).where(User.id.in_(peer_ids)))
    peer_by_id = {u.id: u for u in peers_result.scalars().all()}

    response = []
    for conn in filtered:
        is_from = conn.from_user_id == user_id
        peer_id = conn.to_user_id if is_from else conn.from_user_id
        peer = peer_by_id.get(peer_id)
        # Resolve labels from the current user's perspective
        my_label = conn.from_label if is_from else conn.to_label
        peer_label = conn.to_label if is_from else conn.from_label
        response.append(ConnectionResponse(
            id=conn.id,
            from_user_id=conn.from_user_id,
            to_user_id=conn.to_user_id,
            status=conn.status,
            context=conn.context,
            relationship_type=conn.relationship_type,
            my_label=my_label,
            peer_label=peer_label,
            created_at=conn.created_at,
            accepted_at=conn.accepted_at,
            peer=UserPublic.model_validate(peer) if peer else None,
        ))
    return response


@router.get("/users/{user_id}/connection-requests", response_model=list[ConnectionRequestResponse])
async def list_connection_requests(user_id: str, db: AsyncSession = Depends(get_db),
                                   auth_user_id: str = Depends(get_current_user_id)):
    """List pending connection requests for a user."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    result = await db.execute(
        select(ConnectionRequest).where(
            ConnectionRequest.to_user_id == user_id,
            ConnectionRequest.status == "pending",
        )
    )
    requests = result.scalars().all()

    # Precompute current user's connections and network memberships for mutual counts
    my_conn_result = await db.execute(
        select(Connection).where(
            Connection.status == "accepted",
            or_(Connection.from_user_id == user_id, Connection.to_user_id == user_id),
        )
    )
    my_connected_ids = set()
    for c in my_conn_result.scalars().all():
        my_connected_ids.add(c.to_user_id if c.from_user_id == user_id else c.from_user_id)

    my_net_result = await db.execute(
        select(NetworkMembership.network_id).where(NetworkMembership.user_id == user_id)
    )
    my_network_ids = set(my_net_result.scalars().all())

    response = []
    for req in requests:
        from_user = await db.get(User, req.from_user_id)

        # Count mutual connections
        requester_conn_result = await db.execute(
            select(Connection).where(
                Connection.status == "accepted",
                or_(Connection.from_user_id == req.from_user_id, Connection.to_user_id == req.from_user_id),
            )
        )
        requester_connected_ids = set()
        for c in requester_conn_result.scalars().all():
            requester_connected_ids.add(c.to_user_id if c.from_user_id == req.from_user_id else c.from_user_id)
        mutual_connections = len(my_connected_ids & requester_connected_ids)

        # Count mutual networks
        requester_net_result = await db.execute(
            select(NetworkMembership.network_id).where(NetworkMembership.user_id == req.from_user_id)
        )
        requester_network_ids = set(requester_net_result.scalars().all())
        mutual_networks = len(my_network_ids & requester_network_ids)

        response.append(ConnectionRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            message=req.message,
            status=req.status,
            relationship_type=req.relationship_type,
            from_label=req.from_label,
            mutual_connections=mutual_connections,
            mutual_networks=mutual_networks,
            created_at=req.created_at,
            from_user=UserPublic.model_validate(from_user) if from_user else None,
        ))
    return response

@router.get("/users/{user_id}/connection-requests/sent", response_model=list[ConnectionRequestResponse])
async def list_sent_connection_requests(user_id: str, db: AsyncSession = Depends(get_db),
                                        auth_user_id: str = Depends(get_current_user_id)):
    """List pending connection requests sent by a user (outgoing)."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    result = await db.execute(
        select(ConnectionRequest).where(
            ConnectionRequest.from_user_id == user_id,
            ConnectionRequest.status == "pending",
        )
    )
    requests = result.scalars().all()

    response = []
    for req in requests:
        to_user = await db.get(User, req.to_user_id)
        response.append(ConnectionRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            message=req.message,
            status=req.status,
            relationship_type=req.relationship_type,
            from_label=req.from_label,
            mutual_connections=0,
            mutual_networks=0,
            created_at=req.created_at,
            to_user=UserPublic.model_validate(to_user) if to_user else None,
        ))
    return response


# PUT /api/connection-requests/{id} is handled by the Zig kernel (handlers/connections.zig).


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: str, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Remove a connection (disconnect from someone)."""
    conn = await db.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    # Only allow parties in the connection to delete it
    if conn.from_user_id != auth_user_id and conn.to_user_id != auth_user_id:
        raise HTTPException(403, "Access denied")
    await db.delete(conn)
    await db.commit()
    return {"status": "disconnected"}


@router.patch("/connections/{connection_id}/label", response_model=ConnectionResponse)
async def update_connection_label(
    connection_id: str, data: ConnectionLabelUpdate, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Update your label or the relationship type on a connection."""
    conn = await db.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    if conn.from_user_id != auth_user_id and conn.to_user_id != auth_user_id:
        raise HTTPException(403, "Access denied")

    is_from = conn.from_user_id == auth_user_id
    if data.my_label is not None:
        if is_from:
            conn.from_label = data.my_label
        else:
            conn.to_label = data.my_label
    if data.relationship_type is not None:
        conn.relationship_type = data.relationship_type
    if data.context is not None:
        conn.context = data.context

    await db.commit()
    await db.refresh(conn)

    peer_id = conn.to_user_id if is_from else conn.from_user_id
    peer = await db.get(User, peer_id)
    my_label = conn.from_label if is_from else conn.to_label
    peer_label = conn.to_label if is_from else conn.from_label
    return ConnectionResponse(
        id=conn.id,
        from_user_id=conn.from_user_id,
        to_user_id=conn.to_user_id,
        status=conn.status,
        context=conn.context,
        relationship_type=conn.relationship_type,
        my_label=my_label,
        peer_label=peer_label,
        created_at=conn.created_at,
        accepted_at=conn.accepted_at,
        peer=UserPublic.model_validate(peer) if peer else None,
    )


# ── Cross-Pod Connection Request ──────────────────────────────────────────────

class CrossPodConnectionRequest(pydantic.BaseModel):
    from_user_id: str
    to_pod_url: str
    to_did: str
    to_username: str
    to_display_name: str
    message: str = ""
    relationship_type: str = ""
    context: str = "personal"


@router.post("/connections/request-cross-pod")
async def send_cross_pod_connection_request(
    data: CrossPodConnectionRequest,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Send a connection request to a user on a different pod."""
    import json as _json
    import uuid
    import httpx
    from src.models import Agent, Notification
    from src import transit_bridge
    from src.federation import POD_URL, get_or_create_ghost_user
    from src.federation_auth import sign_federation_request

    if auth_user_id != data.from_user_id:
        raise HTTPException(403, "Access denied")

    allowed, reason = check_connection_rate(data.from_user_id)
    if not allowed:
        raise HTTPException(429, reason)

    from_user = await db.get(User, data.from_user_id)
    if not from_user:
        raise HTTPException(404, "User not found")

    # Get or create ghost user for the remote person
    try:
        ghost = await get_or_create_ghost_user(
            db=db,
            remote_username=data.to_username,
            remote_display_name=data.to_display_name,
            remote_did=data.to_did,
            remote_pod_url=data.to_pod_url,
        )
        await db.flush()
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Check already connected or pending
    existing = await db.execute(
        select(Connection).where(
            or_(
                and_(Connection.from_user_id == data.from_user_id, Connection.to_user_id == ghost.id),
                and_(Connection.from_user_id == ghost.id, Connection.to_user_id == data.from_user_id),
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Already connected")

    existing_req = await db.execute(
        select(ConnectionRequest).where(
            ConnectionRequest.from_user_id == data.from_user_id,
            ConnectionRequest.to_user_id == ghost.id,
            ConnectionRequest.status == "pending",
        )
    )
    if existing_req.scalar_one_or_none():
        raise HTTPException(400, "Request already pending")

    # Sign and send to remote pod
    agent_result = await db.execute(select(Agent).where(Agent.owner_id == data.from_user_id))
    our_agent = agent_result.scalar_one_or_none()
    if not our_agent:
        raise HTTPException(500, "Agent not configured")

    if not transit_bridge.has_key(data.from_user_id) or not our_agent.encrypted_private_key:
        raise HTTPException(400, "Vault key not loaded — please log in again")

    private_key = transit_bridge.decrypt(data.from_user_id, our_agent.encrypted_private_key)
    payload = {
        "from_did": our_agent.did,
        "from_pod_url": POD_URL,
        "from_display_name": from_user.display_name,
        "to_did": data.to_did,
        "message": data.message,
    }
    body = _json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(sign_federation_request(body, private_key))
    del private_key

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{data.to_pod_url.rstrip('/')}/api/pod/connection-request",
                content=body,
                headers=headers,
            )
        if resp.status_code not in (200, 201):
            raise HTTPException(502, f"Remote pod rejected request: {resp.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Could not reach remote pod: {e}")

    # Create local pending ConnectionRequest for tracking
    req = ConnectionRequest(
        from_user_id=data.from_user_id,
        to_user_id=ghost.id,
        message=data.message,
        context=data.context,
        relationship_type=data.relationship_type or None,
    )
    db.add(req)
    record_connection_request(data.from_user_id)
    await db.commit()

    return {"status": "sent", "to_display_name": data.to_display_name, "to_pod_url": data.to_pod_url}
