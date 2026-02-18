"""
Rich Timeline Flow Tests — exercises ALL kernel capabilities.

Tests cover: sequential dependencies, branching via events, absence triggers,
DATA entries, conflict resolution, hook behavior, event storms, window expiry,
multi-entry chains, and CME autonomous operation patterns.

Uses direct FFI bridge (TimelineEngine + EntryBuilder), synchronous.
Skips if libpodos not built.
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
#  HELPERS
# ═══════════════════════════════════════════

def _make_engine(**kwargs) -> TimelineEngine:
    """Create a fresh engine, started, with sensible test defaults."""
    engine = TimelineEngine(
        heartbeat_ms=kwargs.get("heartbeat_ms", 1000),
        max_entries=kwargs.get("max_entries", 100),
        max_events_per_tick=kwargs.get("max_events_per_tick", 256),
    )
    engine.start()
    return engine


def _now_ms() -> int:
    return int(time.time() * 1000)


def _advance_entry(engine: TimelineEngine, entry_id: uuid.UUID, target: EntryState):
    """
    Manually advance an entry through the state machine to the target state.

    The state machine is: dormant(0) → pending(1) → activating(2) → active(3)
                          → deactivating(4) → completed(5)

    Each transition must go to the next valid state. We walk through them.
    """
    # State machine path
    path = [
        EntryState.DORMANT,
        EntryState.PENDING,
        EntryState.ACTIVATING,
        EntryState.ACTIVE,
        EntryState.DEACTIVATING,
        EntryState.COMPLETED,
    ]

    current = engine.get_entry_state(entry_id)
    if current is None:
        raise RuntimeError(f"Entry {entry_id} not found")

    current_idx = path.index(EntryState(current))
    target_idx = path.index(target)

    for i in range(current_idx + 1, target_idx + 1):
        engine.transition_entry(entry_id, path[i])


def _hookless_entry(
    label: str = "test",
    category: str = "general",
    salience: float = 0.5,
    visibility: Visibility = Visibility.PRIVATE,
    entry_type: EntryType = EntryType.TASK,
) -> EntryBuilder:
    """Create a simple entry builder with no hooks or triggers (manual activation)."""
    return (
        EntryBuilder()
        .set_label(label)
        .set_category(category)
        .set_salience(salience)
        .set_visibility(visibility)
        .set_entry_type(entry_type)
    )


# ═══════════════════════════════════════════
#  SEQUENTIAL DEPENDENCIES
# ═══════════════════════════════════════════


class TestSequentialDependencies:
    """Test dependency chains where entries depend on other entries reaching a state."""

    def test_dependency_chain_three_steps(self):
        """A→B→C with hard deps on COMPLETED. Verify correct multi-tick progression."""
        engine = _make_engine()
        try:
            # A: no deps
            a = _hookless_entry(label="Step A", category="chain")
            a_id = engine.add_entry(a)

            # B: depends on A COMPLETED
            b = _hookless_entry(label="Step B", category="chain")
            b.add_dependency(a_id, EntryState.COMPLETED, is_hard=True)
            b_id = engine.add_entry(b)

            # C: depends on B COMPLETED
            c = _hookless_entry(label="Step C", category="chain")
            c.add_dependency(b_id, EntryState.COMPLETED, is_hard=True)
            c_id = engine.add_entry(c)

            # All start dormant
            assert engine.get_entry_state(a_id) == EntryState.DORMANT
            assert engine.get_entry_state(b_id) == EntryState.DORMANT
            assert engine.get_entry_state(c_id) == EntryState.DORMANT

            # Manually activate A and advance to completed
            _advance_entry(engine, a_id, EntryState.PENDING)
            engine.tick()  # pending → activating (no deps)
            assert engine.get_entry_state(a_id) == EntryState.ACTIVATING

            engine.tick()  # activating → active (no hooks)
            assert engine.get_entry_state(a_id) == EntryState.ACTIVE

            _advance_entry(engine, a_id, EntryState.COMPLETED)
            assert engine.get_entry_state(a_id) == EntryState.COMPLETED

            # B should still be dormant — it needs to be moved to pending first
            assert engine.get_entry_state(b_id) == EntryState.DORMANT
            _advance_entry(engine, b_id, EntryState.PENDING)

            # Now tick — B's dep (A COMPLETED) is satisfied, so B→activating
            engine.tick()
            assert engine.get_entry_state(b_id) == EntryState.ACTIVATING

            engine.tick()  # activating → active
            assert engine.get_entry_state(b_id) == EntryState.ACTIVE

            _advance_entry(engine, b_id, EntryState.COMPLETED)

            # C: move to pending and tick
            _advance_entry(engine, c_id, EntryState.PENDING)
            engine.tick()
            assert engine.get_entry_state(c_id) == EntryState.ACTIVATING

            engine.tick()
            assert engine.get_entry_state(c_id) == EntryState.ACTIVE
        finally:
            engine.destroy()

    def test_dependency_blocks_until_satisfied(self):
        """B depends on A at ACTIVE. B stays pending until A reaches active."""
        engine = _make_engine()
        try:
            a = _hookless_entry(label="Prereq", category="blocking")
            a_id = engine.add_entry(a)

            b = _hookless_entry(label="Blocked", category="blocking")
            b.add_dependency(a_id, EntryState.ACTIVE, is_hard=True)
            b_id = engine.add_entry(b)

            # Move both to pending
            _advance_entry(engine, a_id, EntryState.PENDING)
            _advance_entry(engine, b_id, EntryState.PENDING)

            # Tick — A has no deps, moves to activating. B is blocked.
            engine.tick()
            assert engine.get_entry_state(a_id) == EntryState.ACTIVATING
            assert engine.get_entry_state(b_id) == EntryState.PENDING  # blocked!

            # A → active (via tick)
            engine.tick()
            assert engine.get_entry_state(a_id) == EntryState.ACTIVE

            # Now tick again — B's dep (A ACTIVE) is now satisfied
            engine.tick()
            assert engine.get_entry_state(b_id) == EntryState.ACTIVATING
        finally:
            engine.destroy()

    def test_soft_dependency_allows_activation(self):
        """B has soft dep on A. B activates even though A hasn't completed."""
        engine = _make_engine()
        try:
            a = _hookless_entry(label="Soft Prereq", category="soft")
            a_id = engine.add_entry(a)

            b = _hookless_entry(label="Soft Dependent", category="soft")
            b.add_dependency(a_id, EntryState.COMPLETED, is_hard=False)  # soft!
            b_id = engine.add_entry(b)

            # A stays dormant. Move B to pending.
            _advance_entry(engine, b_id, EntryState.PENDING)

            # Tick — soft dep not met but B should still advance
            engine.tick()
            assert engine.get_entry_state(b_id) == EntryState.ACTIVATING
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  BRANCHING VIA EVENTS
# ═══════════════════════════════════════════


class TestBranching:
    """Test branching: one entry pushes different events depending on outcome."""

    def test_branch_success_path(self):
        """A completes → push 'outcome.success' → B activates, C stays dormant."""
        engine = _make_engine()
        try:
            # A: the deciding entry
            a = _hookless_entry(label="Decision", category="branch")
            a_id = engine.add_entry(a)

            # B: listens for outcome.success
            b = _hookless_entry(label="Success Handler", category="branch")
            b.set_trigger_event(EventSource.SYSTEM, "outcome.success")
            b_id = engine.add_entry(b)

            # C: listens for outcome.failure
            c = _hookless_entry(label="Failure Handler", category="branch")
            c.set_trigger_event(EventSource.SYSTEM, "outcome.failure")
            c_id = engine.add_entry(c)

            # B and C both dormant (event-triggered)
            assert engine.get_entry_state(b_id) == EntryState.DORMANT
            assert engine.get_entry_state(c_id) == EntryState.DORMANT

            # Complete A, then push success event
            _advance_entry(engine, a_id, EntryState.COMPLETED)
            engine.push_event("outcome.success", EventSource.SYSTEM)

            # Tick processes events — B should wake up, C stays dormant
            engine.tick()
            b_state = engine.get_entry_state(b_id)
            c_state = engine.get_entry_state(c_id)
            assert b_state == EntryState.PENDING, f"B should be pending, got {b_state}"
            assert c_state == EntryState.DORMANT, f"C should stay dormant, got {c_state}"
        finally:
            engine.destroy()

    def test_branch_failure_path(self):
        """A fails → push 'outcome.failure' → C activates, B stays dormant."""
        engine = _make_engine()
        try:
            a = _hookless_entry(label="Decision", category="branch")
            a_id = engine.add_entry(a)

            b = _hookless_entry(label="Success Handler", category="branch")
            b.set_trigger_event(EventSource.SYSTEM, "outcome.success")
            b_id = engine.add_entry(b)

            c = _hookless_entry(label="Failure Handler", category="branch")
            c.set_trigger_event(EventSource.SYSTEM, "outcome.failure")
            c_id = engine.add_entry(c)

            # Push failure event
            engine.push_event("outcome.failure", EventSource.SYSTEM)

            engine.tick()
            assert engine.get_entry_state(b_id) == EntryState.DORMANT
            assert engine.get_entry_state(c_id) == EntryState.PENDING
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  ABSENCE TRIGGERS
# ═══════════════════════════════════════════


class TestAbsenceTriggers:
    """Test absence triggers — fire when an expected event doesn't arrive by deadline."""

    def test_absence_fires_after_deadline(self):
        """Deadline in the past → tick → entry activates."""
        engine = _make_engine()
        try:
            past_deadline = _now_ms() - 60_000  # 1 minute ago

            entry = _hookless_entry(label="Absence Monitor", category="system")
            entry.set_trigger_absence("expected.event", past_deadline)
            eid = engine.add_entry(entry)

            assert engine.get_entry_state(eid) == EntryState.DORMANT

            engine.tick()
            state = engine.get_entry_state(eid)
            assert state == EntryState.PENDING, f"Expected PENDING after absence fires, got {EntryState(state).name}"
        finally:
            engine.destroy()

    def test_absence_stays_dormant_before_deadline(self):
        """Deadline in the future → tick → stays dormant."""
        engine = _make_engine()
        try:
            future_deadline = _now_ms() + 3_600_000  # 1 hour from now

            entry = _hookless_entry(label="Future Absence", category="system")
            entry.set_trigger_absence("expected.event", future_deadline)
            eid = engine.add_entry(entry)

            engine.tick()
            assert engine.get_entry_state(eid) == EntryState.DORMANT
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  DATA ENTRIES
# ═══════════════════════════════════════════


class TestDataEntries:
    """Test DATA type entries — passive, no hooks, just state tracking."""

    def test_data_entry_passive(self):
        """DATA type entry with no hooks progresses through states without hook dispatch."""
        engine = _make_engine()
        try:
            entry = _hookless_entry(
                label="Sweep Results",
                category="system.metrics",
                entry_type=EntryType.DATA,
            )
            eid = engine.add_entry(entry)

            assert engine.get_entry_state(eid) == EntryState.DORMANT

            # Manually progress through states — DATA entries are passive
            _advance_entry(engine, eid, EntryState.PENDING)
            engine.tick()  # pending → activating (no deps)
            assert engine.get_entry_state(eid) == EntryState.ACTIVATING

            engine.tick()  # activating → active (no hooks)
            assert engine.get_entry_state(eid) == EntryState.ACTIVE

            _advance_entry(engine, eid, EntryState.COMPLETED)
            assert engine.get_entry_state(eid) == EntryState.COMPLETED
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  CONFLICT RESOLUTION
# ═══════════════════════════════════════════


class TestConflictResolution:
    """Test three-stream conflict resolution: PRIVATE > INTERNAL > OPEN."""

    def test_private_shadows_internal(self):
        """PRIVATE entry shadows INTERNAL entry in same category with overlapping windows."""
        engine = _make_engine()
        try:
            now = _now_ms()
            window_start = now - 3_600_000  # 1h ago
            window_end = now + 3_600_000  # 1h from now

            # PRIVATE entry
            priv = _hookless_entry(
                label="Private Health",
                category="health",
                salience=0.8,
                visibility=Visibility.PRIVATE,
            )
            priv.set_window(window_start, window_end)
            priv_id = engine.add_entry(priv)

            # INTERNAL entry, same category and window
            internal = _hookless_entry(
                label="Internal Health",
                category="health",
                salience=0.7,
                visibility=Visibility.INTERNAL,
            )
            internal.set_window(window_start, window_end)
            internal_id = engine.add_entry(internal)

            # Advance both to active
            _advance_entry(engine, priv_id, EntryState.PENDING)
            _advance_entry(engine, internal_id, EntryState.PENDING)
            engine.tick()  # both → activating

            engine.tick()  # both → active, conflict resolution runs

            # PRIVATE should keep salience, INTERNAL should be shadowed
            priv_salience = engine.get_entry_salience(priv_id)
            internal_salience = engine.get_entry_salience(internal_id)

            assert priv_salience == pytest.approx(0.8, abs=0.01), f"PRIVATE salience should be ~0.8, got {priv_salience}"
            assert internal_salience == pytest.approx(0.7 * 0.3, abs=0.01), f"INTERNAL salience should be ~0.21 (shadowed), got {internal_salience}"
        finally:
            engine.destroy()

    def test_private_shadows_open(self):
        """PRIVATE entry shadows OPEN entry."""
        engine = _make_engine()
        try:
            now = _now_ms()
            window_start = now - 3_600_000
            window_end = now + 3_600_000

            priv = _hookless_entry(
                label="Private Info",
                category="health",
                salience=0.8,
                visibility=Visibility.PRIVATE,
            )
            priv.set_window(window_start, window_end)
            priv_id = engine.add_entry(priv)

            public = _hookless_entry(
                label="Open Info",
                category="health",
                salience=0.6,
                visibility=Visibility.OPEN,
            )
            public.set_window(window_start, window_end)
            public_id = engine.add_entry(public)

            _advance_entry(engine, priv_id, EntryState.PENDING)
            _advance_entry(engine, public_id, EntryState.PENDING)
            engine.tick()
            engine.tick()

            priv_salience = engine.get_entry_salience(priv_id)
            public_salience = engine.get_entry_salience(public_id)

            assert priv_salience == pytest.approx(0.8, abs=0.01)
            assert public_salience == pytest.approx(0.6 * 0.3, abs=0.01), f"OPEN salience should be ~0.18, got {public_salience}"
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  HOOK BEHAVIOR
# ═══════════════════════════════════════════


class TestHookBehavior:
    """Test hook dispatch and how it affects entry state progression."""

    def test_hook_failure_blocks_entry(self):
        """Failed pre-hook blocks entry in activating state.

        Documents current behavior: hook retry is NOT implemented in the tick
        loop (resetForRetry exists but is never called). Failed hooks leave
        entries stuck in activating until manual intervention.
        """
        engine = _make_engine()
        hooks_fired = []

        def on_hook(entry_id_bytes, hook_index, action_kind, data, data_len):
            hooks_fired.append((hook_index, action_kind))

        engine.register_hook_callback(on_hook)

        try:
            builder = _hookless_entry(label="Hookable", category="general")
            builder.add_hook(
                action=HookActionKind.AGENT_TASK,
                phase=HookPhase.PRE,
                prompt="Do something",
                max_retries=0,
            )
            eid = engine.add_entry(builder)

            _advance_entry(engine, eid, EntryState.PENDING)
            engine.tick()  # pending → activating
            assert engine.get_entry_state(eid) == EntryState.ACTIVATING

            engine.tick()  # hook fires
            assert len(hooks_fired) >= 1

            # Mark hook as FAILED
            engine.complete_hook(eid, 0, False)

            # Tick — entry should be stuck in activating (or failed)
            engine.tick()
            state = engine.get_entry_state(eid)
            # With max_retries=0 and exhaustion, should fail
            assert state in (EntryState.ACTIVATING, EntryState.FAILED), \
                f"Expected ACTIVATING or FAILED, got {EntryState(state).name}"
        finally:
            engine.destroy()

    def test_hook_completes_advances_entry(self):
        """Successful hook completion → entry advances to active."""
        engine = _make_engine()
        hooks_fired = []

        def on_hook(entry_id_bytes, hook_index, action_kind, data, data_len):
            hooks_fired.append((hook_index, action_kind))

        engine.register_hook_callback(on_hook)

        try:
            builder = _hookless_entry(label="Will Succeed", category="general")
            builder.add_hook(
                action=HookActionKind.AGENT_TASK,
                phase=HookPhase.PRE,
                prompt="Do something",
            )
            eid = engine.add_entry(builder)

            _advance_entry(engine, eid, EntryState.PENDING)
            engine.tick()  # pending → activating
            engine.tick()  # hook dispatch

            assert len(hooks_fired) >= 1

            # Complete the hook successfully
            engine.complete_hook(eid, 0, True)

            # Tick should advance to active
            engine.tick()
            assert engine.get_entry_state(eid) == EntryState.ACTIVE
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  EVENT HANDLING
# ═══════════════════════════════════════════


class TestEventHandling:
    """Test event queue processing at scale."""

    def test_event_storm_100_events(self):
        """Push 100 events, 3 listeners. Verify all 3 activate, no events dropped."""
        engine = _make_engine(max_events_per_tick=256)
        try:
            # Create 3 listeners for different event types
            listeners = []
            for i in range(3):
                entry = _hookless_entry(label=f"Listener {i}", category=f"listen{i}")
                entry.set_trigger_event(EventSource.SYSTEM, f"storm.event.{i}")
                eid = engine.add_entry(entry)
                listeners.append(eid)

            # Push 100 events — events 0, 1, 2 match our listeners
            for i in range(100):
                engine.push_event(f"storm.event.{i % 10}", EventSource.SYSTEM)

            # Tick to process events
            engine.tick()

            # All 3 listeners should have woken up
            for i, eid in enumerate(listeners):
                state = engine.get_entry_state(eid)
                assert state == EntryState.PENDING, \
                    f"Listener {i} should be PENDING, got {EntryState(state).name}"
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  WINDOW EXPIRY
# ═══════════════════════════════════════════


class TestWindowExpiry:
    """Test that active entries with expired windows get deactivated."""

    def test_window_expiry_deactivates(self):
        """Active entry with expired window_end → deactivating."""
        engine = _make_engine()
        try:
            now = _now_ms()
            # Window that ended 1 second ago
            entry = _hookless_entry(label="Expiring", category="timed")
            entry.set_window(now - 3_600_000, now - 1_000)  # ended 1s ago
            eid = engine.add_entry(entry)

            # Advance to active
            _advance_entry(engine, eid, EntryState.ACTIVE)
            assert engine.get_entry_state(eid) == EntryState.ACTIVE

            # Tick should detect expired window
            engine.tick()
            state = engine.get_entry_state(eid)
            assert state == EntryState.DEACTIVATING, \
                f"Expected DEACTIVATING after window expiry, got {EntryState(state).name}"
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  MULTI-ENTRY CHAIN
# ═══════════════════════════════════════════


class TestMultiEntryChain:
    """Test complex multi-hop chains combining triggers and dependencies."""

    def test_cron_to_event_to_dependency(self):
        """
        Full 3-hop chain:
        A (manual trigger, simulating cron) → completes → push event
        → B (event listener) → completes → C (dep on B) activates.
        """
        engine = _make_engine()
        try:
            # A: manual trigger (simulating what cron would do)
            a = _hookless_entry(label="Cron Job", category="pipeline")
            a_id = engine.add_entry(a)

            # B: event listener
            b = _hookless_entry(label="Event Reactor", category="pipeline")
            b.set_trigger_event(EventSource.SYSTEM, "job.completed")
            b_id = engine.add_entry(b)

            # C: depends on B completed
            c = _hookless_entry(label="Final Step", category="pipeline")
            c.add_dependency(b_id, EntryState.COMPLETED, is_hard=True)
            c_id = engine.add_entry(c)

            # Step 1: Complete A
            _advance_entry(engine, a_id, EntryState.COMPLETED)

            # Step 2: Push the event that A "would have" pushed
            engine.push_event("job.completed", EventSource.SYSTEM)
            engine.tick()  # B should wake up
            assert engine.get_entry_state(b_id) == EntryState.PENDING

            # Step 3: Advance B through to completed
            engine.tick()  # B: pending → activating
            assert engine.get_entry_state(b_id) == EntryState.ACTIVATING

            engine.tick()  # B: activating → active
            assert engine.get_entry_state(b_id) == EntryState.ACTIVE

            _advance_entry(engine, b_id, EntryState.COMPLETED)

            # Step 4: Move C to pending and tick — should advance
            _advance_entry(engine, c_id, EntryState.PENDING)
            engine.tick()
            assert engine.get_entry_state(c_id) == EntryState.ACTIVATING

            engine.tick()
            assert engine.get_entry_state(c_id) == EntryState.ACTIVE
        finally:
            engine.destroy()


# ═══════════════════════════════════════════
#  CME SIMULATION
# ═══════════════════════════════════════════


class TestCMESimulation:
    """Simulate CME (Capsule Memory Engine) autonomous operation patterns."""

    def test_cme_sweep_sequence(self):
        """
        Full DAG: sweep → consolidation (event trigger) → forgetting (dep).
        Verify correct ordering: sweep completes, event fires, consolidation
        wakes, completes, forgetting unblocks.
        """
        engine = _make_engine()
        try:
            # 1. Memory Sweep (manual trigger for test)
            sweep = _hookless_entry(
                label="Memory Decay Sweep",
                category="system",
                salience=0.1,
            )
            sweep_id = engine.add_entry(sweep)

            # 2. Consolidation — triggered by sweep completion event
            consolidation = _hookless_entry(
                label="Memory Consolidation",
                category="system",
                salience=0.2,
            )
            consolidation.set_trigger_event(EventSource.SYSTEM, "memory.sweep_completed")
            consolidation_id = engine.add_entry(consolidation)

            # 3. Forgetting — depends on consolidation COMPLETED
            forgetting = _hookless_entry(
                label="Memory Forgetting",
                category="system",
                salience=0.1,
            )
            forgetting.add_dependency(consolidation_id, EntryState.COMPLETED, is_hard=True)
            forgetting_id = engine.add_entry(forgetting)

            # All dormant initially
            assert engine.get_entry_state(sweep_id) == EntryState.DORMANT
            assert engine.get_entry_state(consolidation_id) == EntryState.DORMANT
            assert engine.get_entry_state(forgetting_id) == EntryState.DORMANT

            # --- Phase 1: Complete sweep ---
            _advance_entry(engine, sweep_id, EntryState.COMPLETED)

            # Simulate sweep pushing completion event
            engine.push_event("memory.sweep_completed", EventSource.SYSTEM)
            engine.tick()

            # Consolidation should now be pending (event triggered)
            assert engine.get_entry_state(consolidation_id) == EntryState.PENDING
            # Forgetting still dormant (dep not met)
            assert engine.get_entry_state(forgetting_id) == EntryState.DORMANT

            # --- Phase 2: Advance consolidation ---
            engine.tick()  # pending → activating
            assert engine.get_entry_state(consolidation_id) == EntryState.ACTIVATING

            engine.tick()  # activating → active
            assert engine.get_entry_state(consolidation_id) == EntryState.ACTIVE

            _advance_entry(engine, consolidation_id, EntryState.COMPLETED)

            # --- Phase 3: Forgetting unblocks ---
            _advance_entry(engine, forgetting_id, EntryState.PENDING)
            engine.tick()  # dep satisfied → activating
            assert engine.get_entry_state(forgetting_id) == EntryState.ACTIVATING

            engine.tick()  # activating → active
            assert engine.get_entry_state(forgetting_id) == EntryState.ACTIVE
        finally:
            engine.destroy()

    def test_cme_absence_monitor(self):
        """
        Sweep entry + absence monitor. Run past deadline without sweep
        completing → absence fires.
        """
        engine = _make_engine()
        try:
            # Sweep (manual trigger)
            sweep = _hookless_entry(label="Sweep", category="system")
            sweep_id = engine.add_entry(sweep)

            # Absence monitor: expects memory.sweep_completed within a deadline
            # Set deadline in the past to simulate "hasn't run"
            past_deadline = _now_ms() - 10_000  # 10s ago

            monitor = _hookless_entry(label="Sweep SLA Monitor", category="system")
            monitor.set_trigger_absence("memory.sweep_completed", past_deadline)
            monitor_id = engine.add_entry(monitor)

            # Sweep is still dormant (hasn't run)
            assert engine.get_entry_state(sweep_id) == EntryState.DORMANT

            # Tick — absence should fire because deadline passed
            engine.tick()
            state = engine.get_entry_state(monitor_id)
            assert state == EntryState.PENDING, \
                f"Absence monitor should fire (PENDING), got {EntryState(state).name}"
        finally:
            engine.destroy()
