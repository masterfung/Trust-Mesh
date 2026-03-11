"""Connection request and management routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import Connection, ConnectionRequest, NetworkMembership, User
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
