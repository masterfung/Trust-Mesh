// PodOS Timeline Kernel — C ABI exports
// Entry point for the shared library (libpodos.dylib/.so).
// Python loads this via ctypes and calls exported functions.
// ~40 exports covering engine lifecycle, entry CRUD, events, state, hooks.

const std = @import("std");
pub const types = @import("types.zig");
pub const entry = @import("entry.zig");
pub const event = @import("event.zig");
pub const cron = @import("cron.zig");
pub const dag = @import("dag.zig");
pub const resolution = @import("resolution.zig");
pub const state = @import("state.zig");
pub const log = @import("log.zig");
pub const timeline = @import("timeline.zig");

// Page allocator for FFI — simple, no libc dependency
const ffi_allocator = std.heap.page_allocator;

// ═══════════════════════════════════════════
//  VERSION
// ═══════════════════════════════════════════

export fn podos_version() callconv(.c) u32 {
    return 0x000100; // 0.1.0
}

// ═══════════════════════════════════════════
//  ENGINE LIFECYCLE
// ═══════════════════════════════════════════

export fn podos_engine_create(
    heartbeat_ms: u32,
    max_entries: u32,
    max_events_per_tick: u32,
) callconv(.c) ?*anyopaque {
    const config = timeline.EngineConfig{
        .heartbeat_ms = if (heartbeat_ms > 0) heartbeat_ms else 5000,
        .max_entries = if (max_entries > 0) max_entries else 10_000,
        .max_events_per_tick = if (max_events_per_tick > 0) max_events_per_tick else 256,
    };
    const eng = timeline.Engine.init(ffi_allocator, config) catch return null;
    return @ptrCast(eng);
}

export fn podos_engine_destroy(ptr: ?*anyopaque) callconv(.c) void {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return));
    eng.deinit();
}

export fn podos_engine_start(ptr: ?*anyopaque) callconv(.c) void {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return));
    eng.is_running = true;
}

export fn podos_engine_stop(ptr: ?*anyopaque) callconv(.c) void {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return));
    eng.is_running = false;
}

export fn podos_engine_tick(ptr: ?*anyopaque) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return -1));
    eng.tick() catch return -2;
    return 0;
}

export fn podos_engine_is_running(ptr: ?*anyopaque) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return -1));
    return if (eng.is_running) @as(i32, 1) else @as(i32, 0);
}

// ═══════════════════════════════════════════
//  ENTRY BUILDER (allocate, set fields, add)
// ═══════════════════════════════════════════

export fn podos_entry_create() callconv(.c) ?*anyopaque {
    const e = ffi_allocator.create(entry.Entry) catch return null;
    e.* = .{};
    return @ptrCast(e);
}

export fn podos_entry_free(ptr: ?*anyopaque) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    ffi_allocator.destroy(e);
}

export fn podos_entry_set_id(ptr: ?*anyopaque, id_bytes: [*]const u8) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    @memcpy(&e.id, id_bytes[0..16]);
}

export fn podos_entry_set_label(ptr: ?*anyopaque, str: [*]const u8, len: u8) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    const actual_len: u8 = @intCast(@min(@as(usize, len), types.MAX_LABEL_LEN));
    e.setLabel(str[0..actual_len]);
}

export fn podos_entry_set_category(ptr: ?*anyopaque, str: [*]const u8, len: u8) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    const actual_len: u8 = @intCast(@min(@as(usize, len), types.MAX_CATEGORY_LEN));
    e.setCategory(str[0..actual_len]);
}

export fn podos_entry_set_visibility(ptr: ?*anyopaque, vis: u8) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.visibility = @enumFromInt(vis);
    e.stream_layer = switch (e.visibility) {
        .open => .public,
        .internal => .pool,
        .private => .pod,
    };
}

export fn podos_entry_set_salience(ptr: ?*anyopaque, salience: f32) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.salience = salience;
    e.original_salience = salience;
}

export fn podos_entry_set_window(ptr: ?*anyopaque, start_ms: i64, end_ms: i64) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.window_start = start_ms;
    e.window_end = end_ms;
}

export fn podos_entry_set_entry_type(ptr: ?*anyopaque, entry_type: u8) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.entry_type = @enumFromInt(entry_type);
}

export fn podos_entry_set_trigger_time(ptr: ?*anyopaque, at_ms: i64) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.activation_trigger.kind = .time;
    e.activation_trigger.time.at = at_ms;
}

export fn podos_entry_set_trigger_cron(ptr: ?*anyopaque, str: [*]const u8, len: u8) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.activation_trigger.kind = .time;
    const actual_len: u8 = @intCast(@min(@as(usize, len), types.MAX_CRON_LEN));
    @memcpy(e.activation_trigger.time.cron_pattern[0..actual_len], str[0..actual_len]);
    e.activation_trigger.time.cron_len = actual_len;
}

export fn podos_entry_set_trigger_event(
    ptr: ?*anyopaque,
    source: u8,
    type_str: [*]const u8,
    type_len: u8,
) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.activation_trigger.kind = .event;
    e.activation_trigger.event_match.source_filter = @enumFromInt(source);
    const actual_len: u8 = @intCast(@min(@as(usize, type_len), types.MAX_EVENT_TYPE_LEN));
    @memcpy(e.activation_trigger.event_match.type_pattern[0..actual_len], type_str[0..actual_len]);
    e.activation_trigger.event_match.type_pattern_len = actual_len;
}

export fn podos_entry_set_trigger_absence(
    ptr: ?*anyopaque,
    event_type_str: [*]const u8,
    event_type_len: u8,
    deadline_ms: i64,
) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.activation_trigger.kind = .absence;
    const actual_len: u8 = @intCast(@min(@as(usize, event_type_len), types.MAX_EVENT_TYPE_LEN));
    @memcpy(e.activation_trigger.absence.expected_event_type[0..actual_len], event_type_str[0..actual_len]);
    e.activation_trigger.absence.expected_event_type_len = actual_len;
    e.activation_trigger.absence.expected_by = deadline_ms;
}

export fn podos_entry_set_deactivation_time(ptr: ?*anyopaque, at_ms: i64) callconv(.c) void {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return));
    e.deactivation_trigger.kind = .time;
    e.deactivation_trigger.time.at = at_ms;
}

export fn podos_entry_add_dep(
    ptr: ?*anyopaque,
    dep_id: [*]const u8,
    required_state: u8,
    is_hard: u8,
) callconv(.c) i32 {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return -1));
    if (e.dep_count >= types.MAX_DEPS) return -2;
    var dep = entry.Dependency{};
    @memcpy(&dep.entry_id, dep_id[0..16]);
    dep.required_state = @enumFromInt(required_state);
    dep.is_hard = is_hard != 0;
    e.deps[e.dep_count] = dep;
    e.dep_count += 1;
    return 0;
}

export fn podos_entry_add_hook(
    ptr: ?*anyopaque,
    action_kind: u8,
    phase: u8,
    prompt_str: ?[*]const u8,
    prompt_len: u16,
    timeout_ms: u32,
    max_retries: u8,
) callconv(.c) i32 {
    const e: *entry.Entry = @ptrCast(@alignCast(ptr orelse return -1));
    if (e.hook_count >= types.MAX_HOOKS) return -2;
    var hook = entry.Hook{};
    hook.action_kind = @enumFromInt(action_kind);
    hook.phase = if (phase == 0) .pre else .post;
    if (prompt_str) |ps| {
        const actual_len: u16 = @intCast(@min(@as(usize, prompt_len), types.MAX_HOOK_PROMPT_LEN));
        @memcpy(hook.prompt[0..actual_len], ps[0..actual_len]);
        hook.prompt_len = actual_len;
    }
    hook.timeout_ms = if (timeout_ms > 0) timeout_ms else 30_000;
    hook.max_retries = max_retries;
    e.hooks[e.hook_count] = hook;
    e.hook_count += 1;
    return 0;
}

// ═══════════════════════════════════════════
//  ENGINE ENTRY MANAGEMENT
// ═══════════════════════════════════════════

/// Add entry to engine (transfers ownership — entry_ptr is freed).
/// Returns 0 on success, negative on error.
export fn podos_engine_add_entry(engine_ptr: ?*anyopaque, entry_ptr: ?*anyopaque) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    const e: *entry.Entry = @ptrCast(@alignCast(entry_ptr orelse return -2));
    _ = eng.addEntry(e.*) catch return -3;
    // Engine copies internally — free the builder
    ffi_allocator.destroy(e);
    return 0;
}

export fn podos_engine_get_entry_state(engine_ptr: ?*anyopaque, id_bytes: [*]const u8) callconv(.c) i8 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -2;
    return @intCast(@intFromEnum(e.state));
}

export fn podos_engine_entry_count(engine_ptr: ?*anyopaque) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return 0));
    return eng.entries.count();
}

export fn podos_engine_transition_entry(
    engine_ptr: ?*anyopaque,
    id_bytes: [*]const u8,
    new_state: u8,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -2;
    e.transition(@enumFromInt(new_state)) catch return -3;
    return 0;
}

// ── Entry getters (read from engine) ──

export fn podos_engine_get_entry_label(
    engine_ptr: ?*anyopaque,
    id_bytes: [*]const u8,
    out_buf: [*]u8,
    out_buf_len: u32,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -2;
    const label = e.getLabel();
    const copy_len: u32 = @intCast(@min(label.len, out_buf_len));
    @memcpy(out_buf[0..copy_len], label[0..copy_len]);
    return @intCast(copy_len);
}

export fn podos_engine_get_entry_category(
    engine_ptr: ?*anyopaque,
    id_bytes: [*]const u8,
    out_buf: [*]u8,
    out_buf_len: u32,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -2;
    const cat = e.getCategory();
    const copy_len: u32 = @intCast(@min(cat.len, out_buf_len));
    @memcpy(out_buf[0..copy_len], cat[0..copy_len]);
    return @intCast(copy_len);
}

export fn podos_engine_get_entry_salience(
    engine_ptr: ?*anyopaque,
    id_bytes: [*]const u8,
) callconv(.c) f32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1.0));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -1.0;
    return e.salience;
}

export fn podos_engine_get_entry_visibility(
    engine_ptr: ?*anyopaque,
    id_bytes: [*]const u8,
) callconv(.c) i8 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -2;
    return @intCast(@intFromEnum(e.visibility));
}

/// Get all entry IDs. Caller provides buffer (max_count * 16 bytes).
/// Returns number of IDs written.
export fn podos_engine_get_all_ids(
    engine_ptr: ?*anyopaque,
    out_ids: [*]u8,
    max_count: u32,
) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return 0));
    var count: u32 = 0;
    var it = eng.entries.keyIterator();
    while (it.next()) |key| {
        if (count >= max_count) break;
        @memcpy(out_ids[count * 16 ..][0..16], key);
        count += 1;
    }
    return count;
}

// ═══════════════════════════════════════════
//  EVENT MANAGEMENT
// ═══════════════════════════════════════════

export fn podos_event_push(
    engine_ptr: ?*anyopaque,
    source: u8,
    type_str: [*]const u8,
    type_len: u8,
    timestamp_ms: i64,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var evt = event.Event{};
    evt.source = @enumFromInt(source);
    const actual_len: u8 = @intCast(@min(@as(usize, type_len), types.MAX_EVENT_TYPE_LEN));
    evt.setEventType(type_str[0..actual_len]);
    evt.timestamp = if (timestamp_ms > 0) timestamp_ms else types.nowMs();
    eng.pushEvent(evt) catch return -2;
    return 0;
}

// ═══════════════════════════════════════════
//  CENTRAL STATE QUERIES
// ═══════════════════════════════════════════

export fn podos_state_active_count(ptr: ?*anyopaque) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.active_count;
}

export fn podos_state_pending_count(ptr: ?*anyopaque) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.pending_count;
}

export fn podos_state_dormant_count(ptr: ?*anyopaque) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.dormant_count;
}

export fn podos_state_failed_count(ptr: ?*anyopaque) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.failed_count;
}

export fn podos_state_total_count(ptr: ?*anyopaque) callconv(.c) u32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.total_count;
}

export fn podos_state_tick_count(ptr: ?*anyopaque) callconv(.c) u64 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.tick_count;
}

export fn podos_state_signal_count(ptr: ?*anyopaque) callconv(.c) u16 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.central_state.signal_count;
}

export fn podos_state_get_signal(
    ptr: ?*anyopaque,
    index: u16,
    out_severity: *u8,
    out_msg: [*]u8,
    out_msg_len: u32,
    out_entry_id: [*]u8,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return -1));
    if (index >= eng.central_state.signal_count) return -2;
    const sig = &eng.central_state.signals[index];
    out_severity.* = @intFromEnum(sig.severity);
    const msg = sig.getMessage();
    const copy_len: u32 = @intCast(@min(msg.len, out_msg_len));
    @memcpy(out_msg[0..copy_len], msg[0..copy_len]);
    @memcpy(out_entry_id[0..16], &sig.related_entry_id);
    return @intCast(copy_len);
}

export fn podos_state_get_active_id(
    ptr: ?*anyopaque,
    index: u32,
    out_id: [*]u8,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return -1));
    if (index >= eng.central_state.active_count) return -2;
    @memcpy(out_id[0..16], &eng.central_state.active_ids[index]);
    return 0;
}

// ═══════════════════════════════════════════
//  HOOK MANAGEMENT
// ═══════════════════════════════════════════

export fn podos_hook_complete(
    engine_ptr: ?*anyopaque,
    id_bytes: [*]const u8,
    hook_index: u8,
    success: u8,
) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    var id: types.EntryId = undefined;
    @memcpy(&id, id_bytes[0..16]);
    const e = eng.getEntry(id) orelse return -2;
    if (hook_index >= e.hook_count) return -3;
    e.hooks[hook_index].status = if (success != 0) .completed else .failed;
    return 0;
}

export fn podos_register_hook_callback(
    engine_ptr: ?*anyopaque,
    cb: ?timeline.HookCallback,
) callconv(.c) void {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return));
    eng.hook_callback = cb;
}

export fn podos_register_state_callback(
    engine_ptr: ?*anyopaque,
    cb: ?timeline.StateCallback,
) callconv(.c) void {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return));
    eng.state_callback = cb;
}

// ═══════════════════════════════════════════
//  UTILITY
// ═══════════════════════════════════════════

export fn podos_now_ms() callconv(.c) i64 {
    return types.nowMs();
}

export fn podos_engine_next_wake(ptr: ?*anyopaque) callconv(.c) i64 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.next_wake_at;
}

export fn podos_engine_tick_count(ptr: ?*anyopaque) callconv(.c) u64 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(ptr orelse return 0));
    return eng.tick_count;
}
