"""Federation layer — cross-pod communication for TrustMesh.

Each TrustMesh pod is an independent instance with its own DB, vault, and agents.
Federation lets pods discover each other's agents and proxy gossip queries across pods.
"""

import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import PeerPod

logger = logging.getLogger(__name__)

# This pod's identity (configurable per instance)
POD_NAME = os.getenv("TRUSTMESH_POD_NAME", "TrustMesh Pod")
POD_URL = os.getenv("TRUSTMESH_POD_URL", "http://localhost:8000")

# Timeout for cross-pod HTTP calls
FEDERATION_TIMEOUT = 15.0


async def get_pod_info() -> dict:
    """Return this pod's identity and agent summary."""
    from src.database import async_session
    from src.models import Agent, User

    async with async_session() as db:
        result = await db.execute(
            select(Agent, User).join(User, Agent.owner_id == User.id).order_by(User.display_name)
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
        # Update existing
        existing_pod.name = peer_info.get("pod_name", existing_pod.name)
        existing_pod.agent_count = peer_info.get("agent_count", 0)
        existing_pod.status = "active"
        existing_pod.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing_pod)

        # Tell the peer about us (bidirectional)
        await _register_with_peer(peer_url)
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

    # Tell the peer about us (bidirectional)
    await _register_with_peer(peer_url)

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
    try:
        async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
            await client.post(
                f"{peer_url.rstrip('/')}/api/pod/peers",
                json={"url": POD_URL},
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


async def remote_query(peer_url: str, from_did: str, to_username: str, question: str) -> dict | None:
    """Send a gossip query to a remote pod.

    The remote pod runs its own trust resolution + Citadel pipeline.
    We send our agent DID so the remote pod can verify identity.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{peer_url.rstrip('/')}/api/pod/query",
                json={
                    "from_did": from_did,
                    "from_pod": POD_URL,
                    "to_username": to_username,
                    "question": question,
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
