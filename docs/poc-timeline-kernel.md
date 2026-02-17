# PodOS Timeline Kernel: PoC Implementation Plan

> Zig from day one. Pod to pool to public. Proactive by structure.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Zig Kernel Design](#zig-kernel-design)
3. [Python FFI Bridge](#python-ffi-bridge)
4. [Edge Cases & Solutions](#edge-cases--solutions)
5. [Database Schema](#database-schema)
6. [API Endpoints](#api-endpoints)
7. [CLI Commands](#cli-commands)
8. [UI Components](#ui-components)
9. [Pod-to-Pod Interactivity](#pod-to-pod-interactivity)
10. [Public Stream (Registry)](#public-stream-registry)
11. [Agent Operating Modes & Temporal Discovery](#agent-operating-modes--temporal-discovery)
12. [Encrypted Edge Storage (Pool Availability)](#encrypted-edge-storage-pool-availability)
13. [Agent Integration](#agent-integration)
14. [Demo Scenario](#demo-scenario)
15. [Build Order](#build-order)
16. [File Manifest](#file-manifest)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        POD (one per entity)                      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Zig Kernel: libpodos.dylib / libpodos.so                 │  │
│  │                                                            │  │
│  │  Timeline Engine     Event Queue      Dependency DAG       │  │
│  │  ├── Tick-tock loop  ├── Ring buffer  ├── Adjacency list   │  │
│  │  ├── State machine   ├── Drain/push   ├── Topo sort        │  │
│  │  └── Adaptive wake   └── Priority     └── Cycle detect     │  │
│  │                                                            │  │
│  │  Resolution Engine   Central State    Transition Log       │  │
│  │  ├── 3-stream merge  ├── Computed     ├── Append-only      │  │
│  │  ├── Private > Int   │   snapshot     ├── Replay on crash  │  │
│  │  │   > Open          ├── Delta emit   └── Pruning policy   │  │
│  │  └── Category+time   └── Subscribers                      │  │
│  │       conflict match                                       │  │
│  │                                                            │  │
│  │  C ABI exports:                                            │  │
│  │    podos_init, podos_tick, podos_create_entry,             │  │
│  │    podos_push_event, podos_get_state, podos_subscribe,     │  │
│  │    podos_register_hook_handler, podos_destroy              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │ ctypes FFI                             │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Python Host Layer (existing TrustMesh + new bridge)       │  │
│  │                                                            │  │
│  │  src/timeline_bridge.py  ← ctypes wrapper around libpodos │  │
│  │  src/routes/timeline.py  ← FastAPI endpoints               │  │
│  │  src/agents.py           ← new timeline tools for agent    │  │
│  │  src/federation.py       ← timeline sync additions         │  │
│  │  src/cli.py              ← timeline subcommands            │  │
│  │  src/main.py             ← kernel lifecycle in lifespan()  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │ HTTP                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Next.js UI (existing TrustMesh UI + timeline components)  │  │
│  │                                                            │  │
│  │  TimelineView.tsx     ← main timeline display              │  │
│  │  EntryCard.tsx        ← individual entry with state badge  │  │
│  │  CentralState.tsx     ← live pod state dashboard           │  │
│  │  StreamSubscriptions  ← manage public/pool subscriptions   │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │ federation sync                    │ public stream
         ▼                                    ▼
┌─────────────────┐                 ┌──────────────────────┐
│  Other Pods      │                 │  Registry (port 8100) │
│  (peers/pools)   │                 │  + Public Timeline    │
│  Shadow entries   │                 │  + SSE stream         │
│  Pool timelines   │                 │  + Subscribe API      │
└─────────────────┘                 └──────────────────────┘
```

---

## Zig Kernel Design

### Directory Structure

```
trustmesh-core/
  kernel/
    build.zig           ← Zig build script
    src/
      main.zig          ← C ABI exports, kernel lifecycle
      timeline.zig      ← Timeline engine, tick-tock loop
      entry.zig         ← Entry struct, state machine
      event.zig         ← Event queue, trigger matching
      cron.zig          ← Cron expression parser + matcher
      dag.zig           ← Dependency graph
      resolution.zig    ← 3-stream merge, conflict resolution
      state.zig         ← Central state computation
      log.zig           ← Transition log (append-only)
      types.zig         ← Shared types, enums, constants
    tests/
      test_entry.zig    ← Entry state machine tests
      test_dag.zig      ← DAG cycle detection, topo sort
      test_resolution.zig ← Conflict resolution tests
      test_timeline.zig ← Integration: tick produces correct state
    zig-out/
      lib/
        libpodos.dylib  ← macOS output
        libpodos.so     ← Linux output
```

### Core Types (`types.zig`)

> **Design decisions baked into types:**
> - **Cron evaluation in Zig**: The kernel has a native cron parser (~80 lines). Cron patterns are standard 5-field (`min hour day month weekday`). `cron_matches(pattern, timestamp)` runs during `evaluate_time_triggers()` each tick. No FFI crossing for something that runs every tick — pure performance.
> - **Condition triggers**: Evaluated by Python host. The kernel has `TriggerKind.condition` but no expression language. Host evaluates conditions and pushes manual events when true.
> - **Fixed-size arrays**: All strings use fixed-size `[N]u8` + `_len` pattern. No heap allocations in entry structs. Trade-off: wastes memory but makes entries memcpy-safe and serialization trivial.
> - **JSON for C ABI payloads**: Entry creation and events cross the FFI boundary as JSON strings (parsed by Zig's `std.json`). Avoids complex struct marshaling. Performance cost is acceptable for PoC volumes.
> - **External integrations (Calendar, Email, etc.)**: External apps connect through MCP or integration adapters in the Python host. The host creates timeline entries from external events (e.g., Google Calendar event → entry with time window, ref_type: saas). The kernel treats them like any other entry. Integration adapters are Python-side — the kernel is integration-agnostic.
>
> **Integration adapter pattern:**
> ```
> External Source (Calendar/Email/GitHub via MCP)
>   ↓ MCP tool or webhook
> Python Host (src/integrations/{adapter}.py)
>   ↓ transforms to timeline entry
>   ↓ podos_create_entry(json) or podos_push_event(json)
> Zig Kernel (entry with ref_type: saas, ref_uri: "gcal://event-id")
>   → standard lifecycle: triggers, hooks, resolution, central state
> ```
> Any MCP-connected app becomes a timeline data source. The kernel doesn't know or care about the source — it just processes entries by their types, triggers, and visibility.

```zig
const std = @import("std");

// --- Identifiers ---

pub const EntryId = [16]u8;    // UUID as 16 bytes
pub const TimelineId = [16]u8;
pub const StreamId = [16]u8;

// --- Visibility (resolution priority encoded in enum value) ---

pub const Visibility = enum(u8) {
    open = 1,       // lowest priority
    internal = 2,   // middle
    private = 3,    // highest — always wins

    pub fn overrides(self: Visibility, other: Visibility) bool {
        return @intFromEnum(self) > @intFromEnum(other);
    }
};

// --- Entry State Machine ---

pub const EntryState = enum(u8) {
    dormant = 0,       // exists but not yet relevant
    pending = 1,       // trigger fired, checking deps
    activating = 2,    // deps met, pre-hooks firing
    active = 3,        // live — agent sees this
    deactivating = 4,  // deactivation trigger fired, post-hooks firing
    completed = 5,     // normal end
    failed = 6,        // hook or dep failed
    archived = 7,      // kept for history
    deleted = 8,       // gone
};

// --- Valid state transitions ---

pub fn valid_transition(from: EntryState, to: EntryState) bool {
    return switch (from) {
        .dormant => to == .pending or to == .deleted,
        .pending => to == .activating or to == .failed or to == .deleted,
        .activating => to == .active or to == .failed,
        .active => to == .deactivating or to == .failed,
        .deactivating => to == .completed or to == .archived or to == .failed,
        .completed => to == .archived or to == .deleted,
        .failed => to == .archived or to == .deleted or to == .pending, // retry
        .archived => to == .deleted,
        .deleted => false, // terminal
    };
}

// --- Trigger Types ---

pub const TriggerKind = enum(u8) {
    time = 0,         // fire at datetime or cron
    event = 1,        // fire on matching event
    condition = 2,    // fire when predicate is true
    dependency = 3,   // fire when deps are satisfied (implicit)
    absence = 4,      // fire when expected thing DOESN'T happen
    manual = 5,       // fire on explicit command
};

// --- Entry Types ---

pub const EntryType = enum(u8) {
    event = 0,
    idea = 1,
    data = 2,
    reminder = 3,
    hook = 4,
    milestone = 5,
    task = 6,
    signal = 7,
    mount = 8,
    computed = 9,
};

// --- Hook Action Types ---

pub const HookActionKind = enum(u8) {
    agent_task = 0,    // dispatch to LLM agent
    notify = 1,        // push notification to human
    mutate_entry = 2,  // change another entry's state
    create_entry = 3,  // spawn a new entry
    vault_op = 4,      // modify capsule in vault
    integration = 5,   // call external system
    sync = 6,          // push to federation
    pipeline = 7,      // sequential chain of actions
};

// --- Event Sources ---

pub const EventSource = enum(u8) {
    system = 0,       // internal (tick, startup, shutdown)
    user = 1,         // human action
    agent = 2,        // agent output
    integration = 3,  // external system (email, SaaS)
    federation = 4,   // peer pod message
    timeline = 5,     // entry state transition
    public_stream = 6, // registry public timeline
};

// --- Stream Layer ---

pub const StreamLayer = enum(u8) {
    pod = 3,       // highest priority (matches Visibility.private)
    pool = 2,      // middle (matches Visibility.internal)
    public = 1,    // lowest (matches Visibility.open)
};

// --- Timestamps ---
// Unix milliseconds (i64 handles dates well past year 9999)

pub const Timestamp = i64;

pub fn now_ms() Timestamp {
    return std.time.milliTimestamp();
}
```

### Entry Struct (`entry.zig`)

```zig
const types = @import("types.zig");

/// Maximum length for variable-length fields in the fixed-size entry.
/// Longer content is stored externally and referenced by entry_id.
const MAX_REF_URI_LEN = 256;
const MAX_CATEGORY_LEN = 32;
const MAX_TAG_LEN = 32;
const MAX_TAGS = 8;
const MAX_DEPS = 16;
const MAX_HOOKS = 8;
const MAX_HOOK_PROMPT_LEN = 512;

pub const RefType = enum(u8) {
    none = 0,
    capsule = 1,
    saas = 2,
    storage = 3,
    pool = 4,
    timeline = 5,
    url = 6,
    webhook = 7,
    compute = 8,
};

pub const Ref = struct {
    ref_type: RefType,
    uri: [MAX_REF_URI_LEN]u8,
    uri_len: u16,
};

pub const TimeTrigger = struct {
    at: types.Timestamp,          // fire at this exact ms (0 = not set)
    window_start: types.Timestamp, // fire when time enters window (0 = not set)
    window_end: types.Timestamp,   // deactivate when time exits window (0 = not set)
    cron_pattern: [64]u8,          // cron expression (empty = not set)
    cron_len: u8,
    relative_offset_ms: i64,       // offset from anchor (negative = before)
};

pub const EventTriggerMatch = struct {
    source_filter: types.EventSource, // which source to match
    type_pattern: [64]u8,             // glob pattern for event.type
    type_pattern_len: u8,
    from_pattern: [64]u8,             // glob pattern for event.from
    from_pattern_len: u8,
};

pub const Dependency = struct {
    entry_id: types.EntryId,
    required_state: types.EntryState, // must be active or completed
    is_hard: bool,                     // hard = blocks, soft = warns
};

pub const HookStatus = enum(u8) {
    pending = 0,     // not yet fired
    running = 1,     // dispatched to host, awaiting result
    completed = 2,   // host reported success
    failed = 3,      // host reported failure or timeout
    retrying = 4,    // waiting for backoff before retry
    exhausted = 5,   // all retries spent — entry transitions to failed
};

pub const Hook = struct {
    action_kind: types.HookActionKind,
    phase: enum(u1) { pre = 0, post = 1 },
    prompt: [MAX_HOOK_PROMPT_LEN]u8,   // for agent_task: the prompt
    prompt_len: u16,
    timeout_ms: u32,                    // max wait before fail (0 = default 30s)
    max_retries: u8,                    // max retries (0 = no retry)
    retry_backoff_ms: u32,             // base backoff between retries (exponential)

    // Runtime state (not set by creator — managed by engine)
    status: HookStatus,
    attempts: u8,                       // current attempt count
    last_attempt_at: types.Timestamp,   // for backoff calculation
};

/// Absence trigger: fires when an expected event DOESN'T happen by a deadline.
pub const AbsenceTrigger = struct {
    expected_event_type: [64]u8,       // event type we're waiting for
    expected_event_type_len: u8,
    expected_by: types.Timestamp,       // deadline — if not received by this time, fire
    last_checked_at: types.Timestamp,   // last tick we checked (avoids re-firing)
    fired: bool,                        // has this absence already triggered?
};

/// Unified trigger: wraps all trigger variants for activation/deactivation.
/// PoC note: `condition` triggers are evaluated by the Python host (not in kernel).
/// The host pushes a manual event when the condition becomes true.
pub const Trigger = struct {
    kind: types.TriggerKind,
    time: TimeTrigger,                   // used when kind == .time
    event_match: EventTriggerMatch,      // used when kind == .event
    absence: AbsenceTrigger,             // used when kind == .absence
    // .condition: evaluated by Python host, pushes event to kernel
    // .dependency: implicit from deps array (no trigger config needed)
    // .manual: no config needed (explicit API call triggers it)
};

pub const Entry = struct {
    // Identity
    id: types.EntryId,
    timeline_id: types.TimelineId,
    creator_id: [36]u8,              // UUID string of creating user/agent
    creator_id_len: u8,

    // Human-readable label (for CLI/UI display)
    label: [128]u8,
    label_len: u8,

    // Reference (pointer to external state)
    ref: Ref,

    // State
    state: types.EntryState,
    previous_state: types.EntryState,

    // Time binding
    anchor: types.Timestamp,         // 0 = unanchored
    window_start: types.Timestamp,   // 0 = no window
    window_end: types.Timestamp,     // 0 = no window

    // Triggers (unified — includes time, event, absence configs)
    activation_trigger: Trigger,
    deactivation_trigger: Trigger,

    // Dependencies
    deps: [MAX_DEPS]Dependency,
    dep_count: u8,

    // Hooks (each hook tracks its own retry state via HookStatus)
    hooks: [MAX_HOOKS]Hook,
    hook_count: u8,

    // Visibility & classification
    visibility: types.Visibility,
    stream_layer: types.StreamLayer,     // which stream this came from
    entry_type: types.EntryType,
    category: [MAX_CATEGORY_LEN]u8,
    category_len: u8,
    salience: f32,                       // 0.0 to 1.0 (current, after resolution)
    original_salience: f32,              // before resolution (for un-shadowing)

    // Tags (for public stream filtering / discovery)
    tags: [MAX_TAGS][MAX_TAG_LEN]u8,
    tag_lengths: [MAX_TAGS]u8,
    tag_count: u8,

    // Sync & ordering
    logical_clock: u64,                  // Lamport clock for causal ordering (EC-9)

    // Metadata
    created_at: types.Timestamp,
    last_transition_at: types.Timestamp,
    tick_activated: u64,                 // tick number when activated
    tick_deactivated: u64,               // tick number when deactivated
    cascade_depth: u8,                   // how deep in hook chain (0 = root, EC-5)

    // Shadow tracking (for entries from pool/public streams)
    is_shadow: bool,                     // true if this mirrors a remote entry
    shadow_source_pod: [128]u8,          // URL of originating pod
    shadow_source_pod_len: u8,
    shadow_source_entry_id: types.EntryId, // original entry ID on source pod

    // Flags
    is_deleted: bool,
    needs_confirmation: bool,            // visibility upgrade pending confirmation (EC-3)
    missed_while_offline: bool,          // activated+deactivated while pod was offline (EC-1)
};
```

### Timeline Engine (`timeline.zig`)

```zig
const std = @import("std");
const types = @import("types.zig");
const entry_mod = @import("entry.zig");
const event_mod = @import("event.zig");
const dag_mod = @import("dag.zig");
const resolution_mod = @import("resolution.zig");
const state_mod = @import("state.zig");
const log_mod = @import("log.zig");

const Entry = entry_mod.Entry;

pub const EngineConfig = struct {
    heartbeat_ms: u32 = 5000,        // minimum tick interval (5s for PoC)
    max_entries: u32 = 10000,         // max entries in memory
    max_events_per_tick: u32 = 256,   // drain limit per tick
    max_cascade_depth: u8 = 10,       // hook chain depth limit
    max_hooks_per_tick: u32 = 32,     // hook fire limit per tick
    transition_log_path: [256]u8 = undefined, // file path for log
    transition_log_path_len: u16 = 0,
};

/// Callback type for hook dispatch. The kernel calls this when a hook
/// needs to fire. The host (Python) implements the actual work.
pub const HookCallback = *const fn (
    entry_id: *const types.EntryId,
    hook: *const entry_mod.Hook,
    entry_json: [*]const u8,    // serialized entry context
    entry_json_len: u32,
) callconv(.C) void;

/// Callback for state change notifications.
pub const StateCallback = *const fn (
    state_json: [*]const u8,
    state_json_len: u32,
) callconv(.C) void;

pub const Engine = struct {
    config: EngineConfig,
    allocator: std.mem.Allocator,

    // Entry storage (arena-backed for PoC, B-tree for production)
    entries: std.AutoHashMap(types.EntryId, *Entry),

    // Event queue (ring buffer)
    event_queue: event_mod.EventQueue,

    // Dependency graph
    dag: dag_mod.DependencyGraph,

    // Tick state
    tick_count: u64,
    last_tick_at: types.Timestamp,
    next_wake_at: types.Timestamp,   // pre-computed from time triggers
    is_running: bool,

    // Host callbacks
    hook_callback: ?HookCallback,
    state_callback: ?StateCallback,

    // Transition plan (built during TICK, applied during TOCK)
    transition_plan: std.ArrayList(Transition),

    // Central state (recomputed each tock)
    central_state: state_mod.CentralState,

    // Transition log
    log: log_mod.TransitionLog,

    const Transition = struct {
        entry_id: types.EntryId,
        from_state: types.EntryState,
        to_state: types.EntryState,
        trigger_kind: types.TriggerKind,
        hooks_to_fire: std.ArrayList(entry_mod.Hook),
        resolution_note: ?[]const u8,
    };

    // --- Lifecycle ---

    pub fn init(allocator: std.mem.Allocator, config: EngineConfig) !*Engine {
        // Allocate engine, initialize all sub-systems
        // Open transition log file
        // Return ready-to-tick engine
    }

    pub fn deinit(self: *Engine) void {
        // Close log, free all entries, deinit subsystems
    }

    // --- The Tick-Tock Cycle ---

    pub fn tick(self: *Engine) !void {
        if (!self.is_running) return;

        const now = types.now_ms();
        self.tick_count += 1;

        // === TICK PHASE (evaluate, frozen state) ===

        // 1. Drain event queue
        self.process_events(now);

        // 2. Evaluate time triggers
        self.evaluate_time_triggers(now);

        // 3. Evaluate dependency graph
        self.evaluate_dependencies();

        // 4. Resolve conflicts across streams (private > internal > open)
        resolution_mod.resolve_conflicts(
            &self.entries,
            &self.transition_plan,
            now,
        );

        // 5. Validate transition plan
        self.validate_plan();

        // === TOCK PHASE (commit, apply changes) ===

        // 6. Apply state transitions
        for (self.transition_plan.items) |*t| {
            if (self.entries.get(t.entry_id)) |e| {
                e.previous_state = e.state;
                e.state = t.to_state;
                e.last_transition_at = now;

                if (t.to_state == .active) e.tick_activated = self.tick_count;
                if (t.to_state == .completed or t.to_state == .archived)
                    e.tick_deactivated = self.tick_count;

                // 7. Append to transition log
                self.log.append(t, now);
            }
        }

        // 8. Fire hooks (dispatch to host via callback)
        self.dispatch_hooks();

        // 9. Recompute central state
        self.central_state.recompute(&self.entries, self.tick_count, now);

        // 10. Notify subscribers
        if (self.state_callback) |cb| {
            const json = self.central_state.to_json(self.allocator) catch return;
            defer self.allocator.free(json);
            cb(json.ptr, @intCast(json.len));
        }

        // 11. Clear transition plan for next tick
        self.transition_plan.clearRetainingCapacity();

        // 12. Compute next wake time
        self.next_wake_at = self.compute_next_wake(now);
        self.last_tick_at = now;
    }

    fn process_events(self: *Engine, now: types.Timestamp) void {
        var processed: u32 = 0;
        while (self.event_queue.pop()) |evt| {
            if (processed >= self.config.max_events_per_tick) break;

            // Match event against all entries with event triggers
            var it = self.entries.valueIterator();
            while (it.next()) |e| {
                if (e.*.state == .dormant and
                    e.*.activation_trigger == .event and
                    event_mod.matches(&e.*.activation_event, &evt))
                {
                    self.transition_plan.append(.{
                        .entry_id = e.*.id,
                        .from_state = .dormant,
                        .to_state = .pending,
                        .trigger_kind = .event,
                        .hooks_to_fire = std.ArrayList(entry_mod.Hook).init(self.allocator),
                        .resolution_note = null,
                    }) catch continue;
                }
            }
            processed += 1;
        }
    }

    fn evaluate_time_triggers(self: *Engine, now: types.Timestamp) void {
        var it = self.entries.valueIterator();
        while (it.next()) |e| {
            // Activation: dormant entries with time triggers
            if (e.*.state == .dormant and e.*.activation_trigger == .time) {
                if (e.*.activation_time.at > 0 and e.*.activation_time.at <= now) {
                    self.enqueue_transition(e.*.id, .dormant, .pending, .time);
                }
                if (e.*.activation_time.window_start > 0 and
                    e.*.activation_time.window_start <= now)
                {
                    self.enqueue_transition(e.*.id, .dormant, .pending, .time);
                }
            }

            // Deactivation: active entries with time triggers
            if (e.*.state == .active and e.*.deactivation_trigger == .time) {
                if (e.*.deactivation_time.at > 0 and e.*.deactivation_time.at <= now) {
                    self.enqueue_transition(e.*.id, .active, .deactivating, .time);
                }
                if (e.*.window_end > 0 and e.*.window_end <= now) {
                    self.enqueue_transition(e.*.id, .active, .deactivating, .time);
                }
            }
        }
    }

    fn evaluate_dependencies(self: *Engine) void {
        // For all pending entries, check if deps are satisfied
        var it = self.entries.valueIterator();
        while (it.next()) |e| {
            if (e.*.state != .pending) continue;
            if (e.*.dep_count == 0) {
                // No deps — go straight to activating
                self.enqueue_transition(e.*.id, .pending, .activating, .dependency);
                continue;
            }

            var all_met = true;
            var i: u8 = 0;
            while (i < e.*.dep_count) : (i += 1) {
                const dep = e.*.deps[i];
                if (self.entries.get(dep.entry_id)) |dep_entry| {
                    if (@intFromEnum(dep_entry.state) < @intFromEnum(dep.required_state)) {
                        if (dep.is_hard) {
                            all_met = false;
                            break;
                        }
                        // Soft dep: generate warning signal but don't block
                    }
                } else {
                    // Dep entry not found — treat as failed
                    if (dep.is_hard) {
                        all_met = false;
                        break;
                    }
                }
            }

            if (all_met) {
                self.enqueue_transition(e.*.id, .pending, .activating, .dependency);
            }
        }
    }

    fn dispatch_hooks(self: *Engine) void {
        if (self.hook_callback == null) return;

        var hooks_fired: u32 = 0;
        for (self.transition_plan.items) |t| {
            if (hooks_fired >= self.config.max_hooks_per_tick) break;

            if (self.entries.get(t.entry_id)) |e| {
                var i: u8 = 0;
                while (i < e.hook_count) : (i += 1) {
                    const hook = e.hooks[i];

                    // Pre-hooks fire on activation transitions
                    if (hook.phase == .pre and
                        (t.to_state == .activating or t.to_state == .active))
                    {
                        // Serialize entry to JSON for host
                        const json = serialize_entry(e, self.allocator) catch continue;
                        defer self.allocator.free(json);
                        self.hook_callback.?(
                            &e.id,
                            &hook,
                            json.ptr,
                            @intCast(json.len),
                        );
                        hooks_fired += 1;
                    }

                    // Post-hooks fire on deactivation transitions
                    if (hook.phase == .post and
                        (t.to_state == .deactivating or t.to_state == .completed))
                    {
                        const json = serialize_entry(e, self.allocator) catch continue;
                        defer self.allocator.free(json);
                        self.hook_callback.?(
                            &e.id,
                            &hook,
                            json.ptr,
                            @intCast(json.len),
                        );
                        hooks_fired += 1;
                    }
                }
            }
        }
    }

    fn compute_next_wake(self: *Engine, now: types.Timestamp) types.Timestamp {
        var earliest = now + self.config.heartbeat_ms; // default: heartbeat

        var it = self.entries.valueIterator();
        while (it.next()) |e| {
            if (e.*.state == .dormant and e.*.activation_trigger == .time) {
                const t = e.*.activation_time.at;
                if (t > now and t < earliest) earliest = t;
                const ws = e.*.activation_time.window_start;
                if (ws > now and ws < earliest) earliest = ws;
            }
            if (e.*.state == .active and e.*.deactivation_trigger == .time) {
                const t = e.*.deactivation_time.at;
                if (t > now and t < earliest) earliest = t;
            }
        }

        return earliest;
    }

    // Helper
    fn enqueue_transition(
        self: *Engine,
        id: types.EntryId,
        from: types.EntryState,
        to: types.EntryState,
        kind: types.TriggerKind,
    ) void {
        if (!types.valid_transition(from, to)) return;
        self.transition_plan.append(.{
            .entry_id = id,
            .from_state = from,
            .to_state = to,
            .trigger_kind = kind,
            .hooks_to_fire = std.ArrayList(entry_mod.Hook).init(self.allocator),
            .resolution_note = null,
        }) catch {};
    }
};
```

### Resolution Engine (`resolution.zig`)

```zig
const types = @import("types.zig");
const entry_mod = @import("entry.zig");

/// Two entries conflict if they overlap in time AND share a category.
fn entries_conflict(a: *const entry_mod.Entry, b: *const entry_mod.Entry) bool {
    // Must share a category
    if (a.category_len == 0 or b.category_len == 0) return false;
    const cat_a = a.category[0..a.category_len];
    const cat_b = b.category[0..b.category_len];
    if (!std.mem.eql(u8, cat_a, cat_b)) return false;

    // Must overlap in time
    // (Use window_start/window_end or anchor +-1h as default window)
    const a_start = if (a.window_start > 0) a.window_start else a.anchor - 3600000;
    const a_end = if (a.window_end > 0) a.window_end else a.anchor + 3600000;
    const b_start = if (b.window_start > 0) b.window_start else b.anchor - 3600000;
    const b_end = if (b.window_end > 0) b.window_end else b.anchor + 3600000;

    return a_start < b_end and b_start < a_end;
}

/// Resolve conflicts across streams.
/// For each pair of conflicting active/activating entries,
/// the higher-visibility entry wins (private > internal > open).
/// Losing entries get their salience reduced (shadowed, not deleted).
pub fn resolve_conflicts(
    entries: *std.AutoHashMap(types.EntryId, *entry_mod.Entry),
    plan: *std.ArrayList(Engine.Transition),
    now: types.Timestamp,
) void {
    // Build list of entries that are active or about to be activated
    var active_list = std.ArrayList(*entry_mod.Entry).init(entries.allocator);
    defer active_list.deinit();

    var it = entries.valueIterator();
    while (it.next()) |e| {
        if (e.*.state == .active or e.*.state == .activating or e.*.state == .pending) {
            active_list.append(e.*) catch continue;
        }
    }

    // Pairwise conflict check (O(n^2) but n is small for PoC)
    for (active_list.items, 0..) |a, i| {
        for (active_list.items[i + 1 ..]) |b| {
            if (entries_conflict(a, b)) {
                // Higher visibility wins
                if (a.visibility.overrides(b.visibility)) {
                    b.salience *= 0.3; // shadowed, not removed
                } else if (b.visibility.overrides(a.visibility)) {
                    a.salience *= 0.3;
                }
                // Same visibility: both remain, agent decides
            }
        }
    }
}
```

### C ABI Exports (`main.zig`)

```zig
const std = @import("std");
const timeline = @import("timeline.zig");
const types = @import("types.zig");
const entry_mod = @import("entry.zig");
const event_mod = @import("event.zig");

var engine: ?*timeline.Engine = null;

// --- Lifecycle ---

export fn podos_init(
    heartbeat_ms: u32,
    max_entries: u32,
    log_path: [*]const u8,
    log_path_len: u32,
) callconv(.C) i32 {
    var config = timeline.EngineConfig{
        .heartbeat_ms = heartbeat_ms,
        .max_entries = max_entries,
    };
    if (log_path_len > 0 and log_path_len <= 256) {
        @memcpy(config.transition_log_path[0..log_path_len], log_path[0..log_path_len]);
        config.transition_log_path_len = @intCast(log_path_len);
    }

    engine = timeline.Engine.init(std.heap.page_allocator, config) catch return -1;
    return 0; // success
}

export fn podos_destroy() callconv(.C) void {
    if (engine) |e| {
        e.deinit();
        engine = null;
    }
}

export fn podos_start() callconv(.C) void {
    if (engine) |e| e.is_running = true;
}

export fn podos_stop() callconv(.C) void {
    if (engine) |e| e.is_running = false;
}

// --- Tick ---

export fn podos_tick() callconv(.C) i32 {
    if (engine) |e| {
        e.tick() catch return -1;
        return 0;
    }
    return -1; // not initialized
}

/// Returns milliseconds until next tick should fire.
/// The host (Python) uses this to sleep efficiently.
export fn podos_next_wake_ms() callconv(.C) i64 {
    if (engine) |e| {
        const now = types.now_ms();
        const wake = e.next_wake_at;
        if (wake <= now) return 0;
        return wake - now;
    }
    return 5000; // default heartbeat
}

// --- Entry Management ---

/// Create a new entry. Returns 0 on success, -1 on failure.
/// entry_json is a JSON-serialized entry (parsed by kernel).
export fn podos_create_entry(
    entry_json: [*]const u8,
    entry_json_len: u32,
) callconv(.C) i32 {
    if (engine) |e| {
        const json = entry_json[0..entry_json_len];
        const parsed = parse_entry_json(json, e.allocator) catch return -1;
        e.entries.put(parsed.id, parsed) catch return -1;

        // Add to DAG if it has dependencies
        if (parsed.dep_count > 0) {
            e.dag.add_entry(parsed) catch return -1;
        }

        return 0;
    }
    return -1;
}

/// Update an entry's state (manual trigger).
export fn podos_update_entry_state(
    entry_id: *const types.EntryId,
    new_state: u8,
) callconv(.C) i32 {
    if (engine) |e| {
        if (e.entries.get(entry_id.*)) |ent| {
            const target: types.EntryState = @enumFromInt(new_state);
            if (types.valid_transition(ent.state, target)) {
                ent.previous_state = ent.state;
                ent.state = target;
                ent.last_transition_at = types.now_ms();
                return 0;
            }
        }
    }
    return -1;
}

// --- Event Queue ---

/// Push an event into the queue for processing on next tick.
export fn podos_push_event(
    event_json: [*]const u8,
    event_json_len: u32,
) callconv(.C) i32 {
    if (engine) |e| {
        const json = event_json[0..event_json_len];
        const evt = parse_event_json(json, e.allocator) catch return -1;
        e.event_queue.push(evt) catch return -1;
        return 0;
    }
    return -1;
}

// --- Central State ---

/// Get the current central state as JSON.
/// Caller must free the returned buffer with podos_free_buffer.
export fn podos_get_state(
    out_ptr: *[*]const u8,
    out_len: *u32,
) callconv(.C) i32 {
    if (engine) |e| {
        const json = e.central_state.to_json(e.allocator) catch return -1;
        out_ptr.* = json.ptr;
        out_len.* = @intCast(json.len);
        return 0;
    }
    return -1;
}

export fn podos_free_buffer(ptr: [*]const u8, len: u32) callconv(.C) void {
    if (engine) |e| {
        e.allocator.free(ptr[0..len]);
    }
}

// --- Callbacks ---

export fn podos_register_hook_callback(
    cb: timeline.HookCallback,
) callconv(.C) void {
    if (engine) |e| e.hook_callback = cb;
}

export fn podos_register_state_callback(
    cb: timeline.StateCallback,
) callconv(.C) void {
    if (engine) |e| e.state_callback = cb;
}

// --- Info ---

export fn podos_tick_count() callconv(.C) u64 {
    if (engine) |e| return e.tick_count;
    return 0;
}

export fn podos_entry_count() callconv(.C) u32 {
    if (engine) |e| return @intCast(e.entries.count());
    return 0;
}
```

### Build Script (`build.zig`)

```zig
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Shared library (libpodos.dylib / libpodos.so)
    const lib = b.addSharedLibrary(.{
        .name = "podos",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    lib.linkLibC(); // for malloc if needed

    b.installArtifact(lib);

    // Static library (for embedding)
    const static_lib = b.addStaticLibrary(.{
        .name = "podos",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(static_lib);

    // Tests
    const tests = b.addTest(.{
        .root_source_file = b.path("tests/test_entry.zig"),
        .target = target,
        .optimize = optimize,
    });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run kernel tests");
    test_step.dependOn(&run_tests.step);
}
```

---

## Python FFI Bridge

### `src/timeline_bridge.py`

The bridge wraps libpodos via ctypes and runs the tick loop in a background thread.

```python
"""
Python bridge to the PodOS Zig timeline kernel (libpodos).

Loads the shared library, wraps C ABI functions, runs the tick loop
in a background thread, and dispatches hooks to the Python host layer.
"""
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass, field

# --- Load library ---

def _find_lib():
    """Find libpodos shared library."""
    kernel_dir = Path(__file__).parent.parent / "kernel" / "zig-out" / "lib"
    if sys.platform == "darwin":
        return kernel_dir / "libpodos.dylib"
    elif sys.platform == "linux":
        return kernel_dir / "libpodos.so"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


# --- Types ---

EntryId = ctypes.c_ubyte * 16
HookCallbackType = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(EntryId),           # entry_id
    ctypes.c_void_p,                    # hook ptr
    ctypes.c_char_p,                    # entry_json
    ctypes.c_uint32,                    # entry_json_len
)
StateCallbackType = ctypes.CFUNCTYPE(
    None,
    ctypes.c_char_p,                    # state_json
    ctypes.c_uint32,                    # state_json_len
)


@dataclass
class TimelineEntry:
    """Python-side entry representation."""
    id: str
    ref_type: str = "none"
    ref_uri: str = ""
    visibility: str = "private"       # "private" | "internal" | "open"
    stream_layer: str = "pod"         # "pod" | "pool" | "public"
    entry_type: str = "event"
    category: str = ""
    salience: float = 0.5
    anchor_ms: int = 0                # unix ms, 0 = unanchored
    window_start_ms: int = 0
    window_end_ms: int = 0
    activation_trigger: str = "manual"  # "time" | "event" | "manual" | ...
    activation_time_at_ms: int = 0
    deactivation_trigger: str = "manual"
    deactivation_time_at_ms: int = 0
    hooks: list = field(default_factory=list)  # [{phase, action_kind, prompt, ...}]
    depends_on: list = field(default_factory=list)  # [{entry_id, required_state, is_hard}]
    creator_id: str = ""
    is_shadow: bool = False
    shadow_source_pod: str = ""
    shadow_source_entry_id: str = ""

    def to_kernel_json(self) -> bytes:
        """Serialize to JSON that the Zig kernel can parse."""
        return json.dumps({
            "id": self.id,
            "ref_type": self.ref_type,
            "ref_uri": self.ref_uri,
            "visibility": self.visibility,
            "stream_layer": self.stream_layer,
            "entry_type": self.entry_type,
            "category": self.category,
            "salience": self.salience,
            "anchor_ms": self.anchor_ms,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "activation_trigger": self.activation_trigger,
            "activation_time_at_ms": self.activation_time_at_ms,
            "deactivation_trigger": self.deactivation_trigger,
            "deactivation_time_at_ms": self.deactivation_time_at_ms,
            "hooks": self.hooks,
            "depends_on": self.depends_on,
            "creator_id": self.creator_id,
            "is_shadow": self.is_shadow,
            "shadow_source_pod": self.shadow_source_pod,
            "shadow_source_entry_id": self.shadow_source_entry_id,
        }).encode("utf-8")


@dataclass
class TimelineEvent:
    """An event to push into the kernel's queue."""
    source: str       # "system"|"user"|"agent"|"integration"|"federation"|"public_stream"
    event_type: str   # hierarchical: "email.received", "capsule.updated", etc.
    payload: dict     # source-specific data
    from_pattern: str = ""  # for event trigger matching

    def to_kernel_json(self) -> bytes:
        return json.dumps({
            "source": self.source,
            "type": self.event_type,
            "payload": self.payload,
            "from": self.from_pattern,
        }).encode("utf-8")


class PodOSKernel:
    """Python wrapper around the Zig timeline kernel."""

    def __init__(
        self,
        heartbeat_ms: int = 5000,
        max_entries: int = 10000,
        log_path: str = "",
    ):
        self._lib_path = _find_lib()
        if not self._lib_path.exists():
            raise FileNotFoundError(
                f"libpodos not found at {self._lib_path}. "
                "Run: cd kernel && zig build"
            )

        self._lib = ctypes.CDLL(str(self._lib_path))
        self._setup_functions()

        # Initialize kernel
        log_bytes = log_path.encode("utf-8") if log_path else b""
        rc = self._lib.podos_init(
            heartbeat_ms, max_entries, log_bytes, len(log_bytes)
        )
        if rc != 0:
            raise RuntimeError("Failed to initialize PodOS kernel")

        # Hook dispatch registry
        self._hook_handlers: dict[str, Callable] = {}
        self._state_subscribers: list[Callable] = []

        # Register C callbacks
        self._hook_cb = HookCallbackType(self._on_hook)
        self._state_cb = StateCallbackType(self._on_state_change)
        self._lib.podos_register_hook_callback(self._hook_cb)
        self._lib.podos_register_state_callback(self._state_cb)

        # Tick thread
        self._tick_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Latest state cache
        self.current_state: dict = {}

    def _setup_functions(self):
        """Declare C function signatures."""
        lib = self._lib

        lib.podos_init.argtypes = [ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_char_p, ctypes.c_uint32]
        lib.podos_init.restype = ctypes.c_int32

        lib.podos_destroy.argtypes = []
        lib.podos_destroy.restype = None

        lib.podos_start.argtypes = []
        lib.podos_start.restype = None

        lib.podos_stop.argtypes = []
        lib.podos_stop.restype = None

        lib.podos_tick.argtypes = []
        lib.podos_tick.restype = ctypes.c_int32

        lib.podos_next_wake_ms.argtypes = []
        lib.podos_next_wake_ms.restype = ctypes.c_int64

        lib.podos_create_entry.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.podos_create_entry.restype = ctypes.c_int32

        lib.podos_push_event.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.podos_push_event.restype = ctypes.c_int32

        lib.podos_tick_count.argtypes = []
        lib.podos_tick_count.restype = ctypes.c_uint64

        lib.podos_entry_count.argtypes = []
        lib.podos_entry_count.restype = ctypes.c_uint32

    def start(self):
        """Start the tick loop in a background thread."""
        self._lib.podos_start()
        self._stop_event.clear()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="podos-tick"
        )
        self._tick_thread.start()

    def stop(self):
        """Stop the tick loop."""
        self._stop_event.set()
        self._lib.podos_stop()
        if self._tick_thread:
            self._tick_thread.join(timeout=10)

    def destroy(self):
        """Tear down the kernel."""
        self.stop()
        self._lib.podos_destroy()

    def _tick_loop(self):
        """Background tick loop. Sleeps adaptively between ticks."""
        while not self._stop_event.is_set():
            rc = self._lib.podos_tick()
            if rc != 0:
                time.sleep(1)  # back off on error
                continue

            # Sleep until next wake time
            wait_ms = self._lib.podos_next_wake_ms()
            if wait_ms > 0:
                self._stop_event.wait(timeout=wait_ms / 1000.0)

    def create_entry(self, entry: TimelineEntry) -> bool:
        """Add an entry to the kernel."""
        data = entry.to_kernel_json()
        return self._lib.podos_create_entry(data, len(data)) == 0

    def push_event(self, event: TimelineEvent) -> bool:
        """Push an event into the kernel's queue."""
        data = event.to_kernel_json()
        return self._lib.podos_push_event(data, len(data)) == 0

    def tick_count(self) -> int:
        return self._lib.podos_tick_count()

    def entry_count(self) -> int:
        return self._lib.podos_entry_count()

    # --- Hook handlers ---

    def register_hook_handler(self, action_kind: str, handler: Callable):
        """Register a Python function to handle a specific hook type."""
        self._hook_handlers[action_kind] = handler

    def on_state_change(self, callback: Callable):
        """Register a callback for central state changes."""
        self._state_subscribers.append(callback)

    def _on_hook(self, entry_id_ptr, hook_ptr, entry_json, entry_json_len):
        """C callback — dispatches to registered Python handlers."""
        try:
            entry_data = json.loads(entry_json[:entry_json_len])
            # Parse hook action kind from the hook struct
            # For PoC, we pass action_kind in the entry JSON
            action_kind = entry_data.get("_hook_action_kind", "agent_task")
            handler = self._hook_handlers.get(action_kind)
            if handler:
                # Run handler in a separate thread to avoid blocking tick
                threading.Thread(
                    target=handler,
                    args=(entry_data,),
                    daemon=True,
                ).start()
        except Exception as e:
            print(f"[PodOS] Hook dispatch error: {e}")

    def _on_state_change(self, state_json, state_json_len):
        """C callback — notifies Python subscribers of state changes."""
        try:
            state = json.loads(state_json[:state_json_len])
            self.current_state = state
            for cb in self._state_subscribers:
                cb(state)
        except Exception as e:
            print(f"[PodOS] State callback error: {e}")


# --- Singleton for the pod ---

_kernel: Optional[PodOSKernel] = None

def get_kernel() -> Optional[PodOSKernel]:
    return _kernel

def init_kernel(**kwargs) -> PodOSKernel:
    global _kernel
    _kernel = PodOSKernel(**kwargs)
    return _kernel
```

---

## Edge Cases & Solutions

### EC-1: Pod Goes Offline (Phone Loses Signal)

**Problem**: Pod disconnects. Pool timeline entries arrive while offline. Some entries activated AND deactivated — owner never saw them.

**Solution**:
- Federation sync is event-sourced. Missed events buffer on the sending pod.
- On reconnect, receiving pod pulls missed events ordered by logical clock.
- Engine fast-forwards through buffered events in catch-up ticks.
- Entries that activated and deactivated offline appear in `transition_log` with flag `missed_while_offline=True`.
- Agent generates a catch-up summary: "While you were offline: 3 pool entries resolved, 1 needs your attention."

**Implementation**:
- `federation.py`: `pull_missed_timeline_events(peer_url, since_tick)` → returns ordered event list.
- `timeline_bridge.py`: `replay_events(events)` pushes each into kernel queue, runs catch-up ticks.
- Kernel: `podos_push_event` with `timestamp` field, engine processes in causal order.

### EC-2: Dangling Reference (Capsule Deleted)

**Problem**: Entry points to `capsule://abc-123`, but capsule was archived/deleted.

**Solution**:
- Ref resolution happens in the Python host layer (not kernel). Host returns `ref_unavailable` status.
- Kernel transitions entry to `failed` state with reason `ref_unavailable`.
- Agent hook on failure: "Referenced capsule no longer available. Archive this entry or find alternative?"

**Implementation**:
- `timeline_bridge.py`: Hook handler checks ref before agent task. If capsule missing, push `ref_unavailable` event to kernel.
- Kernel: On `ref_unavailable` event matching an active entry, transition to `failed`.

### EC-3: Privacy Leak via Pool Sync

**Problem**: User accidentally marks private entry as INTERNAL. It syncs to work pool. Boss sees it.

**Solution (two safeguards)**:
1. **Visibility upgrade confirmation**: When entry visibility changes from `private` to `internal` or `open`, kernel sets `needs_confirmation=True`. Entry stays in current state until confirmed via `podos_confirm_visibility_upgrade(entry_id)`. Not auto-synced until confirmed.
2. **Category-scoped pool filtering**: Pools define `shared_categories`. Only entries whose category matches the pool's filter are synced. "Career" category entry won't sync to "work-projects" pool even if INTERNAL.

**Implementation**:
- Kernel: `needs_confirmation` flag in Entry struct. Transition blocked while true.
- `routes/timeline.py`: `POST /api/timeline/entries/{id}/confirm-visibility` endpoint.
- `federation.py`: `sync_timeline_to_pool()` checks entry.category against pool.shared_categories.
- Citadel: Scan entry content before pool sync for sensitive patterns (reuse existing `scan_output`).

### EC-4: Clock Skew Between Pods

**Problem**: Alice's pod clock is 2 minutes ahead of Bob's. Time triggers fire at different moments.

**Solution**:
- **Local entries**: Always use local clock. Your pod, your time.
- **Pool/public entries with time triggers**: Use UTC anchor explicitly. Pool entries default to UTC.
- **Sync events**: Carry originating pod's timestamp as metadata. Receiving pod processes immediately on receipt (trigger already evaluated by sender).
- **Logical clocks**: All sync messages include a Lamport timestamp. Causal ordering is preserved regardless of wall clock differences.

**Implementation**:
- Entry struct: `anchor` is always UTC milliseconds.
- Sync protocol: Each message includes `{logical_clock: u64, wall_clock_ms: i64, pod_id: string}`.
- `timeline_bridge.py`: `push_event` includes both logical and wall clock.
- Resolution: If two events have same logical clock, use pod_id as tiebreaker (deterministic ordering).

### EC-5: Cascade Storm (Infinite Hook Chains)

**Problem**: Entry A's hook creates Entry B, whose hook creates Entry C, whose hook modifies Entry A.

**Solution (three layers of protection)**:
1. **Tick-tock isolation**: Hooks that create/modify entries produce events for the NEXT tick, never the current one. Same-tick cascades are impossible by construction.
2. **Cascade depth counter**: Each entry tracks `cascade_depth`. If a hook creates a new entry, the child's depth = parent's depth + 1. When depth exceeds `max_cascade_depth` (default 10), creation is rejected.
3. **Per-tick hook limit**: `max_hooks_per_tick` (default 32). If exceeded, remaining hooks are deferred to next tick with a `hooks_throttled` signal in central state.

**Implementation**:
- Kernel: `cascade_depth` field in Entry. `dispatch_hooks()` checks depth before firing.
- Kernel: Hook counter in `tick()`. Stops dispatching at limit.
- Central state: `signals` array includes `{severity: "warning", message: "Hook chain depth limit reached"}` when triggered.

### EC-6: Pool Member Removal (Contact Blocked)

**Problem**: Bob leaves "Project Team" pool. His pod has shadow entries from that pool.

**Solution**:
- On pool leave: all shadow entries from that pool's members are transitioned to `archived` with reason `pool_membership_ended`.
- Pod entries depending on those shadows get a `dependency_unavailable` signal.
- Agent generates: "Bob left Project Team. 3 of your entries depended on shared milestones. Review?"
- Mirrors existing ghost user cleanup — same principle for timeline entries.

**Implementation**:
- `routes/networks.py`: On member removal, call `timeline_bridge.archive_shadows_for_pool(pool_id)`.
- `timeline_bridge.py`: Iterates kernel entries, pushes `archive` events for matching shadows.
- `federation.py`: On `cleanup_ghosts_for_pod()`, also cleanup shadow entries from that pod.

### EC-7: Registry Goes Down (Internet Down)

**Problem**: Public stream host unreachable. Pods can't publish OPEN entries or receive public events.

**Solution**:
- Public stream subscription has a `state: "connected"|"disconnected"|"error"` field.
- On disconnect: local and pool operations continue unaffected.
- OPEN entries queue in a `pending_publish` buffer.
- On reconnect: buffered entries sync. Missed public events are pulled with `since` parameter.
- Central state signal: `{severity: "info", message: "Public stream disconnected. Local operations unaffected."}`.

**Implementation**:
- `timeline_bridge.py`: `PublicStreamSubscription` class with reconnect logic.
- `federation.py`: `publish_to_registry_timeline(entry)` queues on failure, retries on reconnect.
- Registry: `GET /api/timeline/stream?since={tick}` returns events since given tick for catch-up.

### EC-8: Large Backlog After Long Offline Period

**Problem**: Pod was offline for a week. 500+ buffered pool events need processing. Fast-forward ticks consume resources.

**Solution**:
- **Batch catch-up mode**: Instead of processing each event in a separate tick, the engine enters catch-up mode where it processes events in batches of 100 per tick, skipping adaptive sleep.
- **Expired entry pruning**: Events for entries whose window_end has already passed are auto-archived during catch-up (no need to activate then immediately deactivate).
- **Catch-up summary**: Agent generates a single summary of all missed activity instead of individual notifications.

**Implementation**:
- Kernel: `podos_enter_catchup_mode()` / `podos_exit_catchup_mode()` — increases `max_events_per_tick` temporarily.
- `timeline_bridge.py`: Detects backlog size, enters catchup mode if > 50 events.
- `agents.py`: `handle_catchup_summary(missed_transitions)` — single LLM call summarizing all missed activity.

### EC-9: Conflicting Shadow Updates (Split-Brain Pool)

**Problem**: Two pods modify the same shared pool entry concurrently (both were online but sync was delayed).

**Solution**:
- **Last-writer-wins with logical clock**: Each modification increments the entry's logical clock. The modification with the higher clock wins.
- **Conflict detection**: If a pod receives a shadow update with a logical clock that's NOT strictly greater than the local shadow's clock, it's a conflict.
- **Conflict signal**: Central state gets `{severity: "attention", message: "Conflicting update on pool entry X. Review needed."}`.
- **Pool owner resolution**: Pool owner's version always wins in case of true conflict. Non-owners get their version reverted.

**Implementation**:
- Entry struct: `logical_clock: u64` field, incremented on each mutation.
- Sync protocol: Includes entry's logical clock.
- `resolution.zig`: `resolve_shadow_conflict(local_clock, remote_clock, is_pool_owner)`.

### EC-10: Agent Task Hook Timeout (LLM Down or Slow)

**Problem**: `agent_task` hook fires, but LLM call takes 30+ seconds or fails entirely.

**Solution**:
- **Timeout**: Each hook has `timeout_ms` (default 30s). If handler doesn't complete in time, hook is marked failed.
- **Retry**: Configurable `retry_count` and `retry_backoff_ms`. Failed hooks retry with exponential backoff.
- **Entry stays in `activating`**: Pre-hooks that haven't completed keep the entry in `activating`. It doesn't transition to `active` until hooks complete or exhaust retries.
- **Fallback**: After all retries fail, entry transitions to `failed` with reason `hook_timeout`. Agent generates a degraded response from cached data if possible.

**Implementation**:
- `timeline_bridge.py`: Hook handler thread has timeout. On timeout, pushes `hook_failed` event to kernel.
- Kernel: Tracks hook completion status per entry. Entry in `activating` state with pending hooks doesn't advance until hooks resolve.
- `agents.py`: `handle_agent_task_with_timeout(entry, timeout_ms)` — wraps LLM call with async timeout.

---

## Database Schema

New tables in SQLite alongside existing TrustMesh models. The kernel manages entries in memory; SQLite provides persistence for restart recovery and history queries.

### `timeline_entries` (persistence mirror of kernel state)

```sql
CREATE TABLE timeline_entries (
    id TEXT PRIMARY KEY,                    -- UUID
    timeline_id TEXT NOT NULL,              -- which timeline (main, pool, branch)
    creator_id TEXT NOT NULL,               -- user or agent UUID

    -- Reference
    ref_type TEXT NOT NULL DEFAULT 'none',  -- capsule|saas|storage|pool|...
    ref_uri TEXT DEFAULT '',

    -- State
    state TEXT NOT NULL DEFAULT 'dormant',
    previous_state TEXT DEFAULT '',

    -- Time binding
    anchor_ms INTEGER DEFAULT 0,
    window_start_ms INTEGER DEFAULT 0,
    window_end_ms INTEGER DEFAULT 0,

    -- Triggers (JSON)
    activation_trigger TEXT NOT NULL DEFAULT 'manual',
    activation_config TEXT DEFAULT '{}',     -- JSON trigger config
    deactivation_trigger TEXT NOT NULL DEFAULT 'manual',
    deactivation_config TEXT DEFAULT '{}',

    -- Dependencies (JSON array)
    depends_on TEXT DEFAULT '[]',

    -- Hooks (JSON array)
    hooks TEXT DEFAULT '[]',

    -- Visibility
    visibility TEXT NOT NULL DEFAULT 'private',
    stream_layer TEXT NOT NULL DEFAULT 'pod',  -- pod|pool|public

    -- Classification
    entry_type TEXT NOT NULL DEFAULT 'event',
    category TEXT DEFAULT '',
    salience REAL DEFAULT 0.5,
    tags TEXT DEFAULT '[]',                 -- JSON array

    -- Shadow tracking
    is_shadow BOOLEAN DEFAULT FALSE,
    shadow_source_pod TEXT DEFAULT '',
    shadow_source_entry_id TEXT DEFAULT '',

    -- Sync
    logical_clock INTEGER DEFAULT 0,
    needs_confirmation BOOLEAN DEFAULT FALSE,
    cascade_depth INTEGER DEFAULT 0,

    -- Metadata
    created_at TEXT NOT NULL,
    last_transition_at TEXT,

    -- Indexes will be created below
    FOREIGN KEY (creator_id) REFERENCES users(id)
);

CREATE INDEX idx_timeline_entries_state ON timeline_entries(state);
CREATE INDEX idx_timeline_entries_timeline ON timeline_entries(timeline_id);
CREATE INDEX idx_timeline_entries_visibility ON timeline_entries(visibility);
CREATE INDEX idx_timeline_entries_category ON timeline_entries(category);
CREATE INDEX idx_timeline_entries_anchor ON timeline_entries(anchor_ms);
CREATE INDEX idx_timeline_entries_shadow ON timeline_entries(is_shadow, shadow_source_pod);
```

### `timeline_transitions` (append-only audit log)

```sql
CREATE TABLE timeline_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    tick_number INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    resolution_note TEXT DEFAULT '',
    missed_while_offline BOOLEAN DEFAULT FALSE,

    FOREIGN KEY (entry_id) REFERENCES timeline_entries(id)
);

CREATE INDEX idx_transitions_entry ON timeline_transitions(entry_id);
CREATE INDEX idx_transitions_tick ON timeline_transitions(tick_number);
```

### `timeline_subscriptions` (pool and public stream subscriptions)

```sql
CREATE TABLE timeline_subscriptions (
    id TEXT PRIMARY KEY,
    stream_type TEXT NOT NULL,              -- 'pool' | 'public'
    stream_url TEXT NOT NULL,               -- pool sync URL or registry URL
    stream_name TEXT DEFAULT '',            -- human-readable label
    filter_categories TEXT DEFAULT '[]',    -- JSON array of categories to include
    filter_entry_types TEXT DEFAULT '[]',   -- JSON array of entry types
    status TEXT NOT NULL DEFAULT 'active',  -- active|paused|disconnected|error
    last_sync_tick INTEGER DEFAULT 0,
    last_sync_at TEXT,
    created_at TEXT NOT NULL,

    UNIQUE(stream_type, stream_url)
);
```

### `timelines` (timeline metadata — main, branches, pool-owned)

```sql
CREATE TABLE timelines (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,                 -- user ID or pool ID
    name TEXT NOT NULL DEFAULT 'main',
    timeline_type TEXT NOT NULL DEFAULT 'main',  -- main|branch|pool_shared
    parent_timeline_id TEXT,                -- for branches
    branch_policy TEXT DEFAULT '{}',        -- JSON: side_effects, auto_merge, etc.
    visibility TEXT NOT NULL DEFAULT 'private',
    created_at TEXT NOT NULL,

    FOREIGN KEY (owner_id) REFERENCES users(id)
);
```

---

## API Endpoints

### New: `src/routes/timeline.py`

```
Timeline Entry CRUD:
  GET    /api/timeline/entries                  List entries (filterable by state, type, category, visibility)
  POST   /api/timeline/entries                  Create entry
  GET    /api/timeline/entries/{id}             Get entry detail
  PATCH  /api/timeline/entries/{id}             Update entry (state, visibility, salience, hooks)
  DELETE /api/timeline/entries/{id}             Delete entry (transition to deleted state)
  POST   /api/timeline/entries/{id}/confirm     Confirm visibility upgrade

Central State:
  GET    /api/timeline/state                    Get current central state (from kernel)
  GET    /api/timeline/state/stream             SSE stream of state deltas

Timeline Management:
  GET    /api/timeline/timelines                List timelines (main, branches, pool)
  POST   /api/timeline/timelines                Create branch
  POST   /api/timeline/timelines/{id}/merge     Merge branch to main
  DELETE /api/timeline/timelines/{id}           Discard branch

Subscriptions:
  GET    /api/timeline/subscriptions            List stream subscriptions
  POST   /api/timeline/subscriptions            Subscribe to pool/public stream
  DELETE /api/timeline/subscriptions/{id}       Unsubscribe

Sync (federation):
  POST   /api/timeline/sync                     Receive timeline events from peers
  GET    /api/timeline/sync/events              Pull events since tick (for catch-up)

Engine Info:
  GET    /api/timeline/engine                   Kernel status (tick count, entry count, uptime)
```

### Modified Existing Endpoints

```
POST /api/pod/pool-sync
  → After pool formation, also create timeline_subscription for the pool.
  → Create shared timeline for the pool.

DELETE /api/pod/peers/{id}
  → Also archive shadow entries from that peer.
  → Also remove timeline subscriptions for that peer's pools.

POST /api/pod/query
  → Include requester's public timeline state in query context
    (so target pod's agent knows "what the requester has active").

GET /api/pod
  → Include timeline engine status in pod info response.
  → Include public timeline entry count.
```

### Registry Extensions

```
Public Timeline Stream:
  GET    /api/timeline/stream                   SSE stream of public entries
  GET    /api/timeline/entries                   List public entries (paginated)
  POST   /api/timeline/entries                   Publish entry to public stream (from pods)
  GET    /api/timeline/entries?since={tick}      Pull entries since tick (for catch-up)
```

---

## CLI Commands

### New: `trustmesh timeline` subcommand group

```
trustmesh timeline
├── list [--state STATE] [--type TYPE] [--category CAT] [--stream LAYER]
│     List timeline entries with filters.
│     Example: trustmesh timeline list --state active --category health
│
├── add --type TYPE [--ref-type RT] [--ref-uri URI] [--category CAT]
│       [--visibility VIS] [--anchor TIME] [--window-start TIME]
│       [--window-end TIME] [--activate-at TIME] [--deactivate-at TIME]
│       [--hook-prompt PROMPT] [--depends-on ENTRY_ID] [--salience FLOAT]
│     Create a new timeline entry.
│     Example: trustmesh timeline add --type reminder --category health \
│              --activate-at "2026-03-05T14:00:00" \
│              --hook-prompt "Review Sarah's medications before appointment" \
│              --ref-type capsule --ref-uri "capsule://medication-list"
│
├── get ENTRY_ID
│     Show full entry detail including state, hooks, deps, transitions.
│
├── update ENTRY_ID [--state STATE] [--visibility VIS] [--salience FLOAT]
│     Update entry fields.
│     Example: trustmesh timeline update abc-123 --state archived
│
├── confirm ENTRY_ID
│     Confirm visibility upgrade (private→internal or internal→open).
│
├── delete ENTRY_ID
│     Delete an entry.
│
├── state
│     Show current central state: active entries, upcoming, pending, signals.
│     Rich table output with color-coded states and priority indicators.
│
├── watch
│     Live-stream central state changes (updates every tick).
│     Like `watch` command but for timeline state.
│
├── subscribe STREAM_URL [--type pool|public] [--categories CAT,CAT,...]
│     Subscribe to a pool or public timeline stream.
│     Example: trustmesh timeline subscribe http://localhost:8100/api/timeline \
│              --type public --categories health,local
│
├── unsubscribe SUBSCRIPTION_ID
│     Remove a stream subscription.
│
├── subscriptions
│     List active stream subscriptions and their status.
│
├── engine
│     Show kernel status: tick count, entry count, uptime, next wake.
│
├── history [--entry-id ID] [--since TIME] [--limit N]
│     Show transition history (audit log).
│
├── branch create --name NAME [--from TIMELINE_ID]
│     Create a branch timeline.
│
├── branch list
│     List all branches.
│
├── branch merge BRANCH_ID
│     Merge branch entries into main timeline.
│
└── branch discard BRANCH_ID
      Archive and remove a branch.
```

---

## UI Components

### 1. Timeline View (`TimelineView.tsx`)

Main timeline display. Replaces or augments the existing dashboard.

```
┌──────────────────────────────────────────────────────────────┐
│  My Timeline                          Engine: ●  Tick #4,521 │
│  ─────────────────────────────────────────────────────────── │
│                                                              │
│  ┌─ ACTIVE ─────────────────────────────────────────────┐   │
│  │                                                       │   │
│  │  ● Morning health check          [PRIVATE] health     │   │
│  │    ref: capsule://medication-schedule                  │   │
│  │    activated 2h ago · deactivates at 8:00 AM          │   │
│  │                                                       │   │
│  │  ● Project deadline review        [INTERNAL] work     │   │
│  │    ref: pool://techcorp-team/milestone-q1              │   │
│  │    from: TechCorp PM Team pool · salience: 0.8        │   │
│  │                                                       │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ UPCOMING ───────────────────────────────────────────┐   │
│  │                                                       │   │
│  │  ○ Mom visiting this weekend      in 2 days           │   │
│  │    pre-hook: "Prepare for visit" fires tomorrow       │   │
│  │                                                       │   │
│  │  ○ Flu checkup                    next week           │   │
│  │    depends on: "Insurance verified" (pending)         │   │
│  │                                                       │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ SIGNALS ────────────────────────────────────────────┐   │
│  │  ⚠  3 health entries expiring this week              │   │
│  │  ℹ  Public stream: Flu season advisory active         │   │
│  │  ℹ  Branch "vacation-plan" has 2 unmerged entries     │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  [+ Add Entry]  [Subscriptions]  [Branches]  [History]      │
└──────────────────────────────────────────────────────────────┘
```

### 2. Entry Card (`EntryCard.tsx`)

Individual entry display with state badge, visibility indicator, and actions.

```
┌─────────────────────────────────────────────────────────┐
│  ● Morning health check                                 │
│  ┌──────┐ ┌─────────┐ ┌────────┐                       │
│  │ACTIVE│ │ PRIVATE  │ │ health │                       │
│  └──────┘ └─────────┘ └────────┘                       │
│                                                         │
│  Type: reminder    Salience: ●●●●○ (0.8)              │
│  Ref: capsule://medication-schedule                     │
│  Stream: pod (local)                                    │
│                                                         │
│  Time: 6:00 AM - 8:00 AM daily                         │
│  Hooks:                                                 │
│    pre: agent_task — "Review medication schedule..."     │
│    post: notify — "Morning check complete"              │
│                                                         │
│  Transitions:                                           │
│    dormant → pending    (time trigger)     6:00:00 AM   │
│    pending → activating (no deps)          6:00:01 AM   │
│    activating → active  (hooks complete)   6:00:03 AM   │
│                                                         │
│  [Archive]  [Edit]  [Change Visibility ▾]               │
└─────────────────────────────────────────────────────────┘
```

### 3. Central State Dashboard (`CentralState.tsx`)

Live dashboard showing the kernel's computed state. Updates via SSE.

```
┌──────────────────────────────────────────────────────────┐
│  Pod State                            ● Live (Tick #4521)│
│  ────────────────────────────────────────────────────────│
│                                                          │
│  Streams:                                                │
│  ┌─ POD ─────────────────┐  Active: 5  Pending: 2      │
│  ┌─ POOL ────────────────┐  Active: 3  Shadows: 8      │
│  │  Family Health Team    │                              │
│  │  TechCorp PM Team      │                              │
│  ┌─ PUBLIC ──────────────┐  Subscribed  Events: 12      │
│  │  Registry stream       │  Status: connected           │
│                                                          │
│  Resolution: 2 conflicts resolved (private won)          │
│  Hooks fired this session: 14                            │
│  Agent tasks dispatched: 6                               │
│  Next wake: 45s (time trigger on "daily-review")         │
└──────────────────────────────────────────────────────────┘
```

### 4. Stream Subscriptions Manager (`StreamSubscriptions.tsx`)

Manage pool and public stream subscriptions.

```
┌──────────────────────────────────────────────────────────┐
│  Stream Subscriptions                                     │
│  ────────────────────────────────────────────────────────│
│                                                          │
│  ● Public Registry Stream                                │
│    URL: http://localhost:8100/api/timeline/stream         │
│    Categories: health, local, emergency                   │
│    Status: ● connected  Last sync: 2m ago                │
│    [Pause] [Edit Filters] [Unsubscribe]                  │
│                                                          │
│  ● Family Health Team (pool)                             │
│    Synced via: peer pod connection                        │
│    Categories: health, family                             │
│    Status: ● connected  Shadows: 5 entries               │
│    [Pause] [View Pool Timeline]                          │
│                                                          │
│  ○ TechCorp PM Team (pool)                               │
│    Status: ○ disconnected (peer offline)                  │
│    Last sync: 3h ago  Shadows: 3 entries (stale)         │
│    [Reconnect] [Archive Shadows]                         │
│                                                          │
│  [+ Subscribe to Stream]                                 │
└──────────────────────────────────────────────────────────┘
```

### 5. Add Entry Form (`AddEntryForm.tsx`)

```
┌──────────────────────────────────────────────────────────┐
│  New Timeline Entry                                       │
│  ────────────────────────────────────────────────────────│
│                                                          │
│  Type:       [▾ reminder]                                │
│  Category:   [▾ health  ]                                │
│  Visibility: [▾ private ] ← shows confirmation warning    │
│                              if internal/open selected    │
│                                                          │
│  Reference (optional):                                    │
│  Ref type:   [▾ capsule ]                                │
│  Ref URI:    [capsule://medication-list              ]   │
│                                                          │
│  Time Binding:                                            │
│  Anchor:     [2026-03-05T14:00     ]                     │
│  Window:     [          ] to [          ]                │
│                                                          │
│  Activation:                                              │
│  Trigger:    [▾ time    ]                                │
│  At:         [2026-03-05T12:00     ] (2h before anchor)  │
│                                                          │
│  Hooks:                                                   │
│  [+ Add Hook]                                            │
│  ┌─ pre-hook ──────────────────────────────────────┐     │
│  │  Action: [▾ agent_task]                          │     │
│  │  Prompt: [Review medications before appointment  │     │
│  │           and prepare questions for Dr. Chen    ]│     │
│  │  Timeout: [30s]  Retries: [2]                    │     │
│  └──────────────────────────────────────────────────┘     │
│                                                          │
│  Dependencies:                                            │
│  [+ Add Dependency]                                      │
│  ┌─ depends on ────────────────────────────────────┐     │
│  │  Entry: [▾ "Insurance verified"   ]              │     │
│  │  Required state: [▾ completed]  Hard: [✓]        │     │
│  └──────────────────────────────────────────────────┘     │
│                                                          │
│  Salience:  ●●●●○  [0.8]                                │
│                                                          │
│  [Cancel]                                [Create Entry]  │
└──────────────────────────────────────────────────────────┘
```

---

## Pod-to-Pod Interactivity

### Timeline Sync Protocol

When two pods are in a pool, their timelines sync through the existing federation layer, extended with timeline events.

```
POOL FORMATION (extends existing pool-sync):

  1. Orchestrator (or manual) creates pool between Pod A and Pod B.
  2. Each pod creates a timeline_subscription for the pool.
  3. Each pod creates a shared timeline (timeline_type: "pool_shared").
  4. INTERNAL entries on each pod are synced to the shared timeline.

ONGOING SYNC:

  Pod A creates/modifies an INTERNAL entry:
    → POST /api/timeline/sync on Pod B
    → Payload: {
        "source_pod": "http://localhost:8001",
        "source_entry_id": "abc-123",
        "event_type": "entry_created" | "entry_updated" | "entry_state_changed",
        "entry_data": { ... serialized entry ... },
        "logical_clock": 42,
        "pool_id": "pool-xyz"
      }
    → Pod B validates: is source_pod a peer? Is pool_id a shared pool?
    → Pod B creates/updates shadow entry on its timeline.
    → Pod B's kernel processes shadow on next tick.

CATCH-UP (after offline period):

  Pod A reconnects to Pod B:
    → GET /api/timeline/sync/events?since_tick=4000&pool_id=pool-xyz
    → Pod B returns all events since tick 4000 for that pool.
    → Pod A replays events in order.
```

### Shadow Entry Lifecycle

```
Remote entry created on Pod A (INTERNAL):
  → Sync to Pod B
  → Pod B creates shadow entry:
      is_shadow: true
      shadow_source_pod: "http://localhost:8001"
      shadow_source_entry_id: "abc-123"
      stream_layer: pool
      visibility: internal
  → Shadow mirrors source state (dormant/active/completed)
  → Shadow's hooks are NOT copied (only the source fires hooks)
  → Pod B's entries CAN depend on shadows (cross-pod dependencies)
  → Pod B's agent SEES shadows in central state

Remote entry deactivated on Pod A:
  → Sync event: entry_state_changed to "completed"
  → Pod B updates shadow to "completed"
  → Pod B entries depending on shadow may now advance

Remote entry deleted on Pod A:
  → Sync event: entry_deleted
  → Pod B archives shadow (not deleted — keeps audit trail)
  → Pod B entries depending on shadow get dependency_unavailable signal
```

---

## Public Stream (Registry)

### Registry Timeline Extension

The registry becomes a timeline host. It maintains a public timeline that any pod can subscribe to.

```
Registry (trustmesh-registry/):

  New files:
    lib/timeline.ts        ← Public timeline management
    app/api/timeline/
      stream/route.ts      ← SSE endpoint
      entries/route.ts     ← CRUD for public entries
      entries/[id]/route.ts ← Individual entry operations

  Database extension:
    CREATE TABLE public_timeline_entries (
      id TEXT PRIMARY KEY,
      publisher_pod_url TEXT NOT NULL,
      publisher_did TEXT NOT NULL,
      entry_type TEXT NOT NULL,
      category TEXT DEFAULT '',
      tags TEXT DEFAULT '[]',            -- JSON array of free-form strings for filtering
      content TEXT DEFAULT '',           -- entry metadata (not vault data)
      anchor_ms INTEGER DEFAULT 0,
      window_start_ms INTEGER DEFAULT 0,
      window_end_ms INTEGER DEFAULT 0,
      visibility TEXT DEFAULT 'open',    -- always open for public stream
      logical_clock INTEGER DEFAULT 0,
      created_at TEXT NOT NULL,
      expires_at TEXT                    -- TTL for time-bound entries
    );

  SSE Stream:
    GET /api/timeline/stream
    → Returns server-sent events:
      data: {"event_type": "entry_created", "entry": {...}}
      data: {"event_type": "entry_updated", "entry": {...}}
      data: {"event_type": "entry_expired", "entry_id": "..."}

  Publish:
    POST /api/timeline/entries
    → Body: { entry data, signed with pod's ed25519 key }
    → Validated like agent registration (reuse existing crypto)
    → Broadcasts to all SSE subscribers

  Query:
    GET /api/timeline/entries?since={tick}&category={cat}
    → For catch-up after reconnection
```

### Pod ↔ Public Stream Flow

```
SUBSCRIBE:
  Pod startup → creates timeline_subscription for registry URL.
  Background task opens SSE connection to registry.
  Incoming events are pushed into kernel via podos_push_event()
  with source="public_stream".

PUBLISH:
  Pod creates an OPEN entry → triggers outbound sync.
  POST to registry /api/timeline/entries with signed payload.
  Registry validates, stores, broadcasts via SSE.
  Other subscribed pods receive it.

LIFECYCLE:
  Public entries can have window_start/window_end.
  Registry runs its own expiration loop (prune expired entries).
  Expiration broadcasts "entry_expired" event to subscribers.
  Subscribing pods archive corresponding shadows.
```

---

## Agent Operating Modes & Temporal Discovery

### The Problem

Right now the registry is a phone book — it says "Riverside Hospital exists" but not "Riverside Hospital is open Mon-Fri 8am-5pm, currently running a flu vaccination clinic, and Dr. Lee is available for consultations until 6pm." The registry has no temporal dimension.

With PodOS, the registry becomes a **living public timeline**. Agent cards aren't static profiles — they're resolved snapshots of what's currently active on each agent's public timeline.

### Operating Modes as Timeline Entries

Every agent publishes OPEN entries to the public stream. These entries ARE the operating mode:

```
Riverside Hospital (org pod, port 8012):
  Public timeline entries (already in seed data):
    "Emergency Services"          type: signal,    always active (no window)
    "Outpatient Hours"            type: event,     recurring: Mon-Fri 8am-5pm
    "Flu Vaccination Walk-in"     type: event,     window: 2026-02-15 to 2026-03-15
    "Accepting New Patients"      type: signal,    activated manually, no end date

Dr. Lee (person pod, port 8005):
  Public timeline entries:
    "Available for Consultations" type: signal,    recurring: Mon-Thu 9am-4pm
    "Accepting Referrals"         type: signal,    active (no window)
    "Conference Travel"           type: event,     window: 2026-03-01 to 2026-03-05
      → deactivation hook: mutate "Available for Consultations" → dormant
      → activation hook: notify pool members "Out of office until March 5"

Riverside Gov (government pod, port 8014):
  Public timeline entries:
    "Tax Filing Season"           type: signal,    window: Jan 15 – Apr 15
    "Public Comment Period: Zoning" type: event,   window: 2026-02-01 to 2026-03-01
    "Office Hours"                type: event,     recurring: Mon-Fri 9am-5pm
```

Key insight: these aren't special "operating mode" objects. They're regular timeline entries with `visibility: open`. The kernel already handles activation windows, recurring triggers, and lifecycle hooks. Operating modes are emergent from the entry set.

### Temporal Tags

Entries carry tags for discoverability on the public stream. Tags are free-form strings that pods use to filter what they subscribe to:

```
Entry tags are part of the entry metadata:
  "Flu Vaccination Walk-in" → tags: ["health", "vaccination", "walk-in"]
  "Tax Filing Season"       → tags: ["government", "tax", "filing", "deadline"]
  "Available for Consults"  → tags: ["health", "consultation", "physician"]

Pods subscribe with tag filters:
  Molly's pod subscribes to public stream with tags: ["health"]
  → Receives entries from Riverside Hospital AND Dr. Lee
  → Doesn't receive tax or zoning entries from Riverside Gov
```

### Temporal Discovery API (Registry Extension)

The registry's existing GET /api/agents becomes temporally aware:

```
CURRENT (static):
  GET /api/agents
  → Returns: [{did, name, pod_url, capabilities, ...}]

WITH TEMPORAL DISCOVERY:
  GET /api/agents?when=now
  → Returns agents with their CURRENTLY ACTIVE public entries
  → Each agent result includes: active_entries[] resolved from their public timeline

  GET /api/agents?when=2026-04-01
  → Returns agents with entries that will be active at that future date
  → Tax filing season? Active. Flu clinic? Expired.

  GET /api/agents?tags=health&when=now
  → Returns only agents with currently active health-tagged entries
  → Riverside Hospital: active (flu clinic, emergency, outpatient hours)
  → Dr. Lee: active (available for consults) OR dormant (conference travel)
  → Riverside Gov: not returned (no active health-tagged entries)

  GET /api/agents/{did}/timeline
  → Returns the agent's public timeline entries (all states)
  → Filtered by visibility (only OPEN entries visible)

  GET /api/agents/{did}/timeline?state=active
  → Returns only currently active entries for this agent
```

### Registry PodOS Architecture

The registry itself runs a PodOS kernel instance. Its timeline IS the public stream:

```
┌───────────────────────────────────────────────────────────┐
│  Registry (port 8100)                                      │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Zig Kernel Instance (public stream kernel)           │  │
│  │                                                        │  │
│  │  Entries: all OPEN entries published by all pods       │  │
│  │  Tick loop: evaluates windows, activates/deactivates  │  │
│  │  Resolution: no conflicts (all open, different pods)  │  │
│  │  Central state: the "what's happening now" snapshot   │  │
│  │  Event queue: receives from pod publishes + expiry    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  The registry's central state IS temporal discovery.       │
│  GET /api/agents?when=now = read registry's central state  │
│                                                            │
│  No separate "temporal discovery" code needed.             │
│  The kernel computes it every tick.                        │
└───────────────────────────────────────────────────────────┘
```

This means:
- When Riverside Hospital publishes "Flu Clinic" with window Feb 15 – Mar 15
- The registry kernel creates this entry on its timeline
- Every tick, the kernel evaluates: is now within Feb 15 – Mar 15?
- If yes → entry is ACTIVE → appears in registry's central state
- GET /api/agents?when=now reads central state → includes Riverside Hospital with "Flu Clinic" active
- On Mar 16, kernel tick deactivates the entry → next request won't show it

### Implementation in Registry

```typescript
// trustmesh-registry/lib/timeline.ts — additions

// On publish: create entry in registry's kernel
// The kernel handles activation/deactivation automatically

// Temporal query becomes a central state read:
export function getActiveAgentsNow(tags?: string[]): AgentWithTimeline[] {
  // Read kernel central state (computed by last tick)
  const state = registryKernel.getCentralState();
  const activeEntries = state.active_entries;

  // Group by publisher DID
  const byAgent = groupBy(activeEntries, e => e.publisher_did);

  // Join with agent records, filter by tags if provided
  return agents
    .filter(a => byAgent[a.did]?.length > 0)
    .filter(a => !tags || byAgent[a.did].some(e =>
      e.tags.some(t => tags.includes(t))
    ))
    .map(a => ({
      ...a,
      active_entries: byAgent[a.did],
    }));
}

// Future query: simulate tick at target time
export function getActiveAgentsAt(when: Date, tags?: string[]): AgentWithTimeline[] {
  // Ask kernel to evaluate at hypothetical time
  const state = registryKernel.evaluateAt(when);
  // Same grouping + filtering logic
}
```

### Integration with Existing Pod Discovery

When pods discover each other (existing `discover_agents` tool), the response now includes temporal context:

```python
# In agents.py discover_agents tool — enhanced response
{
    "did": "did:key:z6Mk...",
    "name": "Riverside Hospital",
    "entity_type": "organization",
    "trust_level": "public",
    "capabilities": ["health", "emergency", "vaccination"],
    "active_now": [
        {"entry_type": "signal", "category": "health", "label": "Emergency Services"},
        {"entry_type": "event", "category": "health", "label": "Flu Vaccination Walk-in",
         "window_end": "2026-03-15"},
        {"entry_type": "event", "category": "health", "label": "Outpatient Hours",
         "note": "Currently open (Mon-Fri 8am-5pm)"}
    ],
    "upcoming": [
        {"entry_type": "event", "category": "health", "label": "Spring Health Fair",
         "window_start": "2026-04-01"}
    ]
}
```

The agent doesn't just see "Riverside Hospital exists" — it sees what Riverside Hospital is doing right now and what's coming up. That's the temporal dimension that makes proactive behavior possible by structure.

---

## Encrypted Edge Storage (Pool Availability)

### The Problem

When a pod goes offline, its capsules become inaccessible. Pool members who need that data can't get it. The phone analogy: if you turn off your phone, nobody in your group chat can read your messages.

For personal pods this might be fine — you're offline, your data sleeps with you. But for organization pods (Riverside Hospital) or time-sensitive pools (emergency health), this is a problem.

### The Parquet-Inspired Edge Storage Idea

Take inspiration from data lakehouse architecture: encrypted flat files on the edge that pool members can access when the originating pod is offline.

```
Pod (online):
  Capsules live in SQLite + vault encryption (AES-256-GCM)
  ↓ selective export
  Encrypted column-oriented flat files (Parquet-inspired)
  ↓ push to edge storage
  R2 / S3 / any object store
  ↓ pool key decryption
  Pool members can read when originating pod is offline
```

### How It Works

```
1. POOL SHARED KEY
   When a pool forms, members agree on a shared encryption key.
   (Already in the design doc — pool-level shared key concept.)
   The shared key encrypts the edge copies. Not the pod vault key.

2. SELECTIVE EXPORT
   Pod owner chooses what goes to edge storage:
   - Only INTERNAL visibility capsules (pool-scoped)
   - Only capsules tagged for specific pools
   - Never PRIVATE capsules (those stay on-pod only)

   Timeline entries can trigger export:
     "Export health records to Family Health pool edge"
     → trigger: on capsule create with category=health, visibility=internal
     → hook: export_to_edge(capsule_id, pool_id)

3. FLAT FILE FORMAT (Parquet-inspired)
   Why Parquet-like and not just encrypted JSON?
   - Column-oriented: pool members can read metadata without decrypting content
   - Partitioned by category + time: efficient queries ("all health capsules from Feb")
   - Append-only: no overwrites, versioned
   - Signed: pod's ed25519 key signs each export batch

   Layout on object store:
     pools/{pool_id}/
       {pod_did}/
         health/
           2026-02.parquet.enc    ← encrypted column file
           2026-02.meta.json      ← unencrypted metadata (category, count, updated_at)
           2026-02.sig            ← ed25519 signature
         finance/
           ...

4. POOL MEMBER ACCESS
   When pod is offline and pool member needs data:
   → Check edge storage for pool
   → Decrypt with pool shared key
   → Read-only access (can't mutate — it's a flat file)
   → Agent treats as "stale cache" with last_synced timestamp

5. FRESHNESS SEMANTICS
   Edge files are snapshots, not live data:
   - last_synced_at timestamp on each file
   - Pool members' agents know the data might be stale
   - When pod comes back online: authoritative data wins
   - Timeline entry tracks staleness:
     "Edge health data for Molly: last synced 2h ago"
     salience increases as staleness grows
```

### Edge Storage as Timeline Entries

This fits naturally into PodOS — edge storage operations are timeline entries:

```
ExportToEdge entry:
  type: hook
  category: pool_sync
  visibility: internal
  trigger: event (capsule.created matching pool scope)
  hook: vault_op → encrypt + upload to R2
  ref: r2://pool-bucket/pools/{pool_id}/{pod_did}/...

EdgeSyncStatus entry:
  type: computed
  category: pool_sync
  visibility: internal
  computed from: last successful export timestamp
  salience: increases with staleness (0.1 at fresh, 0.9 at 24h stale)
  hook: notify pool members when staleness > threshold

EdgeRestore entry:
  type: hook
  category: pool_sync
  visibility: private
  trigger: event (pod.online after downtime)
  hook: compare edge vs local, reconcile
```

### Implementation Approach (Future Phase)

This is a future phase — not in the initial PoC. But the design accommodates it:

```
Phase 7 (post-PoC): Edge Storage

Step 7.1: Pool shared key management
  - Key exchange on pool formation
  - Key rotation mechanism
  - Stored encrypted in each member's vault

Step 7.2: Selective export engine
  - Filter capsules by pool scope + visibility
  - Column-oriented serialization (can use actual Parquet via PyArrow,
    or a simpler custom format for PoC)
  - Encrypt with pool shared key (AES-256-GCM, same crypto.py primitives)

Step 7.3: Object store integration
  - Abstract interface: put_file, get_file, list_files
  - R2 adapter (Cloudflare Workers for edge read)
  - Local filesystem adapter (for dev/testing)
  - S3-compatible adapter

Step 7.4: Timeline hooks for edge sync
  - ExportToEdge hook type in kernel
  - Freshness tracking as computed entries
  - Staleness alerts

Step 7.5: Edge read path
  - Pool member requests data → check pod first → fallback to edge
  - Decrypt with pool shared key
  - Mark as "edge cached" with staleness
  - Agent context includes edge data with freshness warning

DELIVERABLE: Pool data available from edge storage when pods are offline.
```

### Why This Matters

The edge storage layer completes the availability story:

```
Pod online + Pod online  → direct query (current behavior)
Pod online + Pod offline → edge storage fallback (new)
Pod offline + Pod online → catch-up sync on reconnect (existing)
Pod offline + Pod offline → both read from edge (new)
```

Without it, pools are only as available as their least-connected member. With it, pool data has the durability of object storage while maintaining the trust model — only pool members with the shared key can decrypt.

---

## Agent Integration

### New Agent Tools

Add to `agents.py` AGENT_TOOLS list:

```python
# --- Timeline tools ---

{
    "name": "create_timeline_entry",
    "description": "Create a new entry on the owner's timeline. Use this to set up reminders, track events, schedule tasks, or create hooks for proactive behavior.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entry_type": {"type": "string", "enum": ["event", "idea", "data", "reminder", "task", "milestone", "signal"]},
            "category": {"type": "string"},
            "visibility": {"type": "string", "enum": ["private", "internal", "open"], "default": "private"},
            "ref_type": {"type": "string", "enum": ["none", "capsule", "url"], "default": "none"},
            "ref_uri": {"type": "string", "default": ""},
            "anchor": {"type": "string", "description": "ISO datetime for time anchoring"},
            "window_start": {"type": "string", "description": "ISO datetime"},
            "window_end": {"type": "string", "description": "ISO datetime"},
            "activate_at": {"type": "string", "description": "ISO datetime to activate"},
            "deactivate_at": {"type": "string", "description": "ISO datetime to deactivate"},
            "hook_prompt": {"type": "string", "description": "Prompt for agent_task hook on activation"},
            "salience": {"type": "number", "default": 0.5},
            "depends_on_entry_id": {"type": "string", "description": "Entry ID this depends on"},
        },
        "required": ["entry_type", "category"]
    }
},
{
    "name": "get_timeline_state",
    "description": "Get the current timeline state: active entries, upcoming events, pending items, and attention signals. Use this to understand what's happening now and what needs attention.",
    "input_schema": {"type": "object", "properties": {}}
},
{
    "name": "search_timeline",
    "description": "Search timeline entries by category, type, state, or time range.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "entry_type": {"type": "string"},
            "state": {"type": "string"},
            "time_after": {"type": "string", "description": "ISO datetime"},
            "time_before": {"type": "string", "description": "ISO datetime"},
        }
    }
}
```

### Agent Context Enhancement

When the agent runs (either reactively from human query or proactively from hook), it receives timeline context:

```python
# In build_agent_context() — add timeline state
timeline_context = ""
kernel = get_kernel()
if kernel and kernel.current_state:
    state = kernel.current_state
    active = state.get("active_entries", [])
    signals = state.get("signals", [])
    upcoming = state.get("upcoming", [])

    if active:
        timeline_context += "\n## Currently Active on Your Timeline:\n"
        for e in active[:10]:  # top 10 by salience
            timeline_context += f"- [{e['visibility'].upper()}] {e['category']}: {e.get('label', e['entry_type'])} (salience: {e['salience']})\n"

    if signals:
        timeline_context += "\n## Attention Signals:\n"
        for s in signals:
            timeline_context += f"- [{s['severity'].upper()}] {s['message']}\n"

    if upcoming:
        timeline_context += "\n## Upcoming:\n"
        for u in upcoming[:5]:
            timeline_context += f"- {u['label']} — fires in {u.get('fires_in', '?')}\n"
```

### Proactive Hook Handler

```python
# In timeline_bridge.py or agents.py

async def handle_agent_task_hook(entry_data: dict):
    """Called by kernel when an agent_task hook fires."""
    from src.timeline_bridge import get_kernel
    from src.agents import query_agent
    from src.main import vault_keys

    owner_id = entry_data.get("creator_id", "")
    hook_prompt = entry_data.get("_hook_prompt", "")
    entry_context = json.dumps(entry_data, indent=2)

    # Build prompt combining hook instructions and entry context
    full_prompt = f"""PROACTIVE TASK (triggered by your timeline):

Entry context:
{entry_context}

Task:
{hook_prompt}

Act on this proactively. Your owner didn't ask for this — the timeline triggered it
because conditions were met. Be helpful and concise."""

    # Run agent query (self-query mode with tools)
    vault_key = vault_keys.get(owner_id)
    if not vault_key:
        # Owner not logged in — queue for later
        kernel = get_kernel()
        if kernel:
            kernel.push_event(TimelineEvent(
                source="system",
                event_type="hook_deferred",
                payload={"entry_id": entry_data["id"], "reason": "owner_not_logged_in"},
            ))
        return

    result = await query_agent(
        db=...,  # get from async session
        owner_id=owner_id,
        question=full_prompt,
        vault_key=vault_key,
    )

    # Push result back as event
    kernel = get_kernel()
    if kernel:
        kernel.push_event(TimelineEvent(
            source="agent",
            event_type="agent_task.completed",
            payload={
                "entry_id": entry_data["id"],
                "result": result,
            },
        ))
```

---

## Demo Scenario

### "Proactive Health Alert Across Trust Boundaries"

**Setup**: 3 pods running (from existing multi-pod.sh seed data)

| Plan Name | Seed Username | Port | Type | Role in Demo |
|-----------|---------------|------|------|-------------|
| Molly | molly | 8001 | person | Patient (Johnson family) |
| Dr. Lee | dr_lee | 8005 | person | Physician |
| Riverside Hospital | riverside_hospital | 8012 | organization | Hospital (public health) |

**Pool**: Already seeded — Dr. Lee and Molly share a health-related network
**Public**: Registry stream on port 8100

> Uses existing seed data from `seed.py` and `seed_multi.py`. No new entities needed.

### Scene 1: Public Stream Triggers Pod Action (45 seconds)

```
1. Riverside Hospital pod publishes to public stream:
   POST registry:8100/api/timeline/entries
   {
     entry_type: "signal",
     category: "health",
     content: "Flu Season Advisory: High-risk patients should schedule checkups",
     tags: ["health", "vaccination", "advisory"],
     window_start: "2026-02-01",
     window_end: "2026-04-01",
     visibility: "open"
   }

2. Dr. Lee's pod (subscribed to public stream, tags: ["health"]):
   → Kernel receives entry via SSE subscription
   → podos_push_event(source: public_stream, type: timeline.entry_created)
   → Next tick: entry matched by tag filter, shadow created on Dr. Lee's timeline
   → State: public stream shadow is ACTIVE (within window)

3. Dr. Lee's pod — agent_task hook fires:
   → Prompt: "Public health advisory about flu season received.
     Check your patient records for high-risk patients."
   → Agent searches vault, finds Molly's health capsules
   → Agent creates INTERNAL entry on shared pool timeline:
     "Molly should schedule a flu checkup — based on Riverside Hospital advisory"
     category: health, visibility: internal
   → Entry syncs to Molly's pod via pool sync

WHAT TO SHOW IN UI:
  - Dr. Lee's timeline: public shadow appears, agent task fires
  - Dr. Lee's timeline: new INTERNAL entry created automatically
  - State dashboard: "Public stream event processed, pool entry created"
```

### Scene 2: Pool Timeline Triggers Cross-Pod Action (45 seconds)

```
4. Molly's pod receives pool sync:
   → Shadow entry: "Molly should schedule flu checkup"
   → stream_layer: pool, visibility: internal
   → Molly's kernel processes on next tick

5. Molly's agent hook fires:
   → Prompt: "Dr. Lee recommends a flu checkup based on Riverside Hospital advisory.
     Check your schedule for available slots."
   → Agent checks calendar capsules, finds openings next week
   → Agent creates PRIVATE entry on Molly's timeline:
     "Schedule flu checkup — next week"
     hook: notify("Dr. Lee recommends a flu checkup. Available slots: ...")

6. Molly sees notification:
   → "Your agent noticed: Dr. Lee recommends a flu checkup based on a
      Riverside Hospital advisory. Want me to find an appointment?"

WHAT TO SHOW IN UI:
  - Molly's timeline: pool shadow appears
  - Molly's timeline: private entry auto-created by agent
  - Notification badge with proactive message
```

### Scene 3: Private > Internal > Open Resolution (30 seconds)

```
7. Molly already has a private entry:
   "Finals prep week — no appointments"
   category: health, visibility: private
   window: this week
   salience: 0.9

8. Resolution engine in Molly's kernel:
   → Private "finals prep" (salience 0.9) conflicts with
     pool "flu checkup" (salience 0.7)
   → Same category (health), overlapping time window
   → PRIVATE WINS. Pool entry's salience reduced to 0.21 (shadowed).

9. Molly's agent adjusts:
   → Sees resolution in central state
   → Updates response: "You have finals this week. I'll suggest next week
     instead and let Dr. Lee's agent know."
   → Creates entry on pool timeline: "Molly available next week for checkup"

WHAT TO SHOW IN UI:
  - Timeline view: private entry highlighted, pool entry visually dimmed
  - State dashboard: "1 conflict resolved (private > internal)"
  - Agent message updated to respect the priority
```

### Scene 4: CLI Demonstration (30 seconds)

```
$ trustmesh timeline state
┌─────────────────────────────────────────────────────────┐
│  Pod: Molly Johnson          Engine: ● running (tick 47)│
│                                                         │
│  ACTIVE (3):                                            │
│    ● [PRIVATE] Finals prep week         health  0.90    │
│    ● [INTERNAL] Flu checkup (shadowed)  health  0.21    │
│    ● [OPEN] Flu season advisory         health  0.15    │
│                                                         │
│  SIGNALS:                                               │
│    ⚠ 1 conflict resolved (private overrode internal)    │
│    ℹ Agent deferred checkup to next week                │
└─────────────────────────────────────────────────────────┘

$ trustmesh timeline list --state active
ID         Type       Category  Vis       Stream  Salience  Label
abc-123    event      health    private   pod     0.90      Finals prep week
def-456    reminder   health    internal  pool    0.21      Flu checkup (shadowed)
ghi-789    signal     health    open      public  0.15      Flu season advisory

$ trustmesh timeline history --entry-id def-456
Tick  Transition              Trigger      Note
31    dormant → pending       event        pool sync received
32    pending → activating    dependency   no deps
33    activating → active     hooks_done   agent processed
34    active: salience 0.7→0.21  resolution  shadowed by private abc-123
```

---

## Build Order

### Phase 1: Zig Kernel (Foundation)

```
Step 1.1: Scaffold Zig project
  - Create kernel/ directory structure
  - build.zig with shared library target
  - types.zig with all enums and constants

Step 1.2: Entry state machine
  - entry.zig: Entry struct, state transitions
  - test_entry.zig: Test all valid/invalid transitions

Step 1.3: Event queue
  - event.zig: Ring buffer, push/pop, event matching

Step 1.4: Dependency DAG
  - dag.zig: Add/remove entries, cycle detection, topo sort
  - test_dag.zig: Test cycles, dependency satisfaction

Step 1.5: Resolution engine
  - resolution.zig: 3-stream conflict resolution
  - test_resolution.zig: Test private > internal > open

Step 1.6: Central state
  - state.zig: Compute active set, signals, upcoming

Step 1.7: Transition log
  - log.zig: Append-only file, replay on startup

Step 1.8: Timeline engine (integration)
  - timeline.zig: Tick-tock loop, all subsystems connected
  - test_timeline.zig: Integration test — create entries, tick, verify state

Step 1.9: C ABI exports
  - main.zig: All export functions
  - Build and verify: zig build → libpodos.dylib

DELIVERABLE: libpodos.dylib that can be loaded from Python.
```

### Phase 2: Python Bridge + Backend

```
Step 2.1: Python FFI bridge
  - src/timeline_bridge.py: Load lib, wrap functions, tick thread
  - Verify: Python can init kernel, create entry, tick, get state

Step 2.2: Database schema
  - Add tables to models.py or separate migration
  - Persistence: write-through from kernel to SQLite

Step 2.3: API routes
  - src/routes/timeline.py: CRUD + state + engine endpoints
  - Register in main.py

Step 2.4: Kernel lifecycle in app startup
  - main.py lifespan(): init kernel, start tick loop, stop on shutdown

Step 2.5: Agent integration
  - New tools: create_timeline_entry, get_timeline_state, search_timeline
  - Agent context: inject timeline state into prompts
  - Hook handler: handle_agent_task_hook()

DELIVERABLE: Backend serves timeline API, kernel ticks in background.
```

### Phase 3: Federation + Sync

```
Step 3.1: Timeline sync endpoint
  - POST /api/timeline/sync: Receive entry events from peers
  - GET /api/timeline/sync/events: Pull missed events

Step 3.2: Shadow entry creation
  - On receiving sync: create shadow in kernel
  - Track shadow_source_pod, shadow_source_entry_id

Step 3.3: Pool timeline integration
  - On pool-sync: create subscription + shared timeline
  - INTERNAL entries auto-sync to pool peers

Step 3.4: Catch-up after offline
  - Track last_sync_tick per subscription
  - Pull missed events on reconnect

DELIVERABLE: Two pods sync timeline entries through pools.
```

### Phase 4: Public Stream

```
Step 4.1: Registry timeline extension
  - New tables in registry.db
  - POST /api/timeline/entries (publish)
  - GET /api/timeline/entries (query)
  - GET /api/timeline/stream (SSE)

Step 4.2: Pod subscription to public stream
  - Background SSE client in Python
  - Events pushed to kernel via podos_push_event

Step 4.3: Pod publishing OPEN entries
  - When OPEN entry created/updated, POST to registry
  - Signed with pod's ed25519 key

Step 4.4: Public entry lifecycle
  - Registry expiration loop (prune window_end < now)
  - Expiration events broadcast via SSE

DELIVERABLE: Public stream flows from registry to pods and back.
```

### Phase 5: CLI + UI

```
Step 5.1: CLI commands
  - trustmesh timeline list/add/get/update/state/watch/subscribe
  - Formatted output with rich tables

Step 5.2: UI — Timeline view
  - TimelineView.tsx: Main timeline display
  - EntryCard.tsx: Individual entry cards

Step 5.3: UI — Central state dashboard
  - CentralState.tsx: Live state with SSE updates

Step 5.4: UI — Add entry form + subscriptions manager
  - AddEntryForm.tsx
  - StreamSubscriptions.tsx

Step 5.5: UI — Pod dashboard integration
  - Add timeline widget to existing pod dashboard
  - Timeline engine status indicator

DELIVERABLE: Full UI showing timelines, state, subscriptions.
```

### Phase 6: Demo Polish

```
Step 6.1: Seed timeline data
  - Extend seed_multi.py to create timeline entries per pod
  - Pre-create the demo scenario entries (dormant, waiting for triggers)

Step 6.2: Demo script
  - Automated script that walks through the 4 demo scenes
  - Triggers events at the right moments

Step 6.3: Edge case handling
  - Visibility upgrade confirmation flow
  - Offline catch-up summary
  - Cascade depth limiting

Step 6.4: Testing
  - Zig kernel tests (zig build test)
  - Python bridge tests (pytest)
  - API endpoint tests
  - Multi-pod timeline sync tests
  - Edge case tests

DELIVERABLE: Polished demo ready to run.
```

### Phase 7 (Future): Encrypted Edge Storage

```
Step 7.1: Pool shared key management
  - Key exchange on pool formation (extend pool-sync)
  - Pool shared key stored in each member's vault (encrypted with vault key)
  - Key rotation: new key on member add/remove

Step 7.2: Selective export engine
  - Filter capsules by pool scope + visibility (INTERNAL only)
  - Serialize to column-oriented format (Parquet via PyArrow or simpler custom)
  - Encrypt with pool shared key (reuse crypto.py AES-256-GCM)
  - Sign batch with pod's ed25519 key

Step 7.3: Object store adapter
  - Abstract interface: put_file(), get_file(), list_files()
  - R2 adapter (Cloudflare Workers for edge read) — primary target
  - Local filesystem adapter (for dev/testing)
  - S3-compatible adapter (generic fallback)

Step 7.4: Timeline hooks for edge sync
  - ExportToEdge hook type in kernel
  - Freshness tracking as computed entries (staleness → rising salience)
  - Staleness alerts to pool members

Step 7.5: Edge read path
  - Pool member requests data → check originating pod first
  - Pod offline? → fallback to edge storage
  - Decrypt with pool shared key
  - Mark as "edge cached" with last_synced timestamp
  - Agent context includes edge data with freshness warning

DELIVERABLE: Pool data remains available from edge when pods go offline.
```

---

## File Manifest

### New Files

```
trustmesh-core/
  kernel/
    build.zig
    src/
      main.zig              ~200 lines  C ABI exports
      types.zig             ~100 lines  Enums, constants, timestamps
      entry.zig             ~200 lines  Entry struct, state machine, hooks
      event.zig             ~120 lines  Event queue, trigger matching
      cron.zig              ~80 lines   Cron expression parser + matcher
      dag.zig               ~130 lines  Dependency graph
      resolution.zig        ~100 lines  3-stream conflict resolution
      state.zig             ~120 lines  Central state computation
      log.zig               ~80 lines   Transition log
      timeline.zig          ~250 lines  Engine, tick-tock loop
    tests/
      test_entry.zig        ~100 lines
      test_dag.zig          ~80 lines
      test_resolution.zig   ~100 lines
      test_timeline.zig     ~150 lines

  src/
    timeline_bridge.py      ~300 lines  Python FFI wrapper + tick thread
    routes/timeline.py      ~250 lines  FastAPI endpoints

  tests/
    test_timeline_bridge.py ~200 lines
    test_timeline_api.py    ~200 lines
    test_timeline_sync.py   ~150 lines

trustmesh-ui/
  src/
    components/
      timeline/
        TimelineView.tsx    ~200 lines
        EntryCard.tsx        ~120 lines
        CentralState.tsx     ~150 lines
        AddEntryForm.tsx     ~200 lines
        StreamSubscriptions.tsx  ~120 lines
    app/[userId]/timeline/
      page.tsx              ~50 lines   (route page)

trustmesh-registry/
  lib/
    timeline.ts             ~200 lines  Public timeline management + temporal query
  app/api/timeline/
    stream/route.ts         ~80 lines   SSE endpoint
    entries/route.ts        ~120 lines  CRUD
    entries/[id]/route.ts   ~60 lines   Individual entry ops
  app/api/agents/
    route.ts                ~modify     Add ?when=now&tags=health temporal filtering
    [did]/timeline/
      route.ts              ~80 lines   Per-agent public timeline entries
```

### Modified Files

```
trustmesh-core/
  src/main.py               + kernel init/shutdown in lifespan
  src/models.py              + TimelineEntry, TimelineTransition, etc. models
  src/schemas.py             + Pydantic schemas for timeline API
  src/agents.py              + 3 timeline tools, context injection, hook handler
  src/federation.py          + timeline sync functions
  src/routes/pod.py          + timeline info in pod response
  src/cli.py                 + timeline subcommand group
  src/seed.py                + seed timeline entries for demo

trustmesh-ui/
  src/lib/api.ts             + timeline API functions
  src/app/[userId]/page.tsx  + timeline widget on dashboard
  src/app/layout.tsx         + timeline nav link

trustmesh-registry/
  lib/db.ts                  + public_timeline_entries table
  app/page.tsx               + public timeline section on landing
```

### Estimated Total

```
Zig kernel:     ~1,300 lines (source) + ~430 lines (tests)
Python bridge:  ~550 lines + ~550 lines (tests)
API + routes:   ~250 lines
CLI:            ~150 lines
UI components:  ~840 lines
Registry:       ~410 lines
Modified files: ~400 lines of additions

TOTAL NEW CODE: ~4,880 lines
```

---

## Prerequisites

```
Build tools:
  - Zig 0.13+ (brew install zig)
  - Python 3.12+ with uv
  - Bun (for registry + frontend)
  - Existing TrustMesh running

Runtime:
  - ANTHROPIC_API_KEY (for agent hooks)
  - Existing multi-pod setup (multi-pod.sh)
```

---

## Success Criteria

The PoC is complete when:

1. **Zig kernel builds and passes tests**: `cd kernel && zig build test`
2. **Kernel loads from Python**: `from src.timeline_bridge import init_kernel; k = init_kernel(); k.start()`
3. **Entries have lifecycle**: Create entry with time trigger → kernel ticks → entry activates → hook fires
4. **Resolution works**: Private entry shadows internal entry in same category+time
5. **Pod-to-pod sync**: Internal entry on Pod A appears as shadow on Pod B via pool
6. **Public stream flows**: City Health publishes → Registry SSE → Dr. Johnson's pod receives
7. **Agent is proactive**: Hook fires → agent runs task → creates new entry or notifies human
8. **CLI shows state**: `trustmesh timeline state` displays live central state
9. **UI shows timeline**: Timeline view with active entries, signals, subscriptions
10. **Demo runs end-to-end**: All 4 scenes complete without manual intervention (after initial setup)
