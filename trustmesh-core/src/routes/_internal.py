"""Internal routes for Zig kernel → Python callbacks.

These endpoints are not exposed publicly. They require the X-Internal-Proxy-Secret
header (same secret the Zig proxy uses) so they can only be called by the Zig
kernel process on localhost.

Currently used for:
- send-accept-callback: when Zig accepts a cross-pod connection request,
  it calls this endpoint so Python can sign and deliver the callback to the
  requester's remote pod.
"""

import json
import logging
import os
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from src import transit_bridge
from src.database import async_session
from src.federation_auth import sign_federation_request
from src.models import Agent, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/_internal", tags=["internal"])

PROXY_SECRET = os.getenv("TRUSTMESH_PROXY_SECRET", "")
MAX_DID_CHARS = 100


def _require_internal(request: Request) -> None:
    """Reject requests that don't come with the internal proxy secret."""
    if not PROXY_SECRET:
        # No secret configured → only accept loopback connections
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(403, "Internal endpoint: loopback only when no secret configured")
        return
    provided = request.headers.get("X-Internal-Proxy-Secret", "")
    if not secrets.compare_digest(provided, PROXY_SECRET):
        raise HTTPException(403, "Forbidden")


class AcceptCallbackRequest(BaseModel):
    """Payload for Zig → Python sign-and-send callback."""
    from_did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)  # our DID (acceptor)
    to_did: str = Field(..., min_length=1, max_length=MAX_DID_CHARS)    # requester's DID


@router.post("/send-accept-callback")
async def send_accept_callback(data: AcceptCallbackRequest, request: Request):
    """Sign and deliver a cross-pod connection acceptance callback.

    Called by the Zig kernel (or Python connections route) after a local user
    accepts an inbound cross-pod connection request. This endpoint:

    1. Loads the accepting user's ed25519 private key from the transit engine
    2. Signs the acceptance payload
    3. POSTs to the requester's pod's /api/pod/connection-accept endpoint

    Fire-and-forget: DB writes have already been committed by the caller.
    Network failure here does NOT roll back the local acceptance.
    """
    _require_internal(request)

    async with async_session() as db:
        # Resolve our local agent (the one accepting)
        agent_result = await db.execute(select(Agent).where(Agent.did == data.from_did))
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise HTTPException(404, f"Agent with DID {data.from_did[:20]}... not found")

        owner = await db.get(User, agent.owner_id)
        if not owner:
            raise HTTPException(404, "Agent owner not found")

        if not transit_bridge.has_key(agent.owner_id):
            raise HTTPException(503, "Vault key not available — user must be logged in")

        if not agent.encrypted_private_key:
            raise HTTPException(500, "Agent has no private key")

        private_key = transit_bridge.decrypt(agent.owner_id, agent.encrypted_private_key)

        # Find ghost user to get their pod URL
        ghost_result = await db.execute(
            select(User).where(User.remote_did == data.to_did, User.is_remote == True)  # noqa: E712
        )
        ghost = ghost_result.scalar_one_or_none()
        if not ghost or not ghost.remote_pod_url:
            raise HTTPException(404, "Remote requester's pod URL not found")

        remote_pod_url = ghost.remote_pod_url
        accepted_by_display_name = owner.display_name

    # Build signed payload
    payload = {
        "accepted_by_did": data.from_did,
        "requester_did": data.to_did,
        "accepted_by_display_name": accepted_by_display_name,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(sign_federation_request(body, private_key))
    del private_key  # zero ASAP

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{remote_pod_url.rstrip('/')}/api/pod/connection-accept",
                content=body,
                headers=headers,
            )
            if r.status_code not in (200, 201):
                logger.warning(
                    f"Accept callback to {remote_pod_url} failed: {r.status_code} {r.text[:200]}"
                )
    except Exception as e:
        logger.warning(f"Accept callback delivery failed (non-fatal): {e}")

    return {"status": "ok"}
