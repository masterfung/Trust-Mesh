"""Network CRUD and membership management routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.crypto import encrypt, generate_key
from src.database import get_db
from src.models import Connection, Network, NetworkMembership, User
from src.schemas import NetworkAddMember, NetworkCreate, NetworkResponse, UserPublic

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
    return NetworkResponse(
        id=network.id,
        owner_id=network.owner_id,
        name=network.name,
        description=network.description,
        network_type=network.network_type,
        created_at=network.created_at,
        members=members,
    )


@router.post("/networks", response_model=NetworkResponse)
async def create_network(data: NetworkCreate, db: AsyncSession = Depends(get_db)):
    """Create a new network."""
    owner = await db.get(User, data.owner_id)
    if not owner:
        raise HTTPException(404, "Owner not found")

    network_key = generate_key()
    # Encrypt network key with owner's vault key (simplified for hackathon)
    encrypted_key = encrypt(network_key, network_key)  # Self-encrypted placeholder

    network = Network(
        owner_id=data.owner_id,
        name=data.name,
        description=data.description,
        network_type=data.network_type,
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
async def list_user_networks(user_id: str, db: AsyncSession = Depends(get_db)):
    """List networks a user belongs to."""
    result = await db.execute(
        select(Network)
        .join(NetworkMembership, NetworkMembership.network_id == Network.id)
        .where(NetworkMembership.user_id == user_id)
    )
    networks = result.scalars().all()
    return [await _network_response(db, n) for n in networks]


@router.get("/networks/{network_id}", response_model=NetworkResponse)
async def get_network(network_id: str, db: AsyncSession = Depends(get_db)):
    """Get network details with members."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    return await _network_response(db, network)


@router.post("/networks/{network_id}/members", response_model=NetworkResponse)
async def add_member(
    network_id: str, data: NetworkAddMember, db: AsyncSession = Depends(get_db)
):
    """Add a connected user to a network."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")

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
    network_id: str, user_id: str, db: AsyncSession = Depends(get_db)
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

    await db.delete(membership)
    await db.commit()
    return {"ok": True}
