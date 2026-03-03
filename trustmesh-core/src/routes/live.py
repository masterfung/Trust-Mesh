"""Live Agent routes — real-time bidirectional voice/text agent via Gemini Live.

Endpoints:
  GET /api/live/token   — Ephemeral Gemini token for direct client connections
  WS  /api/live/stream  — Server-proxied bidirectional Live session
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import COOKIE_NAME, get_current_user_id, validate_session
from src.database import get_db
from src.gossip import get_user_networks
from src.live_agent import create_ephemeral_token, run_live_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])


# ── Auth helper for WebSocket ──────────────────────────────────

async def _get_ws_user(websocket: WebSocket, db: AsyncSession) -> str | None:
    """Extract and validate user session from a WebSocket handshake.

    WebSockets carry cookies exactly like HTTP requests, so we can reuse
    the session cookie validation without needing a separate token flow.
    Returns user_id or None if unauthenticated.
    """
    from sqlalchemy import select
    from src.models import User

    token = websocket.cookies.get(COOKIE_NAME)
    if not token:
        return None

    # Use empty fingerprint — dev mode / live sessions skip fingerprint binding
    user_id = validate_session(token, fingerprint="")
    if not user_id:
        return None

    # Confirm user exists
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.is_remote:
        return None

    return user_id


# ── Routes ─────────────────────────────────────────────────────

@router.get("/token")
async def get_live_token(user_id: str = Depends(get_current_user_id)):
    """Generate a short-lived ephemeral Gemini token for direct client connections.

    Useful for mobile clients (Expo) that want to connect directly to Gemini
    Live API without proxying through this server (lower latency).
    Token is single-use, valid for 30 minutes.
    """
    try:
        return await create_ephemeral_token()
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc))


@router.websocket("/stream")
async def live_stream(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
):
    """Bidirectional Live Agent session.

    The server proxies audio between the client and Gemini Live, executes
    TrustMesh tool calls in-process (direct DB access, Citadel scanning),
    and can inject proactive messages on behalf of the timeline engine.

    Auth: validated via session cookie on the WebSocket handshake.
    """
    await websocket.accept()

    user_id = await _get_ws_user(websocket, db)
    if not user_id:
        await websocket.send_json({"type": "error", "message": "Authentication required"})
        await websocket.close(code=4001)
        return

    from sqlalchemy import select
    from src.models import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        await websocket.close(code=4001)
        return

    networks = await get_user_networks(db, user_id)
    tz = websocket.query_params.get("tz", "UTC")
    log.info(f"Live session started: user={user_id} ({user.display_name}) tz={tz}")

    try:
        await run_live_session(
            websocket=websocket,
            user_id=user_id,
            user_display_name=user.display_name,
            db=db,
            networks=networks,
            tz=tz,
        )
    except WebSocketDisconnect:
        log.info(f"Live session closed: user={user_id}")
    except Exception:
        log.exception(f"Live session crashed: user={user_id}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
