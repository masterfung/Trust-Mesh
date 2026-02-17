"""
PodOS Timeline API Routes.

REST API for the Timeline Engine — add entries, tick the engine,
read state, push events, and manage hooks. The Zig kernel runs
in-process via the FFI bridge.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


# ═══════════════════════════════════════════
#  ENGINE SINGLETON
# ═══════════════════════════════════════════

_engine = None


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
            _engine.start()
            logger.info("Timeline engine started")
        except ImportError:
            raise HTTPException(503, "Timeline bridge not available")
    return _engine


def _get_optional_engine():
    """Get the engine if it exists, None otherwise."""
    return _engine


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
