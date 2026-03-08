"""Research event feed — SSE endpoint for live research activity.

Clients (UI tabs) connect here to receive real-time events as agents
browse the web with TinyFish. One stream per authenticated user.
"""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.auth import get_current_user_id
import src.research_bus as research_bus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/research/feed")
async def research_feed(auth_user_id: str = Depends(get_current_user_id)):
    """SSE stream of research events for the authenticated user."""

    async def stream():
        async for event in research_bus.subscribe(auth_user_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
