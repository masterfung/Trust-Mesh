"""In-memory research event bus.

Agents publish events here as they browse the web. The SSE endpoint
in routes/research.py subscribes per-user and streams events to the UI.

Events are ephemeral — only delivered to connected clients. No persistence.
"""
import asyncio
import logging
from collections import defaultdict
from typing import AsyncGenerator

log = logging.getLogger(__name__)

# user_id → list of subscriber queues
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


async def publish(user_id: str, event: dict) -> None:
    """Publish an event to all subscribers for this user."""
    for q in list(_subscribers.get(user_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow consumer — skip rather than block


async def subscribe(user_id: str) -> AsyncGenerator[dict, None]:
    """Yield events for user_id until the client disconnects."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[user_id].append(q)
    try:
        while True:
            event = await q.get()
            yield event
    finally:
        try:
            _subscribers[user_id].remove(q)
        except ValueError:
            pass
