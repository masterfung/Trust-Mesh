"""
PodOS Timeline API Routes.

REST API for the Timeline Engine — add entries, tick the engine,
read state, push events, and manage hooks. The Zig kernel runs
in-process via the FFI bridge.

The auto-tick loop runs as a background asyncio task, ticking the
engine at the heartbeat interval. Hook callbacks dispatch to the
agent system for AGENT_TASK hooks.
"""

import asyncio
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


# ═══════════════════════════════════════════
#  ENGINE SINGLETON + AUTO-TICK
# ═══════════════════════════════════════════

_engine = None
_tick_task: Optional[asyncio.Task] = None
_hook_queue: asyncio.Queue = asyncio.Queue()


def _get_engine():
    """Get or create the timeline engine singleton."""
    global _engine
    if _engine is None:
        try:
            from src.timeline_bridge import TimelineEngine, is_available

            if not is_available():
                raise HTTPException(
                    503,
                    "Timeline kernel not available — build with: "
                    "cd kernel && zig build",
                )
            _engine = TimelineEngine(heartbeat_ms=5000, max_entries=10000)
            _register_hook_callback(_engine)
            _engine.start()
            logger.info("Timeline engine started")
        except ImportError:
            raise HTTPException(503, "Timeline bridge not available")
    return _engine


def _get_optional_engine():
    """Get the engine if it exists, None otherwise."""
    return _engine


def _register_hook_callback(engine):
    """Register the FFI hook callback that queues hooks for async dispatch."""
    from src.timeline_bridge import _bytes_to_uuid

    def on_hook(entry_id_bytes, hook_index, action_kind, data, data_len):
        eid = _bytes_to_uuid(entry_id_bytes)
        logger.info("Hook fired: entry=%s hook=%d action=%d", eid, hook_index, action_kind)
        try:
            _hook_queue.put_nowait({
                "entry_id": str(eid),
                "hook_index": hook_index,
                "action_kind": action_kind,
                "timestamp_ms": int(time.time() * 1000),
            })
        except asyncio.QueueFull:
            logger.warning("Hook queue full, dropping hook for entry %s", eid)

    engine.register_hook_callback(on_hook)


async def start_auto_tick():
    """Start the auto-tick background loop. Called from app lifespan."""
    global _tick_task
    try:
        engine = _get_engine()
    except Exception:
        logger.info("Timeline kernel not available — auto-tick disabled")
        return
    # Seed demo entries if engine is empty
    if engine.entry_count == 0:
        _seed_demo_entries(engine)
    if _tick_task is None or _tick_task.done():
        _tick_task = asyncio.create_task(_auto_tick_loop(engine))
        logger.info("Auto-tick loop started")


def _seed_demo_entries(engine):
    """Seed the timeline engine with demo entries for the Riverside scenario."""
    from src.timeline_bridge import (
        EntryBuilder,
        EntryType,
        EventSource,
        HookActionKind,
        HookPhase,
        Visibility,
    )

    now_ms = int(time.time() * 1000)
    hour = 3_600_000

    entries = [
        # ── Active health monitoring ──
        {
            "label": "Peter's morning medication reminder",
            "category": "health",
            "salience": 0.9,
            "entry_type": EntryType.REMINDER,
            "cron": "0 8 * * *",  # every day at 8 AM
            "hook": "Remind Peter about his morning medications. Check his medication capsule for details.",
        },
        {
            "label": "Monitor health capsule updates",
            "category": "health",
            "salience": 0.8,
            "entry_type": EntryType.HOOK,
            "event": "capsule.created.health",
            "hook": "A new health capsule was created. Review it and notify the Care Circle if it's important.",
        },
        {
            "label": "Weekly family check-in",
            "category": "family",
            "salience": 0.6,
            "entry_type": EntryType.TASK,
            "cron": "0 10 * * 0",  # Sundays at 10 AM
            "hook": "Time for the weekly family check-in. Query family members' agents for any updates or needs.",
        },
        # ── Upcoming appointments (time-triggered) ──
        {
            "label": "Dr. Lee follow-up appointment prep",
            "category": "health",
            "salience": 0.85,
            "entry_type": EntryType.TASK,
            "at_ms": now_ms + 2 * hour,  # 2 hours from now
            "hook": "Prepare for Peter's follow-up with Dr. Lee. Search vault for recent health updates and compile a summary.",
        },
        {
            "label": "Check prescription refill status",
            "category": "health",
            "salience": 0.7,
            "entry_type": EntryType.TASK,
            "at_ms": now_ms + 4 * hour,  # 4 hours from now
            "hook": "Check if Peter's prescriptions need refilling. Query Riverside Hospital's agent for pharmacy status.",
        },
        # ── Event-triggered reactions ──
        {
            "label": "React to new capsule creation",
            "category": "general",
            "salience": 0.5,
            "entry_type": EntryType.HOOK,
            "event": "capsule.updated.health",
            "hook": "A health capsule was updated. Check if emergency contacts need to be notified.",
        },
        {
            "label": "React to timeline entry completion",
            "category": "general",
            "salience": 0.4,
            "entry_type": EntryType.HOOK,
            "event": "timeline.entry_completed",
            "hook": "A timeline entry was completed. Check if there are follow-up tasks to create.",
        },
        # ── Dormant entries (need manual activation) ──
        {
            "label": "Emergency contact alert protocol",
            "category": "health",
            "salience": 1.0,
            "entry_type": EntryType.SIGNAL,
            "event": "emergency.triggered",
            "hook": "EMERGENCY: Activate the emergency contact chain. Query all Care Circle members immediately.",
        },
    ]

    count = 0
    for e in entries:
        builder = (
            EntryBuilder()
            .set_label(e["label"])
            .set_category(e["category"])
            .set_salience(e["salience"])
            .set_entry_type(e["entry_type"])
            .set_visibility(Visibility.PRIVATE)
        )

        if "cron" in e:
            builder.set_trigger_cron(e["cron"])
        elif "at_ms" in e:
            builder.set_trigger_time(e["at_ms"])
        elif "event" in e:
            builder.set_trigger_event(EventSource.SYSTEM, e["event"])

        if "hook" in e:
            builder.add_hook(
                action=HookActionKind.AGENT_TASK,
                phase=HookPhase.PRE,
                prompt=e["hook"],
            )

        engine.add_entry(builder)
        count += 1

    logger.info("Seeded %d demo timeline entries", count)


async def stop_auto_tick():
    """Stop the auto-tick background loop. Called from app shutdown."""
    global _tick_task
    if _tick_task and not _tick_task.done():
        _tick_task.cancel()
        try:
            await _tick_task
        except asyncio.CancelledError:
            pass
        _tick_task = None
    engine = _get_optional_engine()
    if engine:
        engine.stop()
    logger.info("Auto-tick loop stopped")


async def _auto_tick_loop(engine):
    """Background loop: tick the engine at its heartbeat interval."""
    heartbeat_sec = 5.0  # default 5s
    logger.info("Auto-tick loop running (heartbeat=%.1fs)", heartbeat_sec)
    while True:
        try:
            # Check next wake time from kernel
            next_wake = engine.next_wake_at
            now_ms = int(time.time() * 1000)
            if next_wake > 0 and next_wake > now_ms:
                sleep_sec = min((next_wake - now_ms) / 1000.0, heartbeat_sec)
            else:
                sleep_sec = heartbeat_sec

            await asyncio.sleep(sleep_sec)

            if engine.is_running:
                engine.tick()
                # Process any queued hooks
                await _dispatch_queued_hooks(engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Auto-tick error")
            await asyncio.sleep(1.0)


async def _dispatch_queued_hooks(engine):
    """Process queued hook callbacks — dispatch AGENT_TASK hooks to the agent."""
    from src.timeline_bridge import HookActionKind

    while not _hook_queue.empty():
        try:
            hook = _hook_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        action = hook["action_kind"]
        entry_id = hook["entry_id"]
        hook_index = hook["hook_index"]

        if action == int(HookActionKind.AGENT_TASK):
            # Dispatch to agent system
            try:
                await _dispatch_agent_hook(engine, entry_id, hook_index)
            except Exception:
                logger.exception("Agent hook dispatch failed for entry %s", entry_id)
                # Mark hook as failed so engine can continue
                try:
                    engine.complete_hook(uuid.UUID(entry_id), hook_index, False)
                except Exception:
                    pass
        elif action == int(HookActionKind.NOTIFY):
            # Log notification hooks
            logger.info("NOTIFY hook for entry %s (hook %d)", entry_id, hook_index)
            engine.complete_hook(uuid.UUID(entry_id), hook_index, True)
        else:
            # Unknown hook type — auto-complete
            engine.complete_hook(uuid.UUID(entry_id), hook_index, True)


async def _dispatch_agent_hook(engine, entry_id_str: str, hook_index: int):
    """Dispatch an AGENT_TASK hook to the AI agent for processing."""
    eid = uuid.UUID(entry_id_str)
    label = engine.get_entry_label(eid) or "unknown"
    category = engine.get_entry_category(eid) or "general"

    logger.info("Dispatching agent hook: entry=%s label=%s", entry_id_str, label)

    # Build a prompt from the entry's hook data
    prompt = f"Timeline hook fired for entry '{label}' (category: {category}). Process this entry and take appropriate action."

    # Try to dispatch to agent system
    try:
        from src.database import async_session
        from src.gossip import query_agent

        async with async_session() as db:
            # Use the first demo user's agent for now
            # In production, entries would have an owner_id field
            from sqlalchemy import select
            from src.models import User
            result = await db.execute(
                select(User).where(User.is_demo == True).limit(1)  # noqa: E712
            )
            user = result.scalar_one_or_none()
            if not user:
                logger.warning("No user found for agent hook dispatch")
                engine.complete_hook(eid, hook_index, False)
                return

            from src.main import vault_keys
            vk = vault_keys.get(user.id)
            if not vk:
                logger.warning("No vault key for user %s", user.id)
                engine.complete_hook(eid, hook_index, False)
                return

            result = await query_agent(
                db=db,
                from_user_id=user.id,
                to_user_id=user.id,  # self-query
                question=prompt,
                vault_keys=vault_keys,
            )
            response = result.get("response", "")
            logger.info("Agent response for hook: %s", response[:200] if response else "empty")
            engine.complete_hook(eid, hook_index, True)
    except Exception:
        logger.exception("Agent hook dispatch failed")
        engine.complete_hook(eid, hook_index, False)


# ═══════════════════════════════════════════
#  REQUEST/RESPONSE SCHEMAS
# ═══════════════════════════════════════════


class TriggerConfig(BaseModel):
    kind: str = "manual"  # time, event, absence, manual
    at_ms: Optional[int] = None  # for time trigger
    cron: Optional[str] = None  # for cron trigger
    event_type: Optional[str] = None  # for event trigger
    event_source: Optional[int] = None  # EventSource enum value
    absence_event_type: Optional[str] = None  # for absence trigger
    absence_deadline_ms: Optional[int] = None


class DependencyConfig(BaseModel):
    entry_id: str  # UUID string
    required_state: int = 3  # EntryState.ACTIVE
    is_hard: bool = True


class HookConfig(BaseModel):
    action: int = 1  # HookActionKind.NOTIFY
    phase: int = 0  # HookPhase.PRE
    prompt: str = ""
    timeout_ms: int = 30000
    max_retries: int = 0


class CreateEntryRequest(BaseModel):
    label: str = Field(..., max_length=128)
    category: str = Field("general", max_length=32)
    entry_type: int = 0  # EntryType.EVENT
    visibility: int = 3  # Visibility.PRIVATE
    salience: float = Field(0.5, ge=0.0, le=1.0)
    window_start_ms: Optional[int] = None
    window_end_ms: Optional[int] = None
    activation_trigger: Optional[TriggerConfig] = None
    deactivation_trigger: Optional[TriggerConfig] = None
    dependencies: list[DependencyConfig] = []
    hooks: list[HookConfig] = []


class PushEventRequest(BaseModel):
    event_type: str = Field(..., max_length=64)
    source: int = 0  # EventSource.SYSTEM
    timestamp_ms: Optional[int] = None


class TransitionRequest(BaseModel):
    new_state: int  # EntryState enum value


class HookCompleteRequest(BaseModel):
    hook_index: int
    success: bool


class EntryResponse(BaseModel):
    id: str
    label: str
    category: str
    state: int
    state_name: str
    salience: float
    visibility: int


class EngineStateResponse(BaseModel):
    active_count: int
    pending_count: int
    dormant_count: int
    failed_count: int
    total_count: int
    tick_count: int
    signal_count: int
    is_running: bool
    signals: list[dict] = []
    active_ids: list[str] = []


# ═══════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════


@router.get("/state")
async def get_timeline_state(
    auth_user_id: str = Depends(get_current_user_id),
) -> EngineStateResponse:
    """Get the current central state of the timeline engine."""
    engine = _get_engine()

    state = engine.state
    return EngineStateResponse(
        active_count=state.active_count,
        pending_count=state.pending_count,
        dormant_count=state.dormant_count,
        failed_count=state.failed_count,
        total_count=state.total_count,
        tick_count=state.tick_count,
        signal_count=state.signal_count,
        is_running=engine.is_running,
        signals=[
            {
                "severity": s.severity.name.lower(),
                "message": s.message,
                "related_entry_id": str(s.related_entry_id),
            }
            for s in state.signals
        ],
        active_ids=[str(uid) for uid in state.active_ids],
    )


@router.post("/tick")
async def tick_engine(
    auth_user_id: str = Depends(get_current_user_id),
) -> dict:
    """Manually advance the engine by one tick."""
    engine = _get_engine()
    engine.tick()
    return {
        "tick_count": engine.tick_count,
        "next_wake_at": engine.next_wake_at,
    }


@router.post("/entries")
async def create_entry(
    req: CreateEntryRequest,
    auth_user_id: str = Depends(get_current_user_id),
) -> EntryResponse:
    """Create and add a new timeline entry."""
    from src.timeline_bridge import (
        EntryBuilder,
        EntryState,
        EntryType,
        EventSource,
        HookActionKind,
        HookPhase,
        Visibility,
    )

    engine = _get_engine()
    builder = EntryBuilder()
    builder.set_label(req.label)
    builder.set_category(req.category)
    builder.set_entry_type(EntryType(req.entry_type))
    builder.set_visibility(Visibility(req.visibility))
    builder.set_salience(req.salience)

    if req.window_start_ms is not None and req.window_end_ms is not None:
        builder.set_window(req.window_start_ms, req.window_end_ms)

    # Activation trigger
    if req.activation_trigger:
        t = req.activation_trigger
        if t.kind == "time" and t.at_ms is not None:
            builder.set_trigger_time(t.at_ms)
        elif t.kind == "time" and t.cron is not None:
            builder.set_trigger_cron(t.cron)
        elif t.kind == "event" and t.event_type is not None:
            builder.set_trigger_event(
                EventSource(t.event_source or 0), t.event_type
            )
        elif t.kind == "absence" and t.absence_event_type and t.absence_deadline_ms:
            builder.set_trigger_absence(
                t.absence_event_type, t.absence_deadline_ms
            )

    # Deactivation trigger
    if req.deactivation_trigger and req.deactivation_trigger.at_ms:
        builder.set_deactivation_time(req.deactivation_trigger.at_ms)

    # Dependencies
    for dep in req.dependencies:
        builder.add_dependency(
            uuid.UUID(dep.entry_id),
            EntryState(dep.required_state),
            dep.is_hard,
        )

    # Hooks
    for hook in req.hooks:
        builder.add_hook(
            action=HookActionKind(hook.action),
            phase=HookPhase(hook.phase),
            prompt=hook.prompt,
            timeout_ms=hook.timeout_ms,
            max_retries=hook.max_retries,
        )

    entry_id = engine.add_entry(builder)
    state_val = engine.get_entry_state(entry_id)
    state_name = EntryState(state_val).name if state_val is not None else "unknown"

    return EntryResponse(
        id=str(entry_id),
        label=req.label,
        category=req.category,
        state=state_val if state_val is not None else 0,
        state_name=state_name,
        salience=req.salience,
        visibility=req.visibility,
    )


@router.get("/entries")
async def list_entries(
    auth_user_id: str = Depends(get_current_user_id),
) -> list[EntryResponse]:
    """List all entries in the timeline engine."""
    from src.timeline_bridge import EntryState

    engine = _get_engine()
    ids = engine.get_all_entry_ids()
    entries = []
    for eid in ids:
        state_val = engine.get_entry_state(eid)
        if state_val is None:
            continue
        label = engine.get_entry_label(eid) or ""
        category = engine.get_entry_category(eid) or ""
        salience = engine.get_entry_salience(eid) or 0.0
        vis = engine.get_entry_visibility(eid)
        entries.append(EntryResponse(
            id=str(eid),
            label=label,
            category=category,
            state=state_val,
            state_name=EntryState(state_val).name,
            salience=salience,
            visibility=vis if vis is not None else 3,
        ))
    return entries


@router.get("/entries/{entry_id}")
async def get_entry(
    entry_id: str,
    auth_user_id: str = Depends(get_current_user_id),
) -> EntryResponse:
    """Get a specific entry by ID."""
    from src.timeline_bridge import EntryState

    engine = _get_engine()
    eid = uuid.UUID(entry_id)
    state_val = engine.get_entry_state(eid)
    if state_val is None:
        raise HTTPException(404, "Entry not found")

    label = engine.get_entry_label(eid) or ""
    category = engine.get_entry_category(eid) or ""
    salience = engine.get_entry_salience(eid) or 0.0
    vis = engine.get_entry_visibility(eid)

    return EntryResponse(
        id=str(eid),
        label=label,
        category=category,
        state=state_val,
        state_name=EntryState(state_val).name,
        salience=salience,
        visibility=vis if vis is not None else 3,
    )


@router.post("/entries/{entry_id}/transition")
async def transition_entry(
    entry_id: str,
    req: TransitionRequest,
    auth_user_id: str = Depends(get_current_user_id),
) -> EntryResponse:
    """Manually transition an entry to a new state."""
    from src.timeline_bridge import EntryState

    engine = _get_engine()
    eid = uuid.UUID(entry_id)

    state_before = engine.get_entry_state(eid)
    if state_before is None:
        raise HTTPException(404, "Entry not found")

    try:
        engine.transition_entry(eid, EntryState(req.new_state))
    except RuntimeError as e:
        raise HTTPException(400, f"Invalid transition: {e}")

    state_after = engine.get_entry_state(eid)
    label = engine.get_entry_label(eid) or ""
    category = engine.get_entry_category(eid) or ""
    salience = engine.get_entry_salience(eid) or 0.0
    vis = engine.get_entry_visibility(eid)

    return EntryResponse(
        id=str(eid),
        label=label,
        category=category,
        state=state_after if state_after is not None else 0,
        state_name=EntryState(state_after).name if state_after is not None else "unknown",
        salience=salience,
        visibility=vis if vis is not None else 3,
    )


@router.post("/events")
async def push_event(
    req: PushEventRequest,
    auth_user_id: str = Depends(get_current_user_id),
) -> dict:
    """Push an event into the timeline event queue."""
    from src.timeline_bridge import EventSource

    engine = _get_engine()
    engine.push_event(
        event_type=req.event_type,
        source=EventSource(req.source),
        timestamp_ms=req.timestamp_ms or 0,
    )
    return {"status": "ok", "event_type": req.event_type}


@router.post("/entries/{entry_id}/hooks/{hook_index}/complete")
async def complete_hook(
    entry_id: str,
    hook_index: int,
    req: HookCompleteRequest,
    auth_user_id: str = Depends(get_current_user_id),
) -> dict:
    """Complete a hook callback (mark as success or failure)."""
    engine = _get_engine()
    eid = uuid.UUID(entry_id)

    try:
        engine.complete_hook(eid, req.hook_index, req.success)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    return {"status": "ok", "entry_id": entry_id, "hook_index": hook_index}


@router.post("/start")
async def start_engine(
    auth_user_id: str = Depends(get_current_user_id),
) -> dict:
    """Start the timeline engine."""
    engine = _get_engine()
    engine.start()
    return {"status": "running"}


@router.post("/stop")
async def stop_engine(
    auth_user_id: str = Depends(get_current_user_id),
) -> dict:
    """Stop the timeline engine."""
    engine = _get_engine()
    engine.stop()
    return {"status": "stopped"}


@router.get("/health")
async def timeline_health() -> dict:
    """Health check for the timeline engine (no auth required)."""
    from src.timeline_bridge import is_available

    if not is_available():
        return {
            "status": "unavailable",
            "kernel_built": False,
            "message": "Build kernel: cd kernel && zig build",
        }

    engine = _get_optional_engine()
    if engine is None:
        return {
            "status": "not_started",
            "kernel_built": True,
            "message": "Engine not yet initialized",
        }

    return {
        "status": "running" if engine.is_running else "stopped",
        "kernel_built": True,
        "tick_count": engine.tick_count,
        "entry_count": engine.entry_count,
        "version": engine.version(),
    }
