"""
PodOS Timeline Bridge — Python ctypes wrapper for libpodos.

Loads the Zig-compiled shared library and exposes a Pythonic API
for the Timeline Engine. This is the bridge between the FastAPI
backend and the Zig kernel.

Usage:
    from src.timeline_bridge import TimelineEngine, EntryBuilder

    engine = TimelineEngine()
    engine.start()

    entry = EntryBuilder()
    entry.set_label("Morning medication")
    entry.set_category("health")
    entry.set_trigger_time(time.time() * 1000 + 60000)  # 1 min from now
    entry.set_salience(0.9)
    engine.add_entry(entry)

    engine.tick()
    print(engine.state)  # EngineState(active_count=1, ...)
"""

from __future__ import annotations

import ctypes
import platform
import uuid
from ctypes import (
    CFUNCTYPE,
    POINTER,
    c_char,
    c_char_p,
    c_float,
    c_int8,
    c_int32,
    c_int64,
    c_uint8,
    c_uint16,
    c_uint32,
    c_uint64,
    c_void_p,
)
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════
#  ENUMS (mirror Zig types)
# ═══════════════════════════════════════════

class Visibility(IntEnum):
    OPEN = 1
    INTERNAL = 2
    PRIVATE = 3


class EntryState(IntEnum):
    DORMANT = 0
    PENDING = 1
    ACTIVATING = 2
    ACTIVE = 3
    DEACTIVATING = 4
    COMPLETED = 5
    FAILED = 6
    ARCHIVED = 7
    DELETED = 8


class TriggerKind(IntEnum):
    TIME = 0
    EVENT = 1
    CONDITION = 2
    DEPENDENCY = 3
    ABSENCE = 4
    MANUAL = 5


class EntryType(IntEnum):
    EVENT = 0
    IDEA = 1
    DATA = 2
    REMINDER = 3
    HOOK = 4
    MILESTONE = 5
    TASK = 6
    SIGNAL = 7
    MOUNT = 8
    COMPUTED = 9


class EventSource(IntEnum):
    SYSTEM = 0
    USER = 1
    AGENT = 2
    INTEGRATION = 3
    FEDERATION = 4
    TIMELINE = 5
    PUBLIC_STREAM = 6


class HookActionKind(IntEnum):
    AGENT_TASK = 0
    NOTIFY = 1
    MUTATE_ENTRY = 2
    CREATE_ENTRY = 3
    VAULT_OP = 4
    INTEGRATION = 5
    SYNC = 6
    PIPELINE = 7


class HookPhase(IntEnum):
    PRE = 0
    POST = 1


class SignalSeverity(IntEnum):
    INFO = 0
    WARNING = 1
    ATTENTION = 2
    CRITICAL = 3


# ═══════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════

@dataclass
class Signal:
    severity: SignalSeverity
    message: str
    related_entry_id: uuid.UUID


@dataclass
class EngineState:
    active_count: int = 0
    pending_count: int = 0
    dormant_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    tick_count: int = 0
    signal_count: int = 0
    signals: list[Signal] = field(default_factory=list)
    active_ids: list[uuid.UUID] = field(default_factory=list)


# ═══════════════════════════════════════════
#  LIBRARY LOADING
# ═══════════════════════════════════════════

def _find_library() -> Path:
    """Find libpodos shared library relative to this file."""
    kernel_dir = Path(__file__).parent.parent / "kernel"
    system = platform.system()
    if system == "Darwin":
        lib_name = "libpodos.dylib"
    elif system == "Linux":
        lib_name = "libpodos.so"
    elif system == "Windows":
        lib_name = "podos.dll"
    else:
        lib_name = "libpodos.so"

    lib_path = kernel_dir / "zig-out" / "lib" / lib_name
    if not lib_path.exists():
        raise FileNotFoundError(
            f"libpodos not found at {lib_path}. "
            f"Build it first: cd {kernel_dir} && zig build"
        )
    return lib_path


def _load_library() -> ctypes.CDLL:
    """Load and configure the libpodos shared library."""
    lib_path = _find_library()
    lib = ctypes.CDLL(str(lib_path))
    _configure_signatures(lib)
    return lib


# Callback types for Python → Zig hooks
HookCallbackType = CFUNCTYPE(
    None,           # return void
    c_void_p,       # entry_id: *const [16]u8
    c_uint8,        # hook_index
    c_uint8,        # action_kind
    c_void_p,       # entry_json (unused for now)
    c_uint32,       # entry_json_len
)

StateCallbackType = CFUNCTYPE(
    None,           # return void
    c_void_p,       # state_json
    c_uint32,       # state_json_len
)


def _configure_signatures(lib: ctypes.CDLL) -> None:
    """Set argtypes and restype for all exported functions."""

    # Version
    lib.podos_version.argtypes = []
    lib.podos_version.restype = c_uint32

    # Engine lifecycle
    lib.podos_engine_create.argtypes = [c_uint32, c_uint32, c_uint32]
    lib.podos_engine_create.restype = c_void_p

    lib.podos_engine_destroy.argtypes = [c_void_p]
    lib.podos_engine_destroy.restype = None

    lib.podos_engine_start.argtypes = [c_void_p]
    lib.podos_engine_start.restype = None

    lib.podos_engine_stop.argtypes = [c_void_p]
    lib.podos_engine_stop.restype = None

    lib.podos_engine_tick.argtypes = [c_void_p]
    lib.podos_engine_tick.restype = c_int32

    lib.podos_engine_is_running.argtypes = [c_void_p]
    lib.podos_engine_is_running.restype = c_int32

    # Entry builder
    lib.podos_entry_create.argtypes = []
    lib.podos_entry_create.restype = c_void_p

    lib.podos_entry_free.argtypes = [c_void_p]
    lib.podos_entry_free.restype = None

    lib.podos_entry_set_id.argtypes = [c_void_p, c_char_p]
    lib.podos_entry_set_id.restype = None

    lib.podos_entry_set_label.argtypes = [c_void_p, c_char_p, c_uint8]
    lib.podos_entry_set_label.restype = None

    lib.podos_entry_set_category.argtypes = [c_void_p, c_char_p, c_uint8]
    lib.podos_entry_set_category.restype = None

    lib.podos_entry_set_visibility.argtypes = [c_void_p, c_uint8]
    lib.podos_entry_set_visibility.restype = None

    lib.podos_entry_set_salience.argtypes = [c_void_p, c_float]
    lib.podos_entry_set_salience.restype = None

    lib.podos_entry_set_window.argtypes = [c_void_p, c_int64, c_int64]
    lib.podos_entry_set_window.restype = None

    lib.podos_entry_set_entry_type.argtypes = [c_void_p, c_uint8]
    lib.podos_entry_set_entry_type.restype = None

    lib.podos_entry_set_trigger_time.argtypes = [c_void_p, c_int64]
    lib.podos_entry_set_trigger_time.restype = None

    lib.podos_entry_set_trigger_cron.argtypes = [c_void_p, c_char_p, c_uint8]
    lib.podos_entry_set_trigger_cron.restype = None

    lib.podos_entry_set_trigger_event.argtypes = [c_void_p, c_uint8, c_char_p, c_uint8]
    lib.podos_entry_set_trigger_event.restype = None

    lib.podos_entry_set_trigger_absence.argtypes = [c_void_p, c_char_p, c_uint8, c_int64]
    lib.podos_entry_set_trigger_absence.restype = None

    lib.podos_entry_set_deactivation_time.argtypes = [c_void_p, c_int64]
    lib.podos_entry_set_deactivation_time.restype = None

    lib.podos_entry_add_dep.argtypes = [c_void_p, c_char_p, c_uint8, c_uint8]
    lib.podos_entry_add_dep.restype = c_int32

    lib.podos_entry_add_hook.argtypes = [
        c_void_p, c_uint8, c_uint8, c_char_p, c_uint16, c_uint32, c_uint8,
    ]
    lib.podos_entry_add_hook.restype = c_int32

    # Engine entry management
    lib.podos_engine_add_entry.argtypes = [c_void_p, c_void_p]
    lib.podos_engine_add_entry.restype = c_int32

    lib.podos_engine_get_entry_state.argtypes = [c_void_p, c_char_p]
    lib.podos_engine_get_entry_state.restype = c_int8

    lib.podos_engine_entry_count.argtypes = [c_void_p]
    lib.podos_engine_entry_count.restype = c_uint32

    lib.podos_engine_transition_entry.argtypes = [c_void_p, c_char_p, c_uint8]
    lib.podos_engine_transition_entry.restype = c_int32

    lib.podos_engine_get_entry_label.argtypes = [c_void_p, c_char_p, c_char_p, c_uint32]
    lib.podos_engine_get_entry_label.restype = c_int32

    lib.podos_engine_get_entry_category.argtypes = [c_void_p, c_char_p, c_char_p, c_uint32]
    lib.podos_engine_get_entry_category.restype = c_int32

    lib.podos_engine_get_entry_salience.argtypes = [c_void_p, c_char_p]
    lib.podos_engine_get_entry_salience.restype = c_float

    lib.podos_engine_get_entry_visibility.argtypes = [c_void_p, c_char_p]
    lib.podos_engine_get_entry_visibility.restype = c_int8

    lib.podos_engine_get_all_ids.argtypes = [c_void_p, c_char_p, c_uint32]
    lib.podos_engine_get_all_ids.restype = c_uint32

    # Event management
    lib.podos_event_push.argtypes = [c_void_p, c_uint8, c_char_p, c_uint8, c_int64]
    lib.podos_event_push.restype = c_int32

    # Central state queries
    lib.podos_state_active_count.argtypes = [c_void_p]
    lib.podos_state_active_count.restype = c_uint32

    lib.podos_state_pending_count.argtypes = [c_void_p]
    lib.podos_state_pending_count.restype = c_uint32

    lib.podos_state_dormant_count.argtypes = [c_void_p]
    lib.podos_state_dormant_count.restype = c_uint32

    lib.podos_state_failed_count.argtypes = [c_void_p]
    lib.podos_state_failed_count.restype = c_uint32

    lib.podos_state_total_count.argtypes = [c_void_p]
    lib.podos_state_total_count.restype = c_uint32

    lib.podos_state_tick_count.argtypes = [c_void_p]
    lib.podos_state_tick_count.restype = c_uint64

    lib.podos_state_signal_count.argtypes = [c_void_p]
    lib.podos_state_signal_count.restype = c_uint16

    lib.podos_state_get_signal.argtypes = [
        c_void_p, c_uint16, POINTER(c_uint8), c_char_p, c_uint32, c_char_p,
    ]
    lib.podos_state_get_signal.restype = c_int32

    lib.podos_state_get_active_id.argtypes = [c_void_p, c_uint32, c_char_p]
    lib.podos_state_get_active_id.restype = c_int32

    # Hook management
    lib.podos_hook_complete.argtypes = [c_void_p, c_char_p, c_uint8, c_uint8]
    lib.podos_hook_complete.restype = c_int32

    lib.podos_register_hook_callback.argtypes = [c_void_p, HookCallbackType]
    lib.podos_register_hook_callback.restype = None

    lib.podos_register_state_callback.argtypes = [c_void_p, StateCallbackType]
    lib.podos_register_state_callback.restype = None

    # Utility
    lib.podos_now_ms.argtypes = []
    lib.podos_now_ms.restype = c_int64

    lib.podos_engine_next_wake.argtypes = [c_void_p]
    lib.podos_engine_next_wake.restype = c_int64

    lib.podos_engine_tick_count.argtypes = [c_void_p]
    lib.podos_engine_tick_count.restype = c_uint64

    # ── Database / FTS5 ──

    lib.podos_db_open.argtypes = [c_char_p, c_uint32]
    lib.podos_db_open.restype = c_void_p

    lib.podos_db_close.argtypes = [c_void_p]
    lib.podos_db_close.restype = None

    lib.podos_fts_upsert.argtypes = [
        c_void_p,  # handle
        c_char_p, c_uint32,  # capsule_id, id_len
        c_char_p, c_uint32,  # title, title_len
        c_char_p, c_uint32,  # content, content_len
        c_char_p, c_uint32,  # category, category_len
    ]
    lib.podos_fts_upsert.restype = c_int32

    lib.podos_fts_delete.argtypes = [c_void_p, c_char_p, c_uint32]
    lib.podos_fts_delete.restype = c_int32

    lib.podos_fts_search.argtypes = [
        c_void_p,              # handle
        c_char_p, c_uint32,    # query, query_len
        c_char_p, c_uint32,    # accessible_ids_json, ids_len
        c_uint32,              # top_k
        c_char_p, c_uint32,    # out_buf, out_capacity
        POINTER(c_uint32),     # out_len
    ]
    lib.podos_fts_search.restype = c_int32

    lib.podos_fts_reset.argtypes = [c_void_p]
    lib.podos_fts_reset.restype = c_int32


# ═══════════════════════════════════════════
#  HELPER: UUID ↔ 16-byte C buffer
# ═══════════════════════════════════════════

def _uuid_to_bytes(u: uuid.UUID) -> bytes:
    """Convert Python UUID to 16-byte buffer for Zig."""
    return u.bytes


def _bytes_to_uuid(b: bytes) -> uuid.UUID:
    """Convert 16-byte buffer from Zig to Python UUID."""
    return uuid.UUID(bytes=b)


# ═══════════════════════════════════════════
#  ENTRY BUILDER
# ═══════════════════════════════════════════

class EntryBuilder:
    """
    Fluent builder for timeline entries.

    Usage:
        entry = EntryBuilder()
        entry.set_label("Take medication").set_category("health").set_salience(0.9)
        engine.add_entry(entry)
    """

    def __init__(self, *, _lib: Optional[ctypes.CDLL] = None):
        self._lib = _lib or _get_lib()
        self._ptr = self._lib.podos_entry_create()
        if not self._ptr:
            raise MemoryError("Failed to allocate entry")
        self._id: Optional[uuid.UUID] = None
        self._consumed = False

    def set_id(self, entry_id: uuid.UUID) -> EntryBuilder:
        self._id = entry_id
        self._lib.podos_entry_set_id(self._ptr, _uuid_to_bytes(entry_id))
        return self

    def set_label(self, label: str) -> EntryBuilder:
        b = label.encode("utf-8")[:128]
        self._lib.podos_entry_set_label(self._ptr, b, len(b))
        return self

    def set_category(self, category: str) -> EntryBuilder:
        b = category.encode("utf-8")[:32]
        self._lib.podos_entry_set_category(self._ptr, b, len(b))
        return self

    def set_visibility(self, vis: Visibility) -> EntryBuilder:
        self._lib.podos_entry_set_visibility(self._ptr, int(vis))
        return self

    def set_salience(self, salience: float) -> EntryBuilder:
        self._lib.podos_entry_set_salience(self._ptr, salience)
        return self

    def set_window(self, start_ms: int, end_ms: int) -> EntryBuilder:
        self._lib.podos_entry_set_window(self._ptr, start_ms, end_ms)
        return self

    def set_entry_type(self, entry_type: EntryType) -> EntryBuilder:
        self._lib.podos_entry_set_entry_type(self._ptr, int(entry_type))
        return self

    def set_trigger_time(self, at_ms: int) -> EntryBuilder:
        self._lib.podos_entry_set_trigger_time(self._ptr, at_ms)
        return self

    def set_trigger_cron(self, cron_expr: str) -> EntryBuilder:
        b = cron_expr.encode("utf-8")[:64]
        self._lib.podos_entry_set_trigger_cron(self._ptr, b, len(b))
        return self

    def set_trigger_event(
        self, source: EventSource, event_type: str
    ) -> EntryBuilder:
        b = event_type.encode("utf-8")[:64]
        self._lib.podos_entry_set_trigger_event(
            self._ptr, int(source), b, len(b)
        )
        return self

    def set_trigger_absence(
        self, event_type: str, deadline_ms: int
    ) -> EntryBuilder:
        b = event_type.encode("utf-8")[:64]
        self._lib.podos_entry_set_trigger_absence(
            self._ptr, b, len(b), deadline_ms
        )
        return self

    def set_deactivation_time(self, at_ms: int) -> EntryBuilder:
        self._lib.podos_entry_set_deactivation_time(self._ptr, at_ms)
        return self

    def add_dependency(
        self,
        dep_id: uuid.UUID,
        required_state: EntryState = EntryState.ACTIVE,
        is_hard: bool = True,
    ) -> EntryBuilder:
        rc = self._lib.podos_entry_add_dep(
            self._ptr,
            _uuid_to_bytes(dep_id),
            int(required_state),
            1 if is_hard else 0,
        )
        if rc < 0:
            raise RuntimeError(f"Failed to add dependency: {rc}")
        return self

    def add_hook(
        self,
        action: HookActionKind,
        phase: HookPhase = HookPhase.PRE,
        prompt: str = "",
        timeout_ms: int = 30000,
        max_retries: int = 0,
    ) -> EntryBuilder:
        b = prompt.encode("utf-8")[:512] if prompt else None
        rc = self._lib.podos_entry_add_hook(
            self._ptr,
            int(action),
            int(phase),
            b,
            len(b) if b else 0,
            timeout_ms,
            max_retries,
        )
        if rc < 0:
            raise RuntimeError(f"Failed to add hook: {rc}")
        return self

    @property
    def id(self) -> uuid.UUID:
        if self._id is None:
            self._id = uuid.uuid4()
            self._lib.podos_entry_set_id(self._ptr, _uuid_to_bytes(self._id))
        return self._id

    def _consume(self) -> c_void_p:
        """Return the pointer and mark as consumed (ownership transferred)."""
        if self._consumed:
            raise RuntimeError("Entry already consumed (added to engine)")
        self._consumed = True
        # Ensure ID is set
        _ = self.id
        return self._ptr

    def __del__(self):
        if not self._consumed and hasattr(self, "_ptr") and self._ptr:
            try:
                self._lib.podos_entry_free(self._ptr)
            except Exception:
                pass


# ═══════════════════════════════════════════
#  TIMELINE ENGINE
# ═══════════════════════════════════════════

class TimelineEngine:
    """
    Python wrapper for the PodOS Timeline Engine.

    The engine runs a tick-tock cycle:
      TICK: evaluate triggers, deps, conflicts (frozen state)
      TOCK: apply transitions, fire hooks, recompute state (atomic)

    Usage:
        engine = TimelineEngine(heartbeat_ms=1000)
        engine.start()
        engine.add_entry(EntryBuilder().set_label("test").set_salience(0.8))
        engine.tick()
        print(engine.state)
        engine.stop()
    """

    def __init__(
        self,
        heartbeat_ms: int = 5000,
        max_entries: int = 10000,
        max_events_per_tick: int = 256,
    ):
        self._lib = _get_lib()
        self._engine = self._lib.podos_engine_create(
            heartbeat_ms, max_entries, max_events_per_tick
        )
        if not self._engine:
            raise MemoryError("Failed to create engine")
        self._hook_callback_ref = None  # prevent GC of callback
        self._state_callback_ref = None

    def __del__(self):
        self.destroy()

    def destroy(self) -> None:
        if hasattr(self, "_engine") and self._engine:
            self._lib.podos_engine_destroy(self._engine)
            self._engine = None

    def start(self) -> None:
        self._lib.podos_engine_start(self._engine)

    def stop(self) -> None:
        self._lib.podos_engine_stop(self._engine)

    @property
    def is_running(self) -> bool:
        return self._lib.podos_engine_is_running(self._engine) == 1

    def tick(self) -> None:
        rc = self._lib.podos_engine_tick(self._engine)
        if rc != 0:
            raise RuntimeError(f"Engine tick failed: {rc}")

    # ── Entry management ──

    def add_entry(self, builder: EntryBuilder) -> uuid.UUID:
        """Add an entry to the engine. Returns the entry UUID."""
        entry_id = builder.id  # ensure ID is assigned
        ptr = builder._consume()
        rc = self._lib.podos_engine_add_entry(self._engine, ptr)
        if rc != 0:
            raise RuntimeError(f"Failed to add entry: {rc}")
        return entry_id

    def get_entry_state(self, entry_id: uuid.UUID) -> Optional[EntryState]:
        rc = self._lib.podos_engine_get_entry_state(
            self._engine, _uuid_to_bytes(entry_id)
        )
        if rc < 0:
            return None
        return EntryState(rc)

    def get_entry_label(self, entry_id: uuid.UUID) -> Optional[str]:
        buf = ctypes.create_string_buffer(128)
        rc = self._lib.podos_engine_get_entry_label(
            self._engine, _uuid_to_bytes(entry_id), buf, 128
        )
        if rc < 0:
            return None
        return buf.raw[:rc].decode("utf-8")

    def get_entry_category(self, entry_id: uuid.UUID) -> Optional[str]:
        buf = ctypes.create_string_buffer(32)
        rc = self._lib.podos_engine_get_entry_category(
            self._engine, _uuid_to_bytes(entry_id), buf, 32
        )
        if rc < 0:
            return None
        return buf.raw[:rc].decode("utf-8")

    def get_entry_salience(self, entry_id: uuid.UUID) -> Optional[float]:
        val = self._lib.podos_engine_get_entry_salience(
            self._engine, _uuid_to_bytes(entry_id)
        )
        if val < 0:
            return None
        return val

    def get_entry_visibility(self, entry_id: uuid.UUID) -> Optional[Visibility]:
        rc = self._lib.podos_engine_get_entry_visibility(
            self._engine, _uuid_to_bytes(entry_id)
        )
        if rc < 0:
            return None
        return Visibility(rc)

    def transition_entry(
        self, entry_id: uuid.UUID, new_state: EntryState
    ) -> None:
        rc = self._lib.podos_engine_transition_entry(
            self._engine, _uuid_to_bytes(entry_id), int(new_state)
        )
        if rc != 0:
            raise RuntimeError(f"Transition failed: {rc}")

    @property
    def entry_count(self) -> int:
        return self._lib.podos_engine_entry_count(self._engine)

    def get_all_entry_ids(self) -> list[uuid.UUID]:
        count = self.entry_count
        if count == 0:
            return []
        buf = ctypes.create_string_buffer(count * 16)
        actual = self._lib.podos_engine_get_all_ids(self._engine, buf, count)
        ids = []
        for i in range(actual):
            raw = buf.raw[i * 16 : (i + 1) * 16]
            ids.append(_bytes_to_uuid(raw))
        return ids

    # ── Event management ──

    def push_event(
        self,
        event_type: str,
        source: EventSource = EventSource.SYSTEM,
        timestamp_ms: int = 0,
    ) -> None:
        b = event_type.encode("utf-8")[:64]
        rc = self._lib.podos_event_push(
            self._engine, int(source), b, len(b), timestamp_ms
        )
        if rc != 0:
            raise RuntimeError(f"Push event failed: {rc}")

    # ── State queries ──

    @property
    def state(self) -> EngineState:
        """Get the current central state snapshot."""
        s = EngineState(
            active_count=self._lib.podos_state_active_count(self._engine),
            pending_count=self._lib.podos_state_pending_count(self._engine),
            dormant_count=self._lib.podos_state_dormant_count(self._engine),
            failed_count=self._lib.podos_state_failed_count(self._engine),
            total_count=self._lib.podos_state_total_count(self._engine),
            tick_count=self._lib.podos_state_tick_count(self._engine),
            signal_count=self._lib.podos_state_signal_count(self._engine),
        )

        # Read signals
        for i in range(s.signal_count):
            severity = c_uint8(0)
            msg_buf = ctypes.create_string_buffer(256)
            entry_id_buf = ctypes.create_string_buffer(16)
            msg_len = self._lib.podos_state_get_signal(
                self._engine, i, ctypes.byref(severity), msg_buf, 256, entry_id_buf
            )
            if msg_len >= 0:
                s.signals.append(Signal(
                    severity=SignalSeverity(severity.value),
                    message=msg_buf.raw[:msg_len].decode("utf-8"),
                    related_entry_id=_bytes_to_uuid(entry_id_buf.raw[:16]),
                ))

        # Read active IDs
        for i in range(s.active_count):
            id_buf = ctypes.create_string_buffer(16)
            rc = self._lib.podos_state_get_active_id(self._engine, i, id_buf)
            if rc == 0:
                s.active_ids.append(_bytes_to_uuid(id_buf.raw[:16]))

        return s

    @property
    def tick_count(self) -> int:
        return self._lib.podos_engine_tick_count(self._engine)

    @property
    def next_wake_at(self) -> int:
        return self._lib.podos_engine_next_wake(self._engine)

    # ── Hook management ──

    def complete_hook(
        self, entry_id: uuid.UUID, hook_index: int, success: bool
    ) -> None:
        rc = self._lib.podos_hook_complete(
            self._engine,
            _uuid_to_bytes(entry_id),
            hook_index,
            1 if success else 0,
        )
        if rc != 0:
            raise RuntimeError(f"Hook complete failed: {rc}")

    def register_hook_callback(self, callback) -> None:
        """
        Register a callback for hook dispatches.

        callback signature: (entry_id: bytes, hook_index: int, action_kind: int,
                             data: bytes, data_len: int) -> None
        """
        @HookCallbackType
        def wrapper(entry_id_ptr, hook_index, action_kind, data_ptr, data_len):
            entry_id = bytes(ctypes.cast(entry_id_ptr, POINTER(c_char * 16)).contents)
            callback(entry_id, hook_index, action_kind, b"", 0)

        self._hook_callback_ref = wrapper  # prevent GC
        self._lib.podos_register_hook_callback(self._engine, wrapper)

    # ── Utility ──

    @staticmethod
    def now_ms() -> int:
        return _get_lib().podos_now_ms()

    def version(self) -> int:
        return self._lib.podos_version()


# ═══════════════════════════════════════════
#  MODULE-LEVEL SINGLETON
# ═══════════════════════════════════════════

_lib_instance: Optional[ctypes.CDLL] = None


def _get_lib() -> ctypes.CDLL:
    global _lib_instance
    if _lib_instance is None:
        _lib_instance = _load_library()
    return _lib_instance


def is_available() -> bool:
    """Check if the Zig kernel library is available."""
    try:
        _get_lib()
        return True
    except (FileNotFoundError, OSError):
        return False
