"""Thread-safe registry of active Gemini Live sessions for proactive injection.

Allows the Timeline engine (and other system components) to inject messages
into an active Live session without any manual trigger. If the user has no
active session, inject is silently dropped — no crash, no fake message.

Usage:
    # On session start
    q = asyncio.Queue()
    await live_sessions.register(user_id, q)

    # From timeline hook / external event
    await live_sessions.inject(user_id, "Found a scheduling conflict: ...")

    # On session end
    await live_sessions.unregister(user_id)
"""

import asyncio
import logging

log = logging.getLogger(__name__)

# user_id -> asyncio.Queue[str]
_active: dict[str, asyncio.Queue] = {}


async def register(user_id: str, queue: asyncio.Queue) -> None:
    """Register an active live session queue for a user."""
    _active[user_id] = queue
    log.info("Live session registered: user=%s", user_id)


async def unregister(user_id: str) -> None:
    """Unregister a live session when it ends."""
    _active.pop(user_id, None)
    log.info("Live session unregistered: user=%s", user_id)


async def inject(user_id: str, text: str) -> bool:
    """Inject a proactive message into an active live session.

    Returns True if the session was active and the message was queued.
    Returns False if the user has no active session (silently dropped).
    """
    queue = _active.get(user_id)
    if queue is None:
        log.debug("Inject dropped — no active session for user=%s", user_id)
        return False
    await queue.put(text)
    log.info("Injected into live session: user=%s text=%.60s...", user_id, text)
    return True


def is_active(user_id: str) -> bool:
    """Check if a user has an active live session."""
    return user_id in _active
