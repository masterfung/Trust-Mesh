"""Trust resolution — backed by Zig libpodos SQLite queries.

The Zig kernel does the fast SQL queries to determine trust level.
When shared networks are found, we fetch Network ORM objects from SQLAlchemy.
"""

import ctypes
import json

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Connection, Network, NetworkMembership, PeerPod, User
from src.models import utcnow

GHOST_STALE_HOURS = 24

_db_handle = None


def _get_lib():
    from src.timeline_bridge import _get_lib as _tl_get_lib
    return _tl_get_lib()


def _get_db_handle():
    """Get the Zig-side DB handle (shared with FTS5).

    Always reads live from embeddings to avoid stale pointer if FTS was
    closed and reinited (e.g., in tests).
    """
    global _db_handle
    if _db_handle is not None:
        return _db_handle
    from src import embeddings
    return embeddings._db_handle


def set_db_handle(handle):
    """Set the DB handle (called from lifespan after FTS init)."""
    global _db_handle
    _db_handle = handle


def reset_db_handle():
    """Clear cached handle so next call re-reads from embeddings."""
    global _db_handle
    _db_handle = None


async def _is_ghost_stale(db: AsyncSession, user_id: str) -> bool:
    """Check if a ghost user's home pod is stale (unreachable or not seen recently).

    Kept in Python for backward compat with callers that use it directly.
    The Zig trust resolver handles this internally.
    """
    from datetime import datetime, timedelta, timezone
    user = await db.get(User, user_id)
    if not user or not user.is_remote or not user.remote_pod_url:
        return False
    result = await db.execute(
        select(PeerPod).where(PeerPod.url == user.remote_pod_url.rstrip("/"))
    )
    peer = result.scalar_one_or_none()
    if not peer:
        return True
    if peer.status != "active":
        return True
    if peer.last_seen_at:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=GHOST_STALE_HOURS)
        naive_last_seen = peer.last_seen_at.replace(tzinfo=None) if peer.last_seen_at.tzinfo else peer.last_seen_at
        naive_cutoff = cutoff.replace(tzinfo=None)
        if naive_last_seen < naive_cutoff:
            return True
    return False


async def get_accepted_connection(
    db: AsyncSession, user_a_id: str, user_b_id: str
) -> Connection | None:
    """Check if two users have an accepted bidirectional connection.

    Kept in Python for callers that need the Connection object.
    """
    from sqlalchemy import and_
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
    """Find networks where both users are members.

    Kept in Python for callers that need Network objects.
    """
    a_networks = select(NetworkMembership.network_id).where(
        NetworkMembership.user_id == user_a_id
    ).subquery()
    b_networks = select(NetworkMembership.network_id).where(
        NetworkMembership.user_id == user_b_id
    ).subquery()

    now = utcnow()
    result = await db.execute(
        select(Network).where(
            Network.id.in_(select(a_networks.c.network_id)),
            Network.id.in_(select(b_networks.c.network_id)),
            or_(Network.expires_at.is_(None), Network.expires_at > now),
        )
    )
    return list(result.scalars().all())


async def resolve_trust_level(
    db: AsyncSession, from_user_id: str, to_user_id: str
) -> tuple[str, list[Network]]:
    """Determine trust level and shared networks between two users.

    Uses Zig kernel for fast SQL resolution, then fetches Network objects
    from SQLAlchemy when needed.

    Returns:
        ("private", []) if same user
        ("network", [shared_networks]) if users share pools
        ("connected", []) if connected but no shared pools
        ("public", []) if not connected at all
    """
    # Fast path: same user
    if from_user_id == to_user_id:
        return ("private", [])

    # Try Zig-backed resolution first
    handle = _get_db_handle()
    if handle is not None:
        try:
            lib = _get_lib()
            from_b = from_user_id.encode("utf-8")
            to_b = to_user_id.encode("utf-8")
            out = ctypes.create_string_buffer(4096)
            length = lib.podos_trust_resolve(
                handle, from_b, len(from_b), to_b, len(to_b), out, 4096
            )
            if length > 0:
                result = json.loads(out.raw[:length].decode("utf-8"))
                level = result.get("level", "public")
                network_ids = result.get("network_ids", [])

                if level == "network" and network_ids:
                    # Fetch Network ORM objects for callers that need them
                    net_result = await db.execute(
                        select(Network).where(Network.id.in_(network_ids))
                    )
                    return (level, list(net_result.scalars().all()))
                return (level, [])
        except Exception:
            pass  # Fall through to Python implementation

    # Fallback: Python implementation (if Zig DB not available)
    shared = await get_shared_networks(db, from_user_id, to_user_id)
    if shared:
        if await _is_ghost_stale(db, from_user_id):
            return ("public", [])
        return ("network", shared)

    connection = await get_accepted_connection(db, from_user_id, to_user_id)
    if connection:
        return ("connected", [])

    return ("public", [])
