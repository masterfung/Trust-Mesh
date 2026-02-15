"""Federation layer — cross-pod communication for TrustMesh.

Each TrustMesh pod is an independent instance with its own DB, vault, and agents.
Federation lets pods discover each other's agents and proxy gossip queries across pods.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete, or_

from src.models import Connection, NetworkMembership, PeerPod, User

logger = logging.getLogger(__name__)

# This pod's identity (configurable per instance)
POD_NAME = os.getenv("TRUSTMESH_POD_NAME", "TrustMesh Pod")
POD_URL = os.getenv("TRUSTMESH_POD_URL", "http://localhost:8000")
REGISTRY_URL = os.getenv("TRUSTMESH_REGISTRY_URL", "")

# Timeout for cross-pod HTTP calls
FEDERATION_TIMEOUT = 15.0


async def get_pod_info() -> dict:
    """Return this pod's identity and agent summary."""
    from src.database import async_session
    from src.models import Agent, User

    async with async_session() as db:
        result = await db.execute(
            select(Agent, User).join(User, Agent.owner_id == User.id)
            .where(User.is_remote == False)  # noqa: E712
            .order_by(User.display_name)
        )
        agents = []
        for agent, user in result.all():
            agents.append({
                "did": agent.did,
                "name": agent.name,
                "owner_username": user.username,
                "owner_display_name": user.display_name,
                "owner_id": user.id,
                "user_type": user.user_type,
            })

    return {
        "pod_name": POD_NAME,
        "pod_url": POD_URL,
        "protocol": "trustmesh/0.1",
        "agent_count": len(agents),
        "agents": agents,
    }


async def ping_peer(peer_url: str) -> dict | None:
    """Ping a peer pod and return its info, or None if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            r = await client.get(f"{peer_url.rstrip('/')}/api/pod")
            if r.status_code == 200:
                return r.json()
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return None


async def connect_to_peer(db: AsyncSession, peer_url: str) -> PeerPod | None:
    """Connect to a peer pod: ping it, register it in our DB, and register ourselves with it.

    Returns the PeerPod record, or None if the peer is unreachable.
    """
    peer_url = peer_url.rstrip("/")

    # Check if already registered
    existing = await db.execute(select(PeerPod).where(PeerPod.url == peer_url))
    existing_pod = existing.scalar_one_or_none()

    # Ping the peer and validate agent card
    peer_info = await ping_peer(peer_url)
    if not peer_info:
        if existing_pod:
            existing_pod.status = "unreachable"
            await db.commit()
        return None

    # Validate agent card URL matches (security check)
    card_valid = await _validate_agent_card(peer_url)
    if not card_valid:
        logger.warning(f"Peer {peer_url} failed agent card validation — proceeding with caution")

    if existing_pod:
        # Update existing — do NOT re-register with peer (they already know us,
        # otherwise we'd loop: A→B→A→B forever)
        existing_pod.name = peer_info.get("pod_name", existing_pod.name)
        existing_pod.agent_count = peer_info.get("agent_count", 0)
        existing_pod.status = "active"
        existing_pod.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing_pod)
        return existing_pod

    # Create new
    pod = PeerPod(
        name=peer_info.get("pod_name", "Unknown Pod"),
        url=peer_url,
        agent_count=peer_info.get("agent_count", 0),
        status="active",
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(pod)
    await db.commit()
    await db.refresh(pod)

    # Tell the peer about us (bidirectional, fire-and-forget)
    asyncio.create_task(_register_with_peer(peer_url))

    return pod


async def _validate_agent_card(peer_url: str) -> bool:
    """Fetch and validate a peer's agent card — verify the pod_url matches what we fetched from."""
    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            r = await client.get(f"{peer_url.rstrip('/')}/.well-known/agent-card.json")
            if r.status_code == 200:
                card = r.json()
                card_url = card.get("trustmesh", {}).get("pod_url", "").rstrip("/")
                if card_url and card_url != peer_url.rstrip("/"):
                    logger.warning(
                        f"Agent card URL mismatch: fetched from {peer_url} but card claims {card_url}"
                    )
                    return False
                return True
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return False


async def _register_with_peer(peer_url: str):
    """Register this pod with a peer pod (so the connection is bidirectional)."""
    headers = {}
    pool_sync_secret = os.getenv("TRUSTMESH_POOL_SYNC_SECRET", "")
    if pool_sync_secret:
        headers["X-Pool-Sync-Secret"] = pool_sync_secret
    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            await client.post(
                f"{peer_url.rstrip('/')}/api/pod/peers",
                json={"url": POD_URL},
                headers=headers,
            )
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass  # Best-effort — peer may already know us


async def discover_remote_agents(db: AsyncSession) -> list[dict]:
    """Discover agents across all active peer pods via their agent cards."""
    result = await db.execute(select(PeerPod).where(PeerPod.status == "active"))
    peers = result.scalars().all()

    all_agents = []
    for peer in peers:
        try:
            async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
                r = await client.get(f"{peer.url.rstrip('/')}/.well-known/agent-card.json")
                if r.status_code == 200:
                    data = r.json()
                    # Extract agents from A2A-compatible agent card
                    skills = data.get("skills", [])
                    for skill in skills:
                        skill["_pod"] = {
                            "name": peer.name,
                            "url": peer.url,
                        }
                        all_agents.append(skill)
                    # Update peer info
                    peer.last_seen_at = datetime.now(timezone.utc)
                    peer.status = "active"
                else:
                    peer.status = "unreachable"
        except (httpx.RequestError, httpx.HTTPStatusError):
            peer.status = "unreachable"

    await db.commit()
    return all_agents


async def remote_query(
    peer_url: str,
    from_did: str,
    to_username: str,
    question: str,
    *,
    signing_private_key: bytes | None = None,
) -> dict | None:
    """Send a gossip query to a remote pod.

    The remote pod runs its own trust resolution + Citadel pipeline.
    We send our agent DID so the remote pod can verify identity.
    """
    try:
        import json as _json
        from src.federation_auth import sign_federation_request

        payload = {
            "from_did": from_did,
            "from_pod": POD_URL,
            "to_username": to_username,
            "question": question,
        }
        # Deterministic JSON bytes so the signature matches the body we send.
        body = _json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

        headers = {"Content-Type": "application/json"}

        if signing_private_key:
            headers.update(sign_federation_request(body, signing_private_key))

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{peer_url.rstrip('/')}/api/pod/query",
                content=body,
                headers=headers,
            )
            if r.status_code == 200:
                return r.json()
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return None


async def get_or_create_ghost_user(
    db: AsyncSession,
    remote_username: str,
    remote_display_name: str,
    remote_did: str,
    remote_pod_url: str,
) -> User:
    """Get or create a ghost user for a remote user joining a local pool.

    Ghost users are lightweight User records that allow remote users to
    participate in local pools via normal NetworkMembership. Idempotent —
    returns existing ghost if one exists for the given DID.
    """
    # Lookup by remote_did first (idempotent)
    existing = await db.execute(
        select(User).where(User.remote_did == remote_did, User.is_remote == True)  # noqa: E712
    )
    ghost = existing.scalar_one_or_none()
    if ghost:
        return ghost

    # Extract hostname from pod URL for username
    from urllib.parse import urlparse
    hostname = urlparse(remote_pod_url).hostname or "unknown"

    ghost = User(
        username=f"remote:{remote_username}@{hostname}",
        display_name=remote_display_name,
        bio=f"Remote user on {hostname}",
        is_discoverable=False,
        is_demo=False,
        is_remote=True,
        remote_pod_url=remote_pod_url.rstrip("/"),
        remote_did=remote_did,
    )
    db.add(ghost)
    await db.flush()
    return ghost


async def lookup_ghost_by_did(db: AsyncSession, remote_did: str) -> User | None:
    """Look up a ghost user by their remote DID."""
    result = await db.execute(
        select(User).where(User.remote_did == remote_did, User.is_remote == True)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def cleanup_ghosts_for_pod(db: AsyncSession, pod_url: str) -> dict:
    """Remove all ghost users from a disconnected pod, plus their connections and memberships.

    Called when a peer is removed to prevent orphaned ghost users from
    retaining elevated trust after the peering relationship ends.

    Returns stats: {ghosts_removed, connections_removed, memberships_removed}
    """
    pod_url = pod_url.rstrip("/")
    # Find all ghosts from this pod URL
    result = await db.execute(
        select(User).where(User.is_remote == True, User.remote_pod_url == pod_url)  # noqa: E712
    )
    ghosts = result.scalars().all()

    if not ghosts:
        return {"ghosts_removed": 0, "connections_removed": 0, "memberships_removed": 0}

    ghost_ids = [g.id for g in ghosts]
    connections_removed = 0
    memberships_removed = 0

    for ghost_id in ghost_ids:
        # Delete network memberships
        mem_result = await db.execute(
            delete(NetworkMembership).where(NetworkMembership.user_id == ghost_id)
        )
        memberships_removed += mem_result.rowcount

        # Delete connections (both directions)
        conn_result = await db.execute(
            delete(Connection).where(
                or_(Connection.from_user_id == ghost_id, Connection.to_user_id == ghost_id)
            )
        )
        connections_removed += conn_result.rowcount

    # Delete the ghost users
    for ghost in ghosts:
        await db.delete(ghost)

    return {
        "ghosts_removed": len(ghosts),
        "connections_removed": connections_removed,
        "memberships_removed": memberships_removed,
    }


async def send_pool_invite(
    peer_url: str,
    network_id: str,
    invite_token: str,
    local_username: str,
    local_display_name: str,
    local_did: str,
) -> dict | None:
    """Send a pool invitation to a remote pod.

    The remote pod will create a ghost user for us and add it to their copy
    of the pool (if they have one), or just acknowledge.
    """
    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            r = await client.post(
                f"{peer_url.rstrip('/')}/api/pod/pool-invite",
                json={
                    "network_id": network_id,
                    "invite_token": invite_token,
                    "from_pod": POD_URL,
                    "username": local_username,
                    "display_name": local_display_name,
                    "did": local_did,
                },
            )
            if r.status_code == 200:
                return r.json()
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return None


async def remote_emergency_access(peer_url: str, token: str, patient_username: str) -> dict | None:
    """Send an emergency access request to a remote pod."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{peer_url.rstrip('/')}/api/emergency/access",
                json={"token": token, "patient_username": patient_username},
            )
            if r.status_code == 200:
                return r.json()
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return None


# ── Public Registry Client ──────────────────────────────────


async def register_with_registry(
    agent_did: str,
    agent_name: str,
    pod_url: str,
    entity_type: str = "person",
    capabilities: list[str] | None = None,
    username: str = "",
    display_name: str = "",
    bio: str = "",
    private_key_bytes: bytes | None = None,
) -> None:
    """Register an agent with the public registry (fire-and-forget).

    Signs the request if private_key_bytes is provided.
    No-op if REGISTRY_URL is not configured.
    """
    if not REGISTRY_URL:
        return

    import json as _json
    from src.federation_auth import sign_federation_request

    payload = {
        "did": agent_did,
        "name": agent_name,
        "pod_url": pod_url,
        "entity_type": entity_type,
        "capabilities": capabilities or [],
        "username": username,
        "display_name": display_name,
        "bio": bio,
    }
    body = _json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if private_key_bytes:
        headers.update(sign_federation_request(body, private_key_bytes))

    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            r = await client.post(f"{REGISTRY_URL.rstrip('/')}/api/register", content=body, headers=headers)
            if r.status_code == 200:
                logger.info(f"Registered {agent_did} with registry")
            else:
                logger.warning(f"Registry registration failed: {r.status_code} {r.text[:100]}")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Registry registration error: {e}")


async def deregister_from_registry(
    agent_did: str,
    private_key_bytes: bytes | None = None,
) -> None:
    """Deregister an agent from the public registry (fire-and-forget).

    Signs the request if private_key_bytes is provided.
    No-op if REGISTRY_URL is not configured.
    """
    if not REGISTRY_URL:
        return

    import urllib.parse
    from src.federation_auth import sign_federation_request

    headers: dict[str, str] = {}
    body = b""
    if private_key_bytes:
        headers.update(sign_federation_request(body, private_key_bytes))

    encoded_did = urllib.parse.quote(agent_did, safe="")
    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            r = await client.delete(
                f"{REGISTRY_URL.rstrip('/')}/api/agents/{encoded_did}",
                headers=headers,
            )
            if r.status_code in (200, 404):
                logger.info(f"Deregistered {agent_did} from registry")
            else:
                logger.warning(f"Registry deregistration failed: {r.status_code}")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Registry deregistration error: {e}")


async def sync_discoverable_agents_to_registry() -> None:
    """Bulk-register all is_discoverable=True local agents with the registry.

    Called on pod startup. No-op if REGISTRY_URL is empty.
    """
    if not REGISTRY_URL:
        return

    from src.database import async_session
    from src.models import Agent, User
    from src.crypto import decrypt
    from src.main import vault_keys

    try:
        async with async_session() as db:
            result = await db.execute(
                select(Agent, User).join(User, Agent.owner_id == User.id)
                .where(User.is_discoverable == True, User.is_remote == False)  # noqa: E712
            )
            for agent, user in result.all():
                # Try to decrypt private key for signed registration
                private_key = None
                vk = vault_keys.get(user.id)
                if vk and agent.encrypted_private_key:
                    try:
                        private_key = decrypt(agent.encrypted_private_key, vk)
                    except Exception:
                        pass

                await register_with_registry(
                    agent_did=agent.did,
                    agent_name=agent.name,
                    pod_url=POD_URL,
                    entity_type=user.user_type or "person",
                    username=user.username,
                    display_name=user.display_name or "",
                    bio=user.bio or "",
                    private_key_bytes=private_key,
                )
    except Exception as e:
        logger.warning(f"Registry sync error: {e}")
