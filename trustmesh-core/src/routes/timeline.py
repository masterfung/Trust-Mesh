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
import ctypes
import json
import logging
import os
import threading
import time
import uuid
from ctypes import c_uint32
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.auth import get_current_user_id, get_optional_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

POOL_SYNC_SECRET = os.getenv("TRUSTMESH_POOL_SYNC_SECRET", "")


# ═══════════════════════════════════════════
#  ENGINE SINGLETON + AUTO-TICK
# ═══════════════════════════════════════════

_engine = None
_tick_task: Optional[asyncio.Task] = None
_hook_queue: asyncio.Queue = asyncio.Queue()

_persist_db_handle = None
_persist_lock = threading.RLock()

# In-memory spec cache for rich entry metadata (trigger, hook, dep info).
_entry_spec_cache: dict[str, dict] = {}


def _cache_spec(entry_id, spec: dict) -> None:
    _entry_spec_cache[str(entry_id)] = spec


def _load_specs_into_cache() -> None:
    """Bulk-load persisted specs into the in-memory cache."""
    specs = _persist_load_json_array("podos_timeline_entries_load", b"", 0)
    for s in specs:
        sid = s.get("id") or s.get("entry_id")
        if sid:
            _entry_spec_cache[str(sid)] = s


def _get_entry_spec(entry_id: str) -> dict | None:
    eid_str = str(entry_id)
    if eid_str in _entry_spec_cache:
        return _entry_spec_cache[eid_str]
    # Lazy bulk-load from persist DB
    if not _entry_spec_cache:
        _load_specs_into_cache()
    return _entry_spec_cache.get(eid_str)


async def require_auth_or_pool_secret(request: Request) -> str:
    """Allow either a user session cookie or the pool sync secret (pod-to-pod)."""
    if POOL_SYNC_SECRET:
        secret = request.headers.get("X-Pool-Sync-Secret", "")
        if secret == POOL_SYNC_SECRET:
            return "pool_sync"
    user_id = await get_optional_user_id(request)
    if user_id:
        return user_id
    raise HTTPException(401, "Authentication required")


def _get_persist_db():
    """Get or open the Zig-side SQLite handle used for timeline persistence."""
    global _persist_db_handle
    if _persist_db_handle is not None:
        return _persist_db_handle

    from src.timeline_bridge import _get_lib

    db_path = os.getenv("TRUSTMESH_DB", "./trustmesh.db")
    lib = _get_lib()
    path_b = db_path.encode("utf-8")
    handle = lib.podos_db_open(path_b, len(path_b))
    if not handle:
        logger.warning("Timeline persistence DB open failed (path=%s)", db_path)
        return None
    _persist_db_handle = handle
    return _persist_db_handle


def _close_persist_db() -> None:
    global _persist_db_handle
    if _persist_db_handle is None:
        return
    try:
        from src.timeline_bridge import _get_lib
        lib = _get_lib()
        lib.podos_db_close(_persist_db_handle)
    except Exception:
        pass
    _persist_db_handle = None


def persist_entry_spec(*, owner_id: str, entry_id: uuid.UUID, state: int, spec: dict) -> None:
    """Persist an entry spec JSON so the engine can restore after restart."""
    from src.timeline_bridge import _get_lib

    handle = _get_persist_db()
    if not handle:
        return

    eid_b = str(entry_id).encode("utf-8")
    owner_b = (owner_id or "").encode("utf-8")
    spec_json_b = json.dumps(spec, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    with _persist_lock:
        lib = _get_lib()
        rc = lib.podos_timeline_entry_upsert(
            handle,
            eid_b, len(eid_b),
            owner_b, len(owner_b),
            int(state),
            spec_json_b, len(spec_json_b),
        )
        if rc < 0:
            logger.warning("Timeline persist upsert failed: entry=%s rc=%s", entry_id, rc)


def persist_update_state(*, entry_id: uuid.UUID, state: int) -> None:
    """Best-effort mirror of entry state to DB (not authoritative)."""
    from src.timeline_bridge import _get_lib

    handle = _get_persist_db()
    if not handle:
        return

    eid_b = str(entry_id).encode("utf-8")
    with _persist_lock:
        lib = _get_lib()
        rc = lib.podos_timeline_entry_update_state(handle, eid_b, len(eid_b), int(state))
        if rc < 0:
            logger.warning("Timeline persist state update failed: entry=%s rc=%s", entry_id, rc)


def _persist_append_outbox_event(*, tick: int, event: dict) -> None:
    from src.timeline_bridge import _get_lib

    handle = _get_persist_db()
    if not handle:
        return
    event_json_b = json.dumps(event, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    with _persist_lock:
        lib = _get_lib()
        rc = lib.podos_timeline_outbox_append(handle, int(tick), event_json_b, len(event_json_b))
        if rc < 0:
            logger.warning("Timeline outbox append failed: rc=%s", rc)


def _persist_mark_inbox_event(*, event_id: str, event: dict) -> None:
    from src.timeline_bridge import _get_lib

    handle = _get_persist_db()
    if not handle:
        return
    event_id_b = event_id.encode("utf-8")
    event_json_b = json.dumps(event, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    with _persist_lock:
        lib = _get_lib()
        rc = lib.podos_timeline_inbox_mark(handle, event_id_b, len(event_id_b), event_json_b, len(event_json_b))
        if rc < 0:
            logger.warning("Timeline inbox mark failed: rc=%s", rc)


def _persist_load_json_array(fn_name: str, *args) -> list:
    """Call a Zig function that writes a JSON array into an output buffer."""
    from src.timeline_bridge import _get_lib

    handle = _get_persist_db()
    if not handle:
        return []

    lib = _get_lib()
    fn = getattr(lib, fn_name)

    # Retry with an expanding buffer when Zig reports "buffer too small" (-3).
    buf_size = 64 * 1024
    for _ in range(6):
        out_buf = ctypes.create_string_buffer(buf_size)
        out_len = c_uint32(0)
        with _persist_lock:
            rc = fn(handle, *args, out_buf, buf_size, ctypes.byref(out_len))
        if rc == 0:
            raw = out_buf.raw[: out_len.value].decode("utf-8")
            try:
                val = json.loads(raw)
                return val if isinstance(val, list) else []
            except json.JSONDecodeError:
                return []
        if rc != -3:
            return []
        buf_size *= 2
    return []


def _persist_get_entry_owner_id(entry_id: uuid.UUID) -> str | None:
    """Lookup persisted owner_id for an entry (used for hook->agent dispatch)."""
    from src.timeline_bridge import _get_lib

    handle = _get_persist_db()
    if not handle:
        return None

    eid_b = str(entry_id).encode("utf-8")
    out_buf = ctypes.create_string_buffer(128)
    out_len = c_uint32(0)
    with _persist_lock:
        lib = _get_lib()
        rc = lib.podos_timeline_entry_get_owner(
            handle,
            eid_b, len(eid_b),
            out_buf, 128,
            ctypes.byref(out_len),
        )
    if rc != 0 or out_len.value <= 0:
        return None
    try:
        owner = out_buf.raw[: out_len.value].decode("utf-8")
        # Owner IDs are UUIDs in normal pods; anything else is likely demo/placeholder.
        if len(owner) == 36:
            return owner
    except Exception:
        return None
    return None


def _restore_persisted_entries(engine) -> int:
    """Restore persisted timeline entries into a fresh engine."""
    from src.timeline_bridge import (
        EntryBuilder,
        EntryState,
        EntryType,
        EventSource,
        HookActionKind,
        HookPhase,
        Visibility,
    )

    specs = _persist_load_json_array("podos_timeline_entries_load", b"", 0)
    if not specs:
        return 0

    restored = 0
    for spec in specs:
        try:
            entry_id_str = spec.get("id") or spec.get("entry_id")
            if not entry_id_str:
                continue
            entry_uuid = uuid.UUID(entry_id_str)

            builder = EntryBuilder().set_id(entry_uuid)
            builder.set_label(spec.get("label", ""))
            builder.set_category(spec.get("category", "general"))
            builder.set_entry_type(EntryType(int(spec.get("entry_type", 0))))
            builder.set_visibility(Visibility(int(spec.get("visibility", 3))))
            builder.set_salience(float(spec.get("salience", 0.5)))

            ws = spec.get("window_start_ms")
            we = spec.get("window_end_ms")
            if ws is not None and we is not None:
                builder.set_window(int(ws), int(we))

            act = spec.get("activation_trigger") or None
            if isinstance(act, dict):
                kind = act.get("kind", "manual")
                if kind == "time" and act.get("at_ms") is not None:
                    builder.set_trigger_time(int(act["at_ms"]))
                elif kind == "time" and act.get("cron") is not None:
                    builder.set_trigger_cron(str(act["cron"]))
                elif kind == "event" and act.get("event_type") is not None:
                    builder.set_trigger_event(
                        EventSource(int(act.get("event_source", 0))),
                        str(act["event_type"]),
                    )
                elif kind == "absence" and act.get("absence_event_type") and act.get("absence_deadline_ms"):
                    builder.set_trigger_absence(
                        str(act["absence_event_type"]),
                        int(act["absence_deadline_ms"]),
                    )

            deact = spec.get("deactivation_trigger") or None
            if isinstance(deact, dict) and deact.get("at_ms") is not None:
                builder.set_deactivation_time(int(deact["at_ms"]))

            for dep in spec.get("dependencies") or []:
                if not isinstance(dep, dict):
                    continue
                dep_id = dep.get("entry_id")
                if not dep_id:
                    continue
                builder.add_dependency(
                    uuid.UUID(dep_id),
                    EntryState(int(dep.get("required_state", 3))),
                    bool(dep.get("is_hard", True)),
                )

            # Local specs may include hooks; for now, restore them verbatim.
            for hook in spec.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                builder.add_hook(
                    action=HookActionKind(int(hook.get("action", 1))),
                    phase=HookPhase(int(hook.get("phase", 0))),
                    prompt=str(hook.get("prompt", "")),
                    timeout_ms=int(hook.get("timeout_ms", 30000)),
                    max_retries=int(hook.get("max_retries", 0)),
                )

            engine.add_entry(builder)
            restored += 1
        except Exception:
            logger.exception("Failed to restore persisted timeline entry")
            continue

    if restored:
        # Let other entries react to restore (optional, safe).
        try:
            engine.push_event("timeline.entries_restored", EventSource.SYSTEM)
        except Exception:
            pass

    return restored


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
            # Attach the Zig-side DB handle so the kernel can durably log transitions.
            try:
                handle = _get_persist_db()
                if handle:
                    _engine.attach_persist_db(handle)
            except Exception:
                logger.exception("Failed to attach persistence DB to engine")
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
    # Restore persisted entries (durable) before seeding demo entries.
    if engine.entry_count == 0:
        try:
            restored = _restore_persisted_entries(engine)
            if restored:
                logger.info("Restored %d persisted timeline entries", restored)
        except Exception:
            logger.exception("Timeline persistence restore failed")
    # Seed demo entries if still empty
    if engine.entry_count == 0:
        _seed_demo_entries(engine)
        _seed_cme_entries(engine)
        _seed_credential_entries(engine)
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

        entry_id = engine.add_entry(builder)
        # Persist demo entries so seeding is one-time per DB file.
        try:
            state_val = engine.get_entry_state(entry_id)
            spec = {
                "id": str(entry_id),
                "owner_id": "demo",
                "label": e["label"],
                "category": e["category"],
                "entry_type": int(e["entry_type"]),
                "visibility": int(Visibility.PRIVATE),
                "salience": float(e["salience"]),
                "window_start_ms": None,
                "window_end_ms": None,
                "activation_trigger": (
                    {"kind": "time", "cron": e["cron"]} if "cron" in e else
                    {"kind": "time", "at_ms": e["at_ms"]} if "at_ms" in e else
                    {"kind": "event", "event_source": int(EventSource.SYSTEM), "event_type": e["event"]} if "event" in e else
                    {"kind": "manual"}
                ),
                "deactivation_trigger": None,
                "dependencies": [],
                "hooks": [{
                    "action": int(HookActionKind.AGENT_TASK),
                    "phase": int(HookPhase.PRE),
                    "prompt": e.get("hook", ""),
                    "timeout_ms": 30000,
                    "max_retries": 0,
                }] if e.get("hook") else [],
            }
            persist_entry_spec(
                owner_id="demo",
                entry_id=entry_id,
                state=int(state_val) if state_val is not None else 0,
                spec=spec,
            )
            _cache_spec(entry_id, spec)
        except Exception:
            logger.exception("Failed to persist demo timeline entry")
        count += 1

    logger.info("Seeded %d demo timeline entries", count)


def _seed_cme_entries(engine):
    """Seed CME (Capsule Memory Engine) autonomous operation entries.

    These entries form a dependency chain:
      sweep (cron) → consolidation (event) → forgetting (dep) → results (dep)
    Plus an absence monitor for SLA and a cross-visibility demo entry.
    """
    from src.timeline_bridge import (
        EntryBuilder,
        EntryState,
        EntryType,
        EventSource,
        HookActionKind,
        HookPhase,
        Visibility,
    )

    now_ms = int(time.time() * 1000)
    hour = 3_600_000

    def _persist_and_cache(eid, spec):
        try:
            state_val = engine.get_entry_state(eid)
            persist_entry_spec(
                owner_id="demo",
                entry_id=eid,
                state=int(state_val) if state_val is not None else 0,
                spec=spec,
            )
            _cache_spec(eid, spec)
        except Exception:
            logger.exception("Failed to persist CME entry %s", eid)

    # 1. Memory Decay Sweep — chain root, cron-triggered
    sweep = (
        EntryBuilder()
        .set_label("Memory Decay Sweep")
        .set_category("system")
        .set_salience(0.1)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.TASK)
        .set_trigger_cron("0 * * * *")
    )
    sweep.add_hook(
        action=HookActionKind.PIPELINE,
        phase=HookPhase.PRE,
        prompt="podos_memory_sweep",
    )
    sweep_id = engine.add_entry(sweep)
    _persist_and_cache(sweep_id, {
        "id": str(sweep_id), "owner_id": "demo",
        "label": "Memory Decay Sweep", "category": "system",
        "entry_type": int(EntryType.TASK), "visibility": int(Visibility.PRIVATE),
        "salience": 0.1,
        "activation_trigger": {"kind": "time", "cron": "0 * * * *"},
        "deactivation_trigger": None, "dependencies": [],
        "hooks": [{"action": int(HookActionKind.PIPELINE), "phase": int(HookPhase.PRE),
                    "prompt": "podos_memory_sweep", "timeout_ms": 30000, "max_retries": 0}],
    })

    # 2. Memory Consolidation — event-triggered by sweep completion
    consolidation = (
        EntryBuilder()
        .set_label("Memory Consolidation")
        .set_category("system")
        .set_salience(0.2)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.TASK)
        .set_trigger_event(EventSource.SYSTEM, "memory.sweep_completed")
    )
    consolidation.add_hook(
        action=HookActionKind.AGENT_TASK,
        phase=HookPhase.PRE,
        prompt="Review capsule clusters and consolidate overlapping temporary memories.",
    )
    consolidation_id = engine.add_entry(consolidation)
    _persist_and_cache(consolidation_id, {
        "id": str(consolidation_id), "owner_id": "demo",
        "label": "Memory Consolidation", "category": "system",
        "entry_type": int(EntryType.TASK), "visibility": int(Visibility.PRIVATE),
        "salience": 0.2,
        "activation_trigger": {"kind": "event", "event_source": int(EventSource.SYSTEM),
                                "event_type": "memory.sweep_completed"},
        "deactivation_trigger": None, "dependencies": [],
        "hooks": [{"action": int(HookActionKind.AGENT_TASK), "phase": int(HookPhase.PRE),
                    "prompt": "Review capsule clusters and consolidate overlapping temporary memories.",
                    "timeout_ms": 30000, "max_retries": 0}],
    })

    # 3. Memory Forgetting — depends on consolidation COMPLETED
    forgetting = (
        EntryBuilder()
        .set_label("Memory Forgetting")
        .set_category("system")
        .set_salience(0.1)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.TASK)
    )
    forgetting.add_dependency(consolidation_id, EntryState.COMPLETED, is_hard=True)
    forgetting.add_hook(
        action=HookActionKind.PIPELINE,
        phase=HookPhase.PRE,
        prompt="podos_memory_forget",
    )
    forgetting_id = engine.add_entry(forgetting)
    _persist_and_cache(forgetting_id, {
        "id": str(forgetting_id), "owner_id": "demo",
        "label": "Memory Forgetting", "category": "system",
        "entry_type": int(EntryType.TASK), "visibility": int(Visibility.PRIVATE),
        "salience": 0.1,
        "activation_trigger": {"kind": "manual"},
        "deactivation_trigger": None,
        "dependencies": [{"entry_id": str(consolidation_id),
                           "required_state": int(EntryState.COMPLETED), "is_hard": True}],
        "hooks": [{"action": int(HookActionKind.PIPELINE), "phase": int(HookPhase.PRE),
                    "prompt": "podos_memory_forget", "timeout_ms": 30000, "max_retries": 0}],
    })

    # 4. Sweep SLA Monitor — absence trigger if sweep doesn't complete in 2h
    sla_monitor = (
        EntryBuilder()
        .set_label("Sweep SLA Monitor")
        .set_category("system")
        .set_salience(0.3)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.SIGNAL)
        .set_trigger_absence("memory.sweep_completed", now_ms + 2 * hour)
    )
    sla_monitor.add_hook(
        action=HookActionKind.NOTIFY,
        phase=HookPhase.PRE,
        prompt="Memory sweep hasn't completed in 2 hours. Check system health.",
    )
    sla_id = engine.add_entry(sla_monitor)
    _persist_and_cache(sla_id, {
        "id": str(sla_id), "owner_id": "demo",
        "label": "Sweep SLA Monitor", "category": "system",
        "entry_type": int(EntryType.SIGNAL), "visibility": int(Visibility.PRIVATE),
        "salience": 0.3,
        "activation_trigger": {"kind": "absence", "absence_event_type": "memory.sweep_completed",
                                "absence_deadline_ms": now_ms + 2 * hour},
        "deactivation_trigger": None, "dependencies": [],
        "hooks": [{"action": int(HookActionKind.NOTIFY), "phase": int(HookPhase.PRE),
                    "prompt": "Memory sweep hasn't completed in 2 hours. Check system health.",
                    "timeout_ms": 30000, "max_retries": 0}],
    })

    # 5. Last Sweep Results — passive DATA entry for observability
    results = (
        EntryBuilder()
        .set_label("Last Sweep Results")
        .set_category("system.metrics")
        .set_salience(0.05)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.DATA)
    )
    results_id = engine.add_entry(results)
    _persist_and_cache(results_id, {
        "id": str(results_id), "owner_id": "demo",
        "label": "Last Sweep Results", "category": "system.metrics",
        "entry_type": int(EntryType.DATA), "visibility": int(Visibility.PRIVATE),
        "salience": 0.05,
        "activation_trigger": {"kind": "manual"},
        "deactivation_trigger": None, "dependencies": [], "hooks": [],
    })

    # 6. Hospital Health Monitor — INTERNAL visibility (cross-pod sync demo)
    hospital_monitor = (
        EntryBuilder()
        .set_label("Hospital Health Monitor")
        .set_category("health")
        .set_salience(0.6)
        .set_visibility(Visibility.INTERNAL)
        .set_entry_type(EntryType.HOOK)
        .set_trigger_event(EventSource.SYSTEM, "capsule.created.health")
    )
    hospital_monitor.add_hook(
        action=HookActionKind.AGENT_TASK,
        phase=HookPhase.PRE,
        prompt="A health capsule was created. Notify Care Circle members via pool sync.",
    )
    hospital_id = engine.add_entry(hospital_monitor)
    _persist_and_cache(hospital_id, {
        "id": str(hospital_id), "owner_id": "demo",
        "label": "Hospital Health Monitor", "category": "health",
        "entry_type": int(EntryType.HOOK), "visibility": int(Visibility.INTERNAL),
        "salience": 0.6,
        "activation_trigger": {"kind": "event", "event_source": int(EventSource.SYSTEM),
                                "event_type": "capsule.created.health"},
        "deactivation_trigger": None, "dependencies": [],
        "hooks": [{"action": int(HookActionKind.AGENT_TASK), "phase": int(HookPhase.PRE),
                    "prompt": "A health capsule was created. Notify Care Circle members via pool sync.",
                    "timeout_ms": 30000, "max_retries": 0}],
    })

    logger.info(
        "Seeded 6 CME entries (sweep=%s, consolidation=%s)",
        sweep_id, consolidation_id,
    )


def _seed_credential_entries(engine):
    """Seed credential lifecycle management timeline entries.

    Two entries:
      1. Daily sweep — SYSTEM hook, runs podos_credential_sweep_expiry
      2. Weekly rotation reminder — AGENT_TASK, notifies owner of stale credentials
    """
    from src.timeline_bridge import (
        EntryBuilder,
        EntryType,
        HookActionKind,
        HookPhase,
        Visibility,
    )

    def _persist_and_cache(eid, spec):
        try:
            state_val = engine.get_entry_state(eid)
            persist_entry_spec(
                owner_id="demo",
                entry_id=eid,
                state=int(state_val) if state_val is not None else 0,
                spec=spec,
            )
            _cache_spec(eid, spec)
        except Exception:
            logger.exception("Failed to persist credential entry %s", eid)

    # 1. Credential Expiry + Share Cleanup — daily at 06:00 UTC, SYSTEM hook
    sweep = (
        EntryBuilder()
        .set_label("Credential Expiry + Share Cleanup")
        .set_category("system.security")
        .set_salience(0.15)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.TASK)
        .set_trigger_cron("0 6 * * *")
    )
    sweep.add_hook(
        action=HookActionKind.PIPELINE,
        phase=HookPhase.PRE,
        prompt="credential_sweep",
    )
    sweep_id = engine.add_entry(sweep)
    _persist_and_cache(sweep_id, {
        "id": str(sweep_id), "owner_id": "demo",
        "label": "Credential Expiry + Share Cleanup", "category": "system.security",
        "entry_type": int(EntryType.TASK), "visibility": int(Visibility.PRIVATE),
        "salience": 0.15,
        "activation_trigger": {"kind": "time", "cron": "0 6 * * *"},
        "deactivation_trigger": None, "dependencies": [],
        "hooks": [{"action": int(HookActionKind.PIPELINE), "phase": int(HookPhase.PRE),
                    "prompt": "credential_sweep", "timeout_ms": 30000, "max_retries": 0}],
    })

    # 2. Credential Rotation Reminder — weekly on Monday at 09:00 UTC, AGENT_TASK
    rotation = (
        EntryBuilder()
        .set_label("Credential Rotation Reminder")
        .set_category("system.security")
        .set_salience(0.3)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.TASK)
        .set_trigger_cron("0 9 * * 1")
    )
    rotation.add_hook(
        action=HookActionKind.AGENT_TASK,
        phase=HookPhase.PRE,
        prompt=(
            "Review credentials due for rotation based on rotation_interval_days. "
            "List each overdue credential (name, service, last_used_at) and notify "
            "the owner with a summary. Do not expose secret values."
        ),
    )
    rotation_id = engine.add_entry(rotation)
    _persist_and_cache(rotation_id, {
        "id": str(rotation_id), "owner_id": "demo",
        "label": "Credential Rotation Reminder", "category": "system.security",
        "entry_type": int(EntryType.TASK), "visibility": int(Visibility.PRIVATE),
        "salience": 0.3,
        "activation_trigger": {"kind": "time", "cron": "0 9 * * 1"},
        "deactivation_trigger": None, "dependencies": [],
        "hooks": [{"action": int(HookActionKind.AGENT_TASK), "phase": int(HookPhase.PRE),
                    "prompt": (
                        "Review credentials due for rotation based on rotation_interval_days. "
                        "List each overdue credential (name, service, last_used_at) and notify "
                        "the owner with a summary. Do not expose secret values."
                    ), "timeout_ms": 60000, "max_retries": 1}],
    })

    logger.info(
        "Seeded 2 credential lifecycle entries (sweep=%s, rotation=%s)",
        sweep_id, rotation_id,
    )


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
        try:
            engine.detach_persist_db()
        except Exception:
            pass
    _close_persist_db()
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

            # NTP guard: never sleep negative or near-zero (prevents rapid-fire ticks on clock correction)
            sleep_sec = max(0.1, sleep_sec)
            await asyncio.sleep(sleep_sec)

            if engine.is_running:
                with _persist_lock:
                    engine.tick()
                # Process any queued hooks
                await _dispatch_queued_hooks(engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Auto-tick error")
            await asyncio.sleep(1.0)


async def _dispatch_queued_hooks(engine):
    """Process queued hook callbacks — dispatch hooks by type."""
    from src.timeline_bridge import EventSource, HookActionKind

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
        elif action == int(HookActionKind.PIPELINE):
            # PIPELINE hooks: auto-complete + push completion event
            eid = uuid.UUID(entry_id)
            label = engine.get_entry_label(eid) or "unknown"
            logger.info("PIPELINE hook for entry %s (%s) — auto-completing", entry_id, label)
            engine.complete_hook(eid, hook_index, True)
            # Push completion event so downstream entries react
            category = engine.get_entry_category(eid) or "system"
            if category == "system":
                # Infer event name from label
                event_name = _pipeline_completion_event(label)
                if event_name:
                    try:
                        engine.push_event(event_name, EventSource.SYSTEM)
                        logger.info("Pushed completion event: %s", event_name)
                    except Exception:
                        logger.exception("Failed to push pipeline completion event")
        elif action == int(HookActionKind.NOTIFY):
            # Log notification hooks
            logger.info("NOTIFY hook for entry %s (hook %d)", entry_id, hook_index)
            engine.complete_hook(uuid.UUID(entry_id), hook_index, True)
        else:
            # Unknown hook type — auto-complete
            engine.complete_hook(uuid.UUID(entry_id), hook_index, True)


def _pipeline_completion_event(label: str) -> str | None:
    """Map a PIPELINE entry label to its completion event name."""
    label_lower = label.lower()
    if "sweep" in label_lower and "decay" in label_lower:
        return "memory.sweep_completed"
    if "forget" in label_lower:
        return "memory.forget_done"
    if "consolidat" in label_lower:
        return "memory.consolidation_completed"
    return None


async def _dispatch_agent_hook(engine, entry_id_str: str, hook_index: int):
    """Dispatch an AGENT_TASK hook to the AI agent for processing.

    System-category entries are dispatched with is_system_hook=True for
    session isolation (OpenClaw pattern: background hooks don't pollute
    user conversation context).
    """
    eid = uuid.UUID(entry_id_str)
    label = engine.get_entry_label(eid) or "unknown"
    category = engine.get_entry_category(eid) or "general"
    is_system_hook = category.startswith("system")

    logger.info(
        "Dispatching agent hook: entry=%s label=%s system=%s",
        entry_id_str, label, is_system_hook,
    )

    # Build a prompt from the entry's hook data
    prompt = f"Timeline hook fired for entry '{label}' (category: {category}). Process this entry and take appropriate action."

    # Try to dispatch to agent system
    try:
        from src.database import async_session
        from src.gossip import query_agent

        async with async_session() as db:
            from sqlalchemy import select
            from src.models import User
            owner_id = _persist_get_entry_owner_id(eid)
            user = None
            if owner_id:
                result = await db.execute(select(User).where(User.id == owner_id).limit(1))
                user = result.scalar_one_or_none()
            if not user:
                # Fallback: first demo user (legacy demo behavior).
                result = await db.execute(
                    select(User).where(User.is_demo == True).limit(1)  # noqa: E712
                )
                user = result.scalar_one_or_none()
            if not user:
                logger.warning("No user found for agent hook dispatch")
                engine.complete_hook(eid, hook_index, False)
                return

            from src import transit_bridge
            if not transit_bridge.has_key(user.id):
                logger.warning("No vault key for user %s", user.id)
                engine.complete_hook(eid, hook_index, False)
                return

            result = await query_agent(
                db=db,
                from_user_id=user.id,
                to_user_id=user.id,  # self-query
                question=prompt,
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
    entry_type: int = 0
    entry_type_name: str = "EVENT"
    visibility_name: str = "PRIVATE"
    trigger_kind: str | None = None
    trigger_detail: str | None = None
    hook_summary: str | None = None
    dep_count: int = 0


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
#  RESPONSE BUILDER
# ═══════════════════════════════════════════


def _build_entry_response(engine, entry_id) -> EntryResponse:
    """Build an EntryResponse with rich metadata from engine + spec cache."""
    from src.timeline_bridge import EntryState, EntryType, Visibility

    eid = entry_id if isinstance(entry_id, uuid.UUID) else uuid.UUID(str(entry_id))
    state_val = engine.get_entry_state(eid)
    label = engine.get_entry_label(eid) or ""
    category = engine.get_entry_category(eid) or ""
    salience = engine.get_entry_salience(eid) or 0.0
    vis = engine.get_entry_visibility(eid)
    vis_int = vis if vis is not None else 3

    state_name = EntryState(state_val).name if state_val is not None else "unknown"

    # Rich fields from spec cache
    spec = _get_entry_spec(str(eid))
    entry_type = 0
    entry_type_name = "EVENT"
    visibility_name = "PRIVATE"
    trigger_kind = None
    trigger_detail = None
    hook_summary = None
    dep_count = 0

    # Visibility name
    try:
        visibility_name = Visibility(vis_int).name
    except (ValueError, KeyError):
        pass

    if spec:
        # Entry type
        et = spec.get("entry_type", 0)
        if isinstance(et, int):
            entry_type = et
            try:
                entry_type_name = EntryType(et).name
            except (ValueError, KeyError):
                pass

        # Trigger info
        act = spec.get("activation_trigger")
        if isinstance(act, dict):
            kind = act.get("kind", "manual")
            if kind == "time" and act.get("cron"):
                trigger_kind = "cron"
                trigger_detail = act["cron"]
            elif kind == "time" and act.get("at_ms") is not None:
                trigger_kind = "time"
                at_ms = int(act["at_ms"])
                now_ms = int(time.time() * 1000)
                delta_min = (at_ms - now_ms) // 60000
                if delta_min > 0:
                    trigger_detail = f"in {delta_min}m"
                else:
                    trigger_detail = "elapsed"
            elif kind == "event" and act.get("event_type"):
                trigger_kind = "event"
                trigger_detail = act["event_type"]
            elif kind == "absence" and act.get("absence_event_type"):
                trigger_kind = "absence"
                trigger_detail = act["absence_event_type"]

        # Hook summary — first hook's action kind name
        hooks = spec.get("hooks")
        if hooks and isinstance(hooks, list) and len(hooks) > 0:
            from src.timeline_bridge import HookActionKind
            try:
                hook_summary = HookActionKind(int(hooks[0].get("action", 1))).name
            except (ValueError, KeyError):
                hook_summary = "NOTIFY"

        # Dependency count
        deps = spec.get("dependencies")
        if deps and isinstance(deps, list):
            dep_count = len(deps)

    return EntryResponse(
        id=str(eid),
        label=label,
        category=category,
        state=state_val if state_val is not None else 0,
        state_name=state_name,
        salience=salience,
        visibility=vis_int,
        entry_type=entry_type,
        entry_type_name=entry_type_name,
        visibility_name=visibility_name,
        trigger_kind=trigger_kind,
        trigger_detail=trigger_detail,
        hook_summary=hook_summary,
        dep_count=dep_count,
    )


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
    with _persist_lock:
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

    # Persist spec for crash/restart restore.
    try:
        spec = req.model_dump()
        spec["id"] = str(entry_id)
        spec["owner_id"] = auth_user_id
        persist_entry_spec(
            owner_id=auth_user_id,
            entry_id=entry_id,
            state=int(state_val) if state_val is not None else 0,
            spec=spec,
        )
        _cache_spec(entry_id, spec)
        # Best-effort outbox event for INTERNAL visibility (pool sync).
        if int(req.visibility) == int(Visibility.INTERNAL):
            event = {
                "event_id": str(uuid.uuid4()),
                "source_pod": os.getenv("TRUSTMESH_POD_URL", "http://localhost:8000"),
                "source_entry_id": str(entry_id),
                "event_type": "entry_created",
                "entry_data": {
                    "id": str(entry_id),
                    "label": req.label,
                    "category": req.category,
                    "salience": req.salience,
                    "entry_type": req.entry_type,
                    "visibility": req.visibility,
                    "activation_trigger": req.activation_trigger.model_dump() if req.activation_trigger else None,
                    "deactivation_trigger": req.deactivation_trigger.model_dump() if req.deactivation_trigger else None,
                    "state": int(state_val) if state_val is not None else 0,
                },
                "logical_clock": 0,
                "pool_id": None,
                "tick": int(engine.tick_count),
            }
            _persist_append_outbox_event(tick=int(engine.tick_count), event=event)
    except Exception:
        logger.exception("Failed to persist timeline entry spec")

    return _build_entry_response(engine, entry_id)


@router.get("/entries")
async def list_entries(
    auth_user_id: str = Depends(get_current_user_id),
) -> list[EntryResponse]:
    """List all entries in the timeline engine."""
    engine = _get_engine()
    ids = engine.get_all_entry_ids()
    entries = []
    for eid in ids:
        state_val = engine.get_entry_state(eid)
        if state_val is None:
            continue
        entries.append(_build_entry_response(engine, eid))
    return entries


@router.get("/entries/{entry_id}")
async def get_entry(
    entry_id: str,
    auth_user_id: str = Depends(get_current_user_id),
) -> EntryResponse:
    """Get a specific entry by ID."""
    engine = _get_engine()
    eid = uuid.UUID(entry_id)
    state_val = engine.get_entry_state(eid)
    if state_val is None:
        raise HTTPException(404, "Entry not found")

    return _build_entry_response(engine, eid)


@router.post("/entries/{entry_id}/transition")
async def transition_entry(
    entry_id: str,
    req: TransitionRequest,
    auth_user_id: str = Depends(get_current_user_id),
) -> EntryResponse:
    """Manually transition an entry to a new state."""
    from src.timeline_bridge import EntryState, Visibility

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
    vis = engine.get_entry_visibility(eid)

    # Best-effort persistence mirror + outbox event (for INTERNAL entries).
    try:
        if state_after is not None:
            persist_update_state(entry_id=eid, state=int(state_after))
        if vis is not None and int(vis) == int(Visibility.INTERNAL):
            event = {
                "event_id": str(uuid.uuid4()),
                "source_pod": os.getenv("TRUSTMESH_POD_URL", "http://localhost:8000"),
                "source_entry_id": str(eid),
                "event_type": "entry_state_changed",
                "entry_data": {"id": str(eid), "state": int(state_after) if state_after is not None else 0},
                "logical_clock": 0,
                "pool_id": None,
                "tick": int(engine.tick_count),
            }
            _persist_append_outbox_event(tick=int(engine.tick_count), event=event)
    except Exception:
        logger.exception("Failed to persist timeline transition")

    return _build_entry_response(engine, eid)


@router.post("/sync")
async def timeline_sync_push(
    req: dict,
    _auth: str = Depends(require_auth_or_pool_secret),
) -> dict:
    """Receive timeline sync events from peers (minimal v1)."""
    # Store in inbox (dedupe). Event schema is intentionally flexible for now.
    try:
        event_id = req.get("event_id")
        if not event_id:
            stable = f"{req.get('source_pod','')}|{req.get('source_entry_id','')}|{req.get('event_type','')}|{req.get('logical_clock',0)}"
            event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, stable))
        _persist_mark_inbox_event(event_id=str(event_id), event=req)
    except Exception:
        logger.exception("Failed to persist timeline inbox event")

    # Best-effort apply for entry_created/state_changed.
    try:
        from src.timeline_bridge import EntryBuilder, EntryState, EntryType, EventSource, Visibility

        engine = _get_engine()
        et = str(req.get("event_type", ""))
        source_entry_id = req.get("source_entry_id") or req.get("entry_id") or ""
        if not source_entry_id:
            return {"status": "ok"}
        eid = uuid.UUID(source_entry_id)

        if et in ("entry_created", "entry_updated"):
            if engine.get_entry_state(eid) is None:
                data = req.get("entry_data") or {}
                builder = EntryBuilder().set_id(eid)
                builder.set_label(str(data.get("label", "remote entry")))
                builder.set_category(str(data.get("category", "general")))
                builder.set_entry_type(EntryType(int(data.get("entry_type", EntryType.EVENT))))
                builder.set_visibility(Visibility(int(data.get("visibility", Visibility.INTERNAL))))
                builder.set_salience(float(data.get("salience", 0.5)))
                # Minimal trigger restore (no hooks for remote shadows)
                act = data.get("activation_trigger") or {}
                if isinstance(act, dict):
                    kind = act.get("kind")
                    if kind == "time" and act.get("at_ms") is not None:
                        builder.set_trigger_time(int(act["at_ms"]))
                    elif kind == "time" and act.get("cron") is not None:
                        builder.set_trigger_cron(str(act["cron"]))
                    elif kind == "event" and act.get("event_type") is not None:
                        builder.set_trigger_event(
                            EventSource(int(act.get("event_source", 0))),
                            str(act["event_type"]),
                        )
                engine.add_entry(builder)
                engine.push_event("timeline.shadow_entry_added", EventSource.FEDERATION)
        elif et == "entry_state_changed":
            data = req.get("entry_data") or {}
            target = data.get("state") or data.get("new_state")
            if target is not None:
                try:
                    engine.transition_entry(eid, EntryState(int(target)))
                except Exception:
                    # Special case: attempt to reach COMPLETED via valid steps.
                    try:
                        cur = engine.get_entry_state(eid)
                        if cur is not None and int(target) == int(EntryState.COMPLETED):
                            if cur == EntryState.ACTIVE:
                                engine.transition_entry(eid, EntryState.DEACTIVATING)
                            engine.transition_entry(eid, EntryState.COMPLETED)
                    except Exception:
                        pass
    except Exception:
        logger.exception("Failed to apply incoming timeline sync event")

    return {"status": "ok"}


@router.get("/sync/events")
async def timeline_sync_pull(
    since_tick: int = 0,
    _auth: str = Depends(require_auth_or_pool_secret),
) -> dict:
    """Pull outbox events since a tick (for catch-up)."""
    events = _persist_load_json_array("podos_timeline_outbox_pull", int(since_tick))
    return {"events": events, "since_tick": since_tick}


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
