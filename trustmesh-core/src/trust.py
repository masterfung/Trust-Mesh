"""Trust resolution between users based on connections and shared networks."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Connection, Network, NetworkMembership, PeerPod, User

GHOST_STALE_HOURS = 24


async def _is_ghost_stale(db: AsyncSession, user_id: str) -> bool:
    """Check if a ghost user's home pod is stale (unreachable or not seen recently)."""
    user = await db.get(User, user_id)
    if not user or not user.is_remote or not user.remote_pod_url:
        return False
    result = await db.execute(
        select(PeerPod).where(PeerPod.url == user.remote_pod_url.rstrip("/"))
    )
    peer = result.scalar_one_or_none()
    if not peer:
        return True  # No PeerPod record = stale
    if peer.status != "active":
        return True
    if peer.last_seen_at:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=GHOST_STALE_HOURS)
        # Handle tz-naive datetimes from SQLite
        naive_last_seen = peer.last_seen_at.replace(tzinfo=None) if peer.last_seen_at.tzinfo else peer.last_seen_at
        naive_cutoff = cutoff.replace(tzinfo=None)
        if naive_last_seen < naive_cutoff:
            return True
    return False


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
        ("network", [shared_networks]) if users share pools (connection optional)
        ("connected", []) if connected but no shared pools
        ("public", []) if not connected at all
    """
    if from_user_id == to_user_id:
        return ("private", [])

    # Pool membership alone grants "network" trust (no connection required)
    shared = await get_shared_networks(db, from_user_id, to_user_id)
    if shared:
        # Ghost staleness: if the requester's home pod is unreachable, downgrade to public
        if await _is_ghost_stale(db, from_user_id):
            return ("public", [])
        return ("network", shared)

    # Connected but no shared pools = connected trust (better than public, less than network)
    connection = await get_accepted_connection(db, from_user_id, to_user_id)
    if connection:
        return ("connected", [])

    return ("public", [])
