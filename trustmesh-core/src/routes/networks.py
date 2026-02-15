"""Network CRUD, membership management, discovery, and join request routes."""

from datetime import datetime, timezone

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.crypto import encrypt, generate_key
from src.database import get_db
from src.models import Connection, Network, NetworkJoinRequest, NetworkMembership, Notification, User
from src.schemas import (
    NetworkAddMember,
    NetworkCreate,
    NetworkDiscoveryResponse,
    NetworkJoinRequestCreate,
    NetworkJoinRequestResponse,
    NetworkJoinRequestUpdate,
    NetworkResponse,
    UserPublic,
)

router = APIRouter(prefix="/api", tags=["networks"])


async def _network_response(db: AsyncSession, network: Network) -> NetworkResponse:
    """Build a NetworkResponse with member list."""
    result = await db.execute(
        select(NetworkMembership).where(NetworkMembership.network_id == network.id)
    )
    memberships = result.scalars().all()
    members = []
    for m in memberships:
        user = await db.get(User, m.user_id)
        if user:
            members.append(UserPublic.model_validate(user))
    # Parse shared_categories from JSON string
    shared_cats = None
    if network.shared_categories:
        try:
            shared_cats = json.loads(network.shared_categories) if isinstance(network.shared_categories, str) else network.shared_categories
        except (json.JSONDecodeError, TypeError):
            shared_cats = None

    return NetworkResponse(
        id=network.id,
        owner_id=network.owner_id,
        name=network.name,
        description=network.description,
        network_type=network.network_type,
        is_public=network.is_public,
        join_policy=network.join_policy,
        pool_type=network.pool_type,
        shared_categories=shared_cats,
        created_at=network.created_at,
        members=members,
    )


@router.post("/networks", response_model=NetworkResponse)
async def create_network(data: NetworkCreate, db: AsyncSession = Depends(get_db),
                         auth_user_id: str = Depends(get_current_user_id)):
    """Create a new network."""
    if auth_user_id != data.owner_id:
        raise HTTPException(403, "Access denied")
    owner = await db.get(User, data.owner_id)
    if not owner:
        raise HTTPException(404, "Owner not found")

    network_key = generate_key()
    # Encrypt network key with owner's vault key
    from src.main import vault_keys
    vault_key = vault_keys.get(data.owner_id)
    if not vault_key:
        raise HTTPException(500, "Vault key not loaded — log in first")
    encrypted_key = encrypt(network_key, vault_key)

    network = Network(
        owner_id=data.owner_id,
        name=data.name,
        description=data.description,
        network_type=data.network_type,
        is_public=data.is_public,
        join_policy=data.join_policy,
        context=data.context,
        pool_type=data.pool_type,
        shared_categories=json.dumps(data.shared_categories) if data.shared_categories else None,
        encrypted_network_key=encrypted_key,
    )
    db.add(network)
    await db.flush()

    # Owner is automatically a member
    membership = NetworkMembership(
        network_id=network.id,
        user_id=data.owner_id,
        role="owner",
    )
    db.add(membership)
    await db.commit()
    await db.refresh(network)
    return await _network_response(db, network)


@router.get("/users/{user_id}/networks", response_model=list[NetworkResponse])
async def list_user_networks(user_id: str, context: str | None = None,
                             db: AsyncSession = Depends(get_db),
                             auth_user_id: str = Depends(get_current_user_id)):
    """List networks a user belongs to. Optional context filter."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    # If no context param, check user's active_context
    if context is None:
        user = await db.get(User, user_id)
        context = user.active_context if user else "all"

    query = (
        select(Network)
        .join(NetworkMembership, NetworkMembership.network_id == Network.id)
        .where(NetworkMembership.user_id == user_id)
    )
    # Filter by network context
    if context and context != "all":
        query = query.where(Network.context.in_([context, "both"]))

    result = await db.execute(query)
    networks = result.scalars().all()
    return [await _network_response(db, n) for n in networks]


# ── Network Discovery ─────────────────────────────
# NOTE: This MUST be before /networks/{network_id} to avoid route shadowing

@router.get("/networks/discover", response_model=list[NetworkDiscoveryResponse])
async def discover_networks(db: AsyncSession = Depends(get_db)):
    """List public networks available to join."""
    result = await db.execute(
        select(Network).where(Network.is_public == True).order_by(Network.name)  # noqa: E712
    )
    networks = result.scalars().all()
    responses = []
    for n in networks:
        mem_result = await db.execute(
            select(func.count(NetworkMembership.id)).where(
                NetworkMembership.network_id == n.id
            )
        )
        member_count = mem_result.scalar() or 0
        owner = await db.get(User, n.owner_id)
        owner_name = owner.display_name if owner else "Unknown"
        # Parse shared_categories
        shared_cats = None
        if n.shared_categories:
            try:
                shared_cats = json.loads(n.shared_categories) if isinstance(n.shared_categories, str) else n.shared_categories
            except (json.JSONDecodeError, TypeError):
                shared_cats = None

        responses.append(NetworkDiscoveryResponse(
            id=n.id,
            name=n.name,
            description=n.description,
            network_type=n.network_type,
            join_policy=n.join_policy,
            pool_type=n.pool_type,
            shared_categories=shared_cats,
            member_count=member_count,
            owner_name=owner_name,
        ))
    return responses


@router.get("/networks/{network_id}", response_model=NetworkResponse)
async def get_network(network_id: str, db: AsyncSession = Depends(get_db),
                      auth_user_id: str = Depends(get_current_user_id)):
    """Get network details with members (must be a member)."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    # Check membership
    result = await db.execute(
        select(NetworkMembership).where(
            NetworkMembership.network_id == network_id,
            NetworkMembership.user_id == auth_user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(403, "Not a member of this network")
    return await _network_response(db, network)


@router.post("/networks/{network_id}/members", response_model=NetworkResponse)
async def add_member(
    network_id: str, data: NetworkAddMember, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Add a connected user to a network."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    if network.owner_id != auth_user_id:
        raise HTTPException(403, "Only the network owner can add members")

    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # Check they're connected to the owner
    conn_result = await db.execute(
        select(Connection).where(
            Connection.status == "accepted",
            or_(
                and_(Connection.from_user_id == network.owner_id, Connection.to_user_id == data.user_id),
                and_(Connection.from_user_id == data.user_id, Connection.to_user_id == network.owner_id),
            ),
        )
    )
    if not conn_result.scalar_one_or_none():
        raise HTTPException(400, "User must be connected to network owner first")

    # Check not already a member
    existing = await db.execute(
        select(NetworkMembership).where(
            NetworkMembership.network_id == network_id,
            NetworkMembership.user_id == data.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Already a member")

    membership = NetworkMembership(
        network_id=network_id,
        user_id=data.user_id,
        role="member",
    )
    db.add(membership)
    await db.commit()
    return await _network_response(db, network)


@router.delete("/networks/{network_id}/members/{user_id}")
async def remove_member(
    network_id: str, user_id: str, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Remove a user from a network."""
    result = await db.execute(
        select(NetworkMembership).where(
            NetworkMembership.network_id == network_id,
            NetworkMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(404, "Membership not found")
    if membership.role == "owner":
        raise HTTPException(400, "Cannot remove the network owner")

    # Only owner or the user themselves can remove
    network = await db.get(Network, network_id)
    if auth_user_id != network.owner_id and auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    await db.delete(membership)

    # SECURITY: Clean up ghost users with no remaining memberships
    user = await db.get(User, user_id)
    if user and user.is_remote:
        remaining = await db.execute(
            select(func.count()).select_from(NetworkMembership)
            .where(NetworkMembership.user_id == user_id)
        )
        if remaining.scalar() == 0:
            # Ghost has no remaining memberships — full cleanup
            await db.execute(delete(Connection).where(
                or_(Connection.from_user_id == user_id, Connection.to_user_id == user_id)
            ))
            await db.delete(user)

    await db.commit()
    return {"ok": True}


@router.post("/networks/{network_id}/join-request", response_model=NetworkJoinRequestResponse)
async def create_join_request(
    network_id: str,
    data: NetworkJoinRequestCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Request to join a public network."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    if not network.is_public:
        raise HTTPException(403, "Network is not public")

    # Check if already a member
    existing_mem = await db.execute(
        select(NetworkMembership).where(
            NetworkMembership.network_id == network_id,
            NetworkMembership.user_id == user_id,
        )
    )
    if existing_mem.scalar_one_or_none():
        raise HTTPException(400, "Already a member")

    # Check for existing pending request
    existing_req = await db.execute(
        select(NetworkJoinRequest).where(
            NetworkJoinRequest.network_id == network_id,
            NetworkJoinRequest.user_id == user_id,
            NetworkJoinRequest.status == "pending",
        )
    )
    if existing_req.scalar_one_or_none():
        raise HTTPException(400, "Request already pending")

    # If open join policy, auto-approve
    if network.join_policy == "open":
        membership = NetworkMembership(
            network_id=network_id,
            user_id=user_id,
            role="member",
        )
        db.add(membership)
        join_req = NetworkJoinRequest(
            user_id=user_id,
            network_id=network_id,
            message=data.message,
            status="approved",
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(join_req)
        await db.commit()
        await db.refresh(join_req)
        return join_req

    # Create pending request
    join_req = NetworkJoinRequest(
        user_id=user_id,
        network_id=network_id,
        message=data.message,
        status="pending",
    )
    db.add(join_req)

    # Notify network owner
    notification = Notification(
        user_id=network.owner_id,
        notification_type="join_request",
        title=f"Join request for {network.name}",
        body=data.message or "No message",
        related_id=network_id,
    )
    db.add(notification)

    await db.commit()
    await db.refresh(join_req)
    return join_req


@router.get("/networks/{network_id}/join-requests", response_model=list[NetworkJoinRequestResponse])
async def list_join_requests(network_id: str, db: AsyncSession = Depends(get_db),
                             auth_user_id: str = Depends(get_current_user_id)):
    """List pending join requests for a network (owner only)."""
    network = await db.get(Network, network_id)
    if not network or network.owner_id != auth_user_id:
        raise HTTPException(403, "Only network owner can view join requests")
    result = await db.execute(
        select(NetworkJoinRequest).where(
            NetworkJoinRequest.network_id == network_id,
            NetworkJoinRequest.status == "pending",
        ).order_by(NetworkJoinRequest.created_at.desc())
    )
    requests = result.scalars().all()
    responses = []
    for req in requests:
        user = await db.get(User, req.user_id)
        responses.append(NetworkJoinRequestResponse(
            id=req.id,
            user_id=req.user_id,
            network_id=req.network_id,
            message=req.message,
            status=req.status,
            created_at=req.created_at,
            reviewed_at=req.reviewed_at,
            user=UserPublic.model_validate(user) if user else None,
        ))
    return responses


@router.put("/networks/{network_id}/join-requests/{request_id}")
async def review_join_request(
    network_id: str,
    request_id: str,
    data: NetworkJoinRequestUpdate,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Approve or decline a join request."""
    network = await db.get(Network, network_id)
    if not network or network.owner_id != auth_user_id:
        raise HTTPException(403, "Only network owner can review join requests")
    join_req = await db.get(NetworkJoinRequest, request_id)
    if not join_req or join_req.network_id != network_id:
        raise HTTPException(404, "Join request not found")
    if join_req.status != "pending":
        raise HTTPException(400, "Request already reviewed")

    join_req.status = data.status
    join_req.reviewed_at = datetime.now(timezone.utc)

    if data.status == "approved":
        membership = NetworkMembership(
            network_id=network_id,
            user_id=join_req.user_id,
            role="member",
        )
        db.add(membership)

    await db.commit()
    return {"ok": True, "status": data.status}
