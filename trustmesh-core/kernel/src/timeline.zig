// PodOS Timeline Kernel — The Engine (tick-tock loop)
// TICK phase: evaluate triggers, deps, conflicts (frozen state)
// TOCK phase: apply transitions, fire hooks, recompute state (atomic commit)

const std = @import("std");
const types = @import("types.zig");
const entry_mod = @import("entry.zig");
const event_mod = @import("event.zig");
const cron_mod = @import("cron.zig");
const dag_mod = @import("dag.zig");
const resolution_mod = @import("resolution.zig");
const state_mod = @import("state.zig");
const log_mod = @import("log.zig");
const db_mod = @import("db.zig");
const persist_mod = @import("timeline_persist.zig");

const Entry = entry_mod.Entry;
const Event = event_mod.Event;

fn entryIdToUuidString(id: *const types.EntryId, out: *[36]u8) []const u8 {
    const hex = "0123456789abcdef";
    var j: usize = 0;
    for (id.*, 0..) |b, i| {
        if (i == 4 or i == 6 or i == 8 or i == 10) {
            out[j] = '-';
            j += 1;
        }
        out[j] = hex[@intCast(b >> 4)];
        out[j + 1] = hex[@intCast(b & 0x0f)];
        j += 2;
    }
    return out[0..36];
}

// ── Configuration ──

pub const EngineConfig = struct {
    heartbeat_ms: u32 = 5000, // minimum tick interval
    max_entries: u32 = 10_000,
    max_events_per_tick: u32 = 256,
    max_cascade_depth: u8 = 10, // hook chain depth limit (EC-5)
    max_hooks_per_tick: u32 = 32, // hook fire limit per tick (EC-5)
    log_path: [256]u8 = .{0} ** 256,
    log_path_len: u16 = 0,
};

// ── Callbacks (Python host registers these) ──

pub const HookCallback = *const fn (
    entry_id: *const types.EntryId,
    hook_index: u8,
    action_kind: u8,
    entry_json: [*]const u8,
    entry_json_len: u32,
) callconv(.c) void;

pub const StateCallback = *const fn (
    state_json: [*]const u8,
    state_json_len: u32,
) callconv(.c) void;

// ── Transition Plan (built in TICK, applied in TOCK) ──

pub const PlannedTransition = struct {
    entry_id: types.EntryId,
    from_state: types.EntryState,
    to_state: types.EntryState,
    trigger_kind: types.TriggerKind,
};

// ── The Engine ──

pub const Engine = struct {
    config: EngineConfig,
    allocator: std.mem.Allocator,

    // Entry storage
    entries: std.AutoHashMap(types.EntryId, *Entry),

    // Event queue
    event_queue: event_mod.EventQueue,

    // Dependency graph
    dag: dag_mod.DependencyGraph,

    // Tick state
    tick_count: u64 = 0,
    last_tick_at: types.Timestamp = 0,
    next_wake_at: types.Timestamp = 0,
    is_running: bool = false,
    in_catchup_mode: bool = false,

    // Callbacks
    hook_callback: ?HookCallback = null,
    state_callback: ?StateCallback = null,

    // TICK phase output
    transition_plan: std.ArrayList(PlannedTransition),

    // Central state
    central_state: state_mod.CentralState = .{},

    // Transition log
    tlog: log_mod.TransitionLog = .{},

    // Optional SQLite persistence (attached by host).
    persist_db: ?*db_mod.Database = null,

    // Stats
    hooks_fired_this_tick: u32 = 0,
    conflicts_resolved_this_tick: u32 = 0,

    // ── Lifecycle ──

    pub fn init(allocator: std.mem.Allocator, config: EngineConfig) !*Engine {
        const self = try allocator.create(Engine);
        self.* = .{
            .config = config,
            .allocator = allocator,
            .entries = std.AutoHashMap(types.EntryId, *Entry).init(allocator),
            .event_queue = try event_mod.EventQueue.init(allocator, config.max_events_per_tick * 2),
            .dag = dag_mod.DependencyGraph.init(allocator),
            .transition_plan = std.ArrayList(PlannedTransition){},
        };

        // Open transition log if path configured
        if (config.log_path_len > 0) {
            self.tlog = try log_mod.TransitionLog.init(config.log_path[0..config.log_path_len]);
        }

        return self;
    }

    pub fn deinit(self: *Engine) void {
        // Free all entries
        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            self.allocator.destroy(entry_ptr.*);
        }
        self.entries.deinit();
        self.event_queue.deinit(self.allocator);
        self.dag.deinit();
        self.transition_plan.deinit(self.allocator);
        self.tlog.deinit();
        self.allocator.destroy(self);
    }

    pub fn attachPersistDb(self: *Engine, database: *db_mod.Database) void {
        self.persist_db = database;
    }

    pub fn detachPersistDb(self: *Engine) void {
        self.persist_db = null;
    }

    // ── Entry management ──

    pub fn addEntry(self: *Engine, e: Entry) !types.EntryId {
        const entry_ptr = try self.allocator.create(Entry);
        entry_ptr.* = e;
        entry_ptr.created_at = types.nowMs();

        try self.entries.put(entry_ptr.id, entry_ptr);

        // Register in DAG if it has dependencies
        if (entry_ptr.dep_count > 0) {
            self.dag.addEntry(entry_ptr) catch |err| {
                // Rollback on cycle
                _ = self.entries.remove(entry_ptr.id);
                self.allocator.destroy(entry_ptr);
                return err;
            };
        }

        return entry_ptr.id;
    }

    pub fn getEntry(self: *Engine, id: types.EntryId) ?*Entry {
        return self.entries.get(id);
    }

    pub fn pushEvent(self: *Engine, evt: Event) !void {
        try self.event_queue.push(evt);
    }

    // ══════════════════════════════
    //  THE TICK-TOCK CYCLE
    // ══════════════════════════════

    pub fn tick(self: *Engine) !void {
        if (!self.is_running) return;

        const now = types.nowMs();
        self.tick_count += 1;
        self.hooks_fired_this_tick = 0;
        self.conflicts_resolved_this_tick = 0;
        self.transition_plan.clearRetainingCapacity();

        // ═══ TICK PHASE (evaluate, frozen state) ═══

        // 1. Drain event queue — match events to dormant entries
        self.processEvents(now);

        // 2. Evaluate time triggers (including cron)
        self.evaluateTimeTriggers(now);

        // 3. Check absence triggers (expected events that didn't arrive)
        self.checkAbsenceTriggers(now);

        // 4. Check window expiry for active entries
        self.checkWindowExpiry(now);

        // 5. Evaluate dependencies for pending entries
        self.evaluateDependencies();

        // 6. Advance activating entries (pre-hooks done → active)
        self.advanceActivating();

        // ═══ TOCK PHASE (commit, apply changes) ═══

        // 7. Apply all planned transitions atomically
        for (self.transition_plan.items) |t| {
            if (self.entries.get(t.entry_id)) |e| {
                e.previous_state = e.state;
                e.state = t.to_state;
                e.last_transition_at = now;

                if (t.to_state == .active) e.tick_activated = self.tick_count;
                if (t.to_state == .completed or t.to_state == .archived)
                    e.tick_deactivated = self.tick_count;

                // Log transition
                self.tlog.append(.{
                    .entry_id = t.entry_id,
                    .from_state = t.from_state,
                    .to_state = t.to_state,
                    .trigger_kind = t.trigger_kind,
                    .tick = self.tick_count,
                    .timestamp = now,
                }) catch {};

                // Durable transition log + authoritative state mirror (SQLite).
                if (self.persist_db) |pdb| {
                    var id_buf: [36]u8 = undefined;
                    const id_str = entryIdToUuidString(&t.entry_id, &id_buf);
                    const from_i32: i32 = @intCast(@intFromEnum(t.from_state));
                    const to_i32: i32 = @intCast(@intFromEnum(t.to_state));
                    const trig_i32: i32 = @intCast(@intFromEnum(t.trigger_kind));
                    persist_mod.updateEntryState(pdb, id_str.ptr, id_str.len, to_i32) catch {};
                    persist_mod.appendTransition(
                        pdb,
                        self.tick_count,
                        now,
                        id_str.ptr,
                        id_str.len,
                        from_i32,
                        to_i32,
                        trig_i32,
                    ) catch {};
                }
            }
        }

        // 8. Resolve conflicts (Private > Internal > Open)
        self.resolveConflicts();

        // 9. Fire hooks for transitioned entries
        self.dispatchHooks();

        // 10. Recompute central state
        self.central_state.recompute(&self.entries, self.tick_count, now);
        self.central_state.conflicts_resolved = self.conflicts_resolved_this_tick;

        // 11. Compute next wake time
        self.next_wake_at = self.computeNextWake(now);
        self.last_tick_at = now;
    }

    // ── TICK phase helpers ──

    fn processEvents(self: *Engine, now: types.Timestamp) void {
        var processed: u32 = 0;
        while (self.event_queue.pop()) |evt| {
            if (processed >= self.config.max_events_per_tick) break;

            var it = self.entries.valueIterator();
            while (it.next()) |entry_ptr| {
                const e = entry_ptr.*;
                if (e.state != .dormant) continue;
                if (e.activation_trigger.kind != .event) continue;

                if (event_mod.matches(&e.activation_trigger.event_match, &evt)) {
                    self.enqueueTransition(e.id, .dormant, .pending, .event);
                }
            }
            _ = now;
            processed += 1;
        }
    }

    fn evaluateTimeTriggers(self: *Engine, now: types.Timestamp) void {
        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;

            // Activation time triggers
            if (e.state == .dormant and e.activation_trigger.kind == .time) {
                if (e.shouldActivateByTime(now)) {
                    self.enqueueTransition(e.id, .dormant, .pending, .time);
                    continue;
                }
                // Check cron
                if (e.activation_trigger.time.cron_len > 0) {
                    const pattern = e.activation_trigger.time.cron_pattern[0..e.activation_trigger.time.cron_len];
                    const expr = cron_mod.parse(pattern) catch continue;
                    if (cron_mod.cronMatches(&expr, now)) {
                        self.enqueueTransition(e.id, .dormant, .pending, .time);
                    }
                }
            }

            // Deactivation time triggers
            if (e.state == .active and e.deactivation_trigger.kind == .time) {
                if (e.deactivation_trigger.time.at > 0 and e.deactivation_trigger.time.at <= now) {
                    self.enqueueTransition(e.id, .active, .deactivating, .time);
                }
            }
        }
    }

    fn checkAbsenceTriggers(self: *Engine, now: types.Timestamp) void {
        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;
            if (e.shouldFireAbsence(now)) {
                // Mark absence as fired
                entry_ptr.*.activation_trigger.absence.fired = true;
                entry_ptr.*.activation_trigger.absence.last_checked_at = now;
                self.enqueueTransition(e.id, .dormant, .pending, .absence);
            }
        }
    }

    fn checkWindowExpiry(self: *Engine, now: types.Timestamp) void {
        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;
            if (e.state == .active and e.isWindowExpired(now)) {
                self.enqueueTransition(e.id, .active, .deactivating, .time);
            }
        }
    }

    fn evaluateDependencies(self: *Engine) void {
        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;
            if (e.state != .pending) continue;

            if (e.dep_count == 0) {
                // No deps — go straight to activating
                self.enqueueTransition(e.id, .pending, .activating, .dependency);
                continue;
            }

            const result = self.dag.depsSatisfied(e, &self.entries);
            if (result.satisfied) {
                self.enqueueTransition(e.id, .pending, .activating, .dependency);
            }
        }
    }

    fn advanceActivating(self: *Engine) void {
        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;
            if (e.state != .activating) continue;

            // Check if pre-hooks are done
            if (e.hook_count == 0 or e.allHooksCompleted(.pre)) {
                if (e.anyHookExhausted()) {
                    // At least one pre-hook exhausted retries — fail the entry
                    self.enqueueTransition(e.id, .activating, .failed, .manual);
                } else {
                    self.enqueueTransition(e.id, .activating, .active, .manual);
                }
            }
        }
    }

    // ── TOCK phase helpers ──

    fn resolveConflicts(self: *Engine) void {
        // Collect active entries into a slice
        var active_list = std.ArrayList(*Entry){};
        defer active_list.deinit(self.allocator);

        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;
            if (e.isActive() or e.state == .activating) {
                active_list.append(self.allocator, e) catch continue;
            }
        }

        if (active_list.items.len > 1) {
            self.conflicts_resolved_this_tick = resolution_mod.resolveConflicts(active_list.items);
        }
    }

    fn dispatchHooks(self: *Engine) void {
        const cb = self.hook_callback orelse return;

        for (self.transition_plan.items) |t| {
            if (self.hooks_fired_this_tick >= self.config.max_hooks_per_tick) break;

            if (self.entries.get(t.entry_id)) |e| {
                // Check cascade depth (EC-5)
                if (e.cascade_depth >= self.config.max_cascade_depth) continue;

                for (e.hooks[0..e.hook_count], 0..) |*hook, idx| {
                    if (self.hooks_fired_this_tick >= self.config.max_hooks_per_tick) break;

                    // Pre-hooks fire on activation transitions
                    if (hook.phase == .pre and
                        (t.to_state == .activating or t.to_state == .active))
                    {
                        if (hook.status == .pending) {
                            hook.status = .running;
                            hook.last_attempt_at = types.nowMs();
                            hook.attempts += 1;
                            cb(&e.id, @intCast(idx), @intFromEnum(hook.action_kind), &types.ZERO_ID, 0);
                            self.hooks_fired_this_tick += 1;
                        }
                    }

                    // Post-hooks fire on deactivation transitions
                    if (hook.phase == .post and
                        (t.to_state == .deactivating or t.to_state == .completed))
                    {
                        if (hook.status == .pending) {
                            hook.status = .running;
                            hook.last_attempt_at = types.nowMs();
                            hook.attempts += 1;
                            cb(&e.id, @intCast(idx), @intFromEnum(hook.action_kind), &types.ZERO_ID, 0);
                            self.hooks_fired_this_tick += 1;
                        }
                    }
                }
            }
        }
    }

    fn computeNextWake(self: *Engine, now: types.Timestamp) types.Timestamp {
        var earliest = now + self.config.heartbeat_ms;

        var it = self.entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;

            // Dormant entries with time triggers
            if (e.state == .dormant and e.activation_trigger.kind == .time) {
                const t = e.activation_trigger.time.at;
                if (t > now and t < earliest) earliest = t;
                const ws = e.window_start;
                if (ws > now and ws < earliest) earliest = ws;

                // Cron: find next match
                if (e.activation_trigger.time.cron_len > 0) {
                    const pattern = e.activation_trigger.time.cron_pattern[0..e.activation_trigger.time.cron_len];
                    const expr = cron_mod.parse(pattern) catch continue;
                    const next = cron_mod.cronNext(&expr, now);
                    if (next > 0 and next < earliest) earliest = next;
                }
            }

            // Active entries with window expiry
            if (e.state == .active and e.window_end > 0) {
                if (e.window_end > now and e.window_end < earliest) earliest = e.window_end;
            }

            // Active entries with deactivation time triggers
            if (e.state == .active and e.deactivation_trigger.kind == .time) {
                const t = e.deactivation_trigger.time.at;
                if (t > now and t < earliest) earliest = t;
            }

            // Absence triggers
            if (e.state == .dormant and e.activation_trigger.kind == .absence) {
                const t = e.activation_trigger.absence.expected_by;
                if (t > now and t < earliest and !e.activation_trigger.absence.fired) earliest = t;
            }
        }

        return earliest;
    }

    // ── Helpers ──

    fn enqueueTransition(
        self: *Engine,
        id: types.EntryId,
        from: types.EntryState,
        to: types.EntryState,
        kind: types.TriggerKind,
    ) void {
        // Check for duplicate in plan
        for (self.transition_plan.items) |existing| {
            if (types.ids_equal(existing.entry_id, id)) return;
        }

        if (!types.validTransition(from, to)) return;

        self.transition_plan.append(self.allocator, .{
            .entry_id = id,
            .from_state = from,
            .to_state = to,
            .trigger_kind = kind,
        }) catch {};
    }
};
