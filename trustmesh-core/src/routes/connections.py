"""Connection request and management routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import Connection, ConnectionRequest, User
from src.rate_limit import check_connection_rate, record_connection_request
from src.schemas import (
    ConnectionRequestCreate,
    ConnectionRequestResponse,
    ConnectionRequestUpdate,
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

    response = []
    for conn in filtered:
        peer_id = conn.to_user_id if conn.from_user_id == user_id else conn.from_user_id
        peer = await db.get(User, peer_id)
        response.append(ConnectionResponse(
            id=conn.id,
            from_user_id=conn.from_user_id,
            to_user_id=conn.to_user_id,
            status=conn.status,
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
    response = []
    for req in requests:
        from_user = await db.get(User, req.from_user_id)
        response.append(ConnectionRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            message=req.message,
            status=req.status,
            created_at=req.created_at,
            from_user=UserPublic.model_validate(from_user) if from_user else None,
        ))
    return response


@router.put("/connection-requests/{request_id}", response_model=ConnectionRequestResponse)
async def update_connection_request(
    request_id: str, data: ConnectionRequestUpdate, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Accept or decline a connection request."""
    req = await db.get(ConnectionRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.to_user_id != auth_user_id:
        raise HTTPException(403, "Access denied")
    if req.status != "pending":
        raise HTTPException(400, "Request already processed")

    req.status = data.status
    req.reviewed_at = datetime.now(timezone.utc)

    if data.status == "accepted":
        connection = Connection(
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            status="accepted",
            accepted_at=datetime.now(timezone.utc),
        )
        db.add(connection)

    await db.commit()
    await db.refresh(req)
    return ConnectionRequestResponse(
        id=req.id,
        from_user_id=req.from_user_id,
        to_user_id=req.to_user_id,
        message=req.message,
        status=req.status,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
    )
