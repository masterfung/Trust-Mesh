"""Trust resolution between users based on connections and shared networks."""

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Connection, Network, NetworkMembership


async def get_accepted_connection(
    db: AsyncSession, user_a_id: str, user_b_id: str
) -> Connection | None:
    """Check if two users have an accepted bidirectional connection."""
    result = await db.execute(
        select(Connection).where(
            Connection.status == "accepted",
            or_(
                and_(Connection.from_user_id == user_a_id, Connection.to_user_id == user_b_id),
                and_(Connection.from_user_id == user_b_id, Connection.to_user_id == user_a_id),
            ),
        )
    )
    return result.scalar_one_or_none()


async def get_shared_networks(
    db: AsyncSession, user_a_id: str, user_b_id: str
) -> list[Network]:
    """Find networks where both users are members."""
    a_networks = select(NetworkMembership.network_id).where(
        NetworkMembership.user_id == user_a_id
    ).subquery()
    b_networks = select(NetworkMembership.network_id).where(
        NetworkMembership.user_id == user_b_id
    ).subquery()

    result = await db.execute(
        select(Network).where(
            Network.id.in_(select(a_networks.c.network_id)),
            Network.id.in_(select(b_networks.c.network_id)),
        )
    )
    return list(result.scalars().all())


async def resolve_trust_level(
    db: AsyncSession, from_user_id: str, to_user_id: str
) -> tuple[str, list[Network]]:
    """Determine trust level and shared networks between two users.

    Returns:
        ("private", []) if same user
        ("network", [shared_networks]) if connected + share networks
        ("public", []) if connected but no shared networks, or not connected
    """
    if from_user_id == to_user_id:
        return ("private", [])

    connection = await get_accepted_connection(db, from_user_id, to_user_id)
    if not connection:
        return ("public", [])

    shared = await get_shared_networks(db, from_user_id, to_user_id)
    if shared:
        return ("network", shared)

    return ("public", [])
