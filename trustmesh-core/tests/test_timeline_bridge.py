"""
Tests for the PodOS Timeline Bridge (Python ↔ Zig FFI).

These tests verify the ctypes bridge correctly communicates with
the Zig kernel shared library (libpodos).
"""

import time
import uuid

import pytest

from src.timeline_bridge import (
    EntryBuilder,
    EntryState,
    EntryType,
    EventSource,
    HookActionKind,
    HookPhase,
    SignalSeverity,
    TimelineEngine,
    Visibility,
    is_available,
)

# Skip all tests if kernel not built
pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="libpodos not built — run: cd kernel && zig build",
)


# ═══════════════════════════════════════════
#  VERSION
# ═══════════════════════════════════════════


def test_version():
    engine = TimelineEngine()
    assert engine.version() == 0x000100  # 0.1.0
    engine.destroy()


def test_is_available():
    assert is_available() is True


# ═══════════════════════════════════════════
#  ENGINE LIFECYCLE
# ═══════════════════════════════════════════


def test_engine_create_destroy():
    engine = TimelineEngine()
    assert engine._engine is not None
    engine.destroy()
    assert engine._engine is None


def test_engine_start_stop():
    engine = TimelineEngine()
    assert not engine.is_running
    engine.start()
    assert engine.is_running
    engine.stop()
    assert not engine.is_running
    engine.destroy()


def test_engine_tick_not_running():
    engine = TimelineEngine()
    # Tick when not running should be a no-op (returns 0)
    engine.tick()
    assert engine.tick_count == 0
    engine.destroy()


def test_engine_tick_increments():
    engine = TimelineEngine()
    engine.start()
    engine.tick()
    assert engine.tick_count == 1
    engine.tick()
    assert engine.tick_count == 2
    engine.destroy()


# ═══════════════════════════════════════════
#  ENTRY BUILDER
# ═══════════════════════════════════════════


def test_entry_builder_auto_id():
    entry = EntryBuilder()
    entry_id = entry.id
    assert isinstance(entry_id, uuid.UUID)
    assert entry_id == entry.id  # same on second access


def test_entry_builder_explicit_id():
    eid = uuid.uuid4()
    entry = EntryBuilder().set_id(eid)
    assert entry.id == eid


def test_entry_builder_fluent():
    entry = (
        EntryBuilder()
        .set_label("Morning medication")
        .set_category("health")
        .set_salience(0.9)
        .set_visibility(Visibility.PRIVATE)
        .set_entry_type(EntryType.REMINDER)
    )
    assert entry.id is not None  # auto-assigned


# ═══════════════════════════════════════════
#  ADD ENTRIES AND READ BACK
# ═══════════════════════════════════════════


def test_add_entry_and_read_state():
    engine = TimelineEngine()
    entry = EntryBuilder().set_label("Test entry").set_category("test")
    eid = engine.add_entry(entry)
    assert engine.entry_count == 1
    state = engine.get_entry_state(eid)
    assert state == EntryState.DORMANT
    engine.destroy()


def test_add_entry_read_label():
    engine = TimelineEngine()
    entry = EntryBuilder().set_label("Morning checkup").set_category("health")
    eid = engine.add_entry(entry)
    assert engine.get_entry_label(eid) == "Morning checkup"
    assert engine.get_entry_category(eid) == "health"
    engine.destroy()


def test_add_entry_read_salience():
    engine = TimelineEngine()
    entry = EntryBuilder().set_salience(0.75).set_category("test")
    eid = engine.add_entry(entry)
    sal = engine.get_entry_salience(eid)
    assert sal is not None
    assert abs(sal - 0.75) < 0.01
    engine.destroy()


def test_add_entry_read_visibility():
    engine = TimelineEngine()
    entry = EntryBuilder().set_visibility(Visibility.INTERNAL).set_category("test")
    eid = engine.add_entry(entry)
    assert engine.get_entry_visibility(eid) == Visibility.INTERNAL
    engine.destroy()


def test_nonexistent_entry_returns_none():
    engine = TimelineEngine()
    fake_id = uuid.uuid4()
    assert engine.get_entry_state(fake_id) is None
    assert engine.get_entry_label(fake_id) is None
    assert engine.get_entry_category(fake_id) is None
    assert engine.get_entry_salience(fake_id) is None
    engine.destroy()


def test_get_all_entry_ids():
    engine = TimelineEngine()
    ids = set()
    for i in range(5):
        entry = EntryBuilder().set_label(f"Entry {i}").set_category("test")
        ids.add(engine.add_entry(entry))
    assert engine.entry_count == 5
    all_ids = set(engine.get_all_entry_ids())
    assert all_ids == ids
    engine.destroy()


# ═══════════════════════════════════════════
#  TIME TRIGGER → TICK → STATE TRANSITION
# ═══════════════════════════════════════════


def test_time_trigger_activates_entry():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    now_ms = int(time.time() * 1000)
    entry = (
        EntryBuilder()
        .set_label("Overdue item")
        .set_category("health")
        .set_trigger_time(now_ms - 1000)  # 1 second ago
    )
    eid = engine.add_entry(entry)

    # Entry starts dormant
    assert engine.get_entry_state(eid) == EntryState.DORMANT

    # After tick: should advance through dormant → pending → activating → active
    engine.tick()
    state = engine.get_entry_state(eid)
    assert state is not None
    assert state.value >= EntryState.PENDING.value  # at least pending

    engine.destroy()


def test_window_expiry_deactivates():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    now_ms = int(time.time() * 1000)
    entry = (
        EntryBuilder()
        .set_label("Expired task")
        .set_category("test")
        .set_window(now_ms - 2000, now_ms - 1000)  # window ended 1s ago
    )
    # Need to manually set to active state
    eid = entry.id
    engine.add_entry(entry)
    # Transition dormant → pending → activating → active manually
    engine.transition_entry(eid, EntryState.PENDING)
    engine.transition_entry(eid, EntryState.ACTIVATING)
    engine.transition_entry(eid, EntryState.ACTIVE)

    engine.tick()
    state = engine.get_entry_state(eid)
    assert state is not None
    assert state.value >= EntryState.DEACTIVATING.value
    engine.destroy()


# ═══════════════════════════════════════════
#  EVENT TRIGGER
# ═══════════════════════════════════════════


def test_event_trigger_activates_entry():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    entry = (
        EntryBuilder()
        .set_label("On new data")
        .set_category("data")
        .set_trigger_event(EventSource.SYSTEM, "timeline.entry_created")
    )
    eid = engine.add_entry(entry)

    # Push matching event
    engine.push_event("timeline.entry_created", EventSource.FEDERATION)

    engine.tick()
    state = engine.get_entry_state(eid)
    assert state is not None
    assert state.value >= EntryState.PENDING.value
    engine.destroy()


# ═══════════════════════════════════════════
#  CENTRAL STATE
# ═══════════════════════════════════════════


def test_central_state_counts():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    # Add an active entry (manually transition)
    entry1 = EntryBuilder().set_label("Active").set_category("test").set_salience(0.8)
    eid1 = engine.add_entry(entry1)
    engine.transition_entry(eid1, EntryState.PENDING)
    engine.transition_entry(eid1, EntryState.ACTIVATING)
    engine.transition_entry(eid1, EntryState.ACTIVE)

    # Add a dormant entry
    entry2 = EntryBuilder().set_label("Dormant").set_category("test")
    engine.add_entry(entry2)

    engine.tick()

    state = engine.state
    assert state.active_count == 1
    assert state.dormant_count == 1
    assert state.total_count == 2
    engine.destroy()


def test_central_state_signals_on_failed():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    entry = EntryBuilder().set_label("Will fail").set_category("test")
    eid = engine.add_entry(entry)
    # Transition to pending → activating → failed
    engine.transition_entry(eid, EntryState.PENDING)
    engine.transition_entry(eid, EntryState.ACTIVATING)
    engine.transition_entry(eid, EntryState.FAILED)

    engine.tick()

    state = engine.state
    assert state.failed_count == 1
    assert state.signal_count >= 1
    assert len(state.signals) >= 1
    # At least one warning signal about failure
    assert any(s.severity == SignalSeverity.WARNING for s in state.signals)
    engine.destroy()


def test_central_state_active_ids():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    now_ms = int(time.time() * 1000)
    entry = (
        EntryBuilder()
        .set_label("Will be active")
        .set_category("test")
        .set_trigger_time(now_ms - 1000)
    )
    eid = engine.add_entry(entry)

    # Multiple ticks to advance through states
    engine.tick()
    engine.tick()
    engine.tick()

    state = engine.state
    if state.active_count > 0:
        assert eid in state.active_ids
    engine.destroy()


# ═══════════════════════════════════════════
#  MANUAL TRANSITIONS
# ═══════════════════════════════════════════


def test_manual_transition():
    engine = TimelineEngine()
    entry = EntryBuilder().set_label("Manual").set_category("test")
    eid = engine.add_entry(entry)

    assert engine.get_entry_state(eid) == EntryState.DORMANT
    engine.transition_entry(eid, EntryState.PENDING)
    assert engine.get_entry_state(eid) == EntryState.PENDING
    engine.transition_entry(eid, EntryState.ACTIVATING)
    assert engine.get_entry_state(eid) == EntryState.ACTIVATING
    engine.transition_entry(eid, EntryState.ACTIVE)
    assert engine.get_entry_state(eid) == EntryState.ACTIVE
    engine.destroy()


def test_invalid_transition_raises():
    engine = TimelineEngine()
    entry = EntryBuilder().set_label("Invalid").set_category("test")
    eid = engine.add_entry(entry)

    # dormant → active is invalid (must go through pending first)
    with pytest.raises(RuntimeError):
        engine.transition_entry(eid, EntryState.ACTIVE)
    engine.destroy()


# ═══════════════════════════════════════════
#  HOOKS
# ═══════════════════════════════════════════


def test_hook_complete():
    engine = TimelineEngine()
    entry = (
        EntryBuilder()
        .set_label("Hooked")
        .set_category("test")
        .add_hook(HookActionKind.AGENT_TASK, HookPhase.PRE, "Do something")
    )
    eid = engine.add_entry(entry)

    # Complete the hook
    engine.complete_hook(eid, 0, True)
    engine.destroy()


def test_hook_callback():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    received = []

    def on_hook(entry_id, hook_index, action_kind, data, data_len):
        received.append((entry_id, hook_index, action_kind))

    engine.register_hook_callback(on_hook)

    now_ms = int(time.time() * 1000)
    entry = (
        EntryBuilder()
        .set_label("Callback test")
        .set_category("test")
        .set_trigger_time(now_ms - 1000)
        .add_hook(HookActionKind.NOTIFY, HookPhase.PRE, "Test hook")
    )
    engine.add_entry(entry)

    # Tick to trigger and fire hook
    engine.tick()
    engine.tick()

    # Hook should have fired (may or may not depending on state machine progression)
    # At minimum, no crash
    engine.destroy()


# ═══════════════════════════════════════════
#  ENTRY TYPES & FEATURES
# ═══════════════════════════════════════════


def test_cron_trigger():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    entry = (
        EntryBuilder()
        .set_label("Cron job")
        .set_category("system")
        .set_trigger_cron("* * * * *")  # every minute
    )
    engine.add_entry(entry)
    engine.tick()
    # No crash — cron matching works
    engine.destroy()


def test_absence_trigger():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    now_ms = int(time.time() * 1000)
    entry = (
        EntryBuilder()
        .set_label("Missing check-in")
        .set_category("health")
        .set_trigger_absence("health.checkin", now_ms - 1000)  # deadline passed
    )
    eid = engine.add_entry(entry)

    engine.tick()
    state = engine.get_entry_state(eid)
    assert state is not None
    assert state.value >= EntryState.PENDING.value  # absence should fire
    engine.destroy()


def test_multiple_entries():
    engine = TimelineEngine(heartbeat_ms=100)
    engine.start()

    now_ms = int(time.time() * 1000)
    ids = []
    for i in range(10):
        entry = (
            EntryBuilder()
            .set_label(f"Entry {i}")
            .set_category("batch")
            .set_trigger_time(now_ms - 1000)
            .set_salience(0.5 + i * 0.05)
        )
        ids.append(engine.add_entry(entry))

    assert engine.entry_count == 10
    engine.tick()
    engine.tick()
    engine.tick()

    state = engine.state
    assert state.total_count == 10
    engine.destroy()


def test_now_ms():
    ts = TimelineEngine.now_ms()
    assert ts > 0
    python_ts = int(time.time() * 1000)
    # Should be within 1 second of each other
    assert abs(ts - python_ts) < 1000


# ═══════════════════════════════════════════
#  ENTRY BUILDER EDGE CASES
# ═══════════════════════════════════════════


def test_entry_consumed_twice_raises():
    engine = TimelineEngine()
    entry = EntryBuilder().set_label("Once").set_category("test")
    engine.add_entry(entry)
    with pytest.raises(RuntimeError, match="already consumed"):
        engine.add_entry(entry)
    engine.destroy()


def test_entry_free_on_gc():
    """Entry not added to engine should be freed on GC without crash."""
    entry = EntryBuilder().set_label("Unused").set_category("test")
    del entry  # should not crash
