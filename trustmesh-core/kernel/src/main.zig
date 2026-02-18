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
pub const db = @import("db.zig");
pub const fts = @import("fts.zig");
pub const timeline_persist = @import("timeline_persist.zig");
pub const crypto = @import("crypto.zig");
pub const trust = @import("trust.zig");
pub const session = @import("session.zig");
pub const rate_limit = @import("rate_limit.zig");
pub const transit = @import("transit.zig");
pub const federation_auth = @import("federation_auth.zig");
pub const federation = @import("federation.zig");
pub const json = @import("json.zig");
pub const credential = @import("credential.zig");
pub const credential_audit = @import("credential_audit.zig");

// Page allocator for FFI — simple, no libc dependency
const ffi_allocator = std.heap.page_allocator;

// ── Global state for session, rate limit, and transit stores ──
var _session_store: ?*session.SessionStore = null;
var _rate_limiter: ?*rate_limit.RateLimiter = null;
var _transit_engine: ?*transit.TransitEngine = null;

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

export fn podos_engine_attach_persist_db(engine_ptr: ?*anyopaque, db_handle: ?*anyopaque) callconv(.c) i32 {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return -1));
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -2));
    eng.attachPersistDb(database);
    return 0;
}

export fn podos_engine_detach_persist_db(engine_ptr: ?*anyopaque) callconv(.c) void {
    const eng: *timeline.Engine = @ptrCast(@alignCast(engine_ptr orelse return));
    eng.detachPersistDb();
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

// ═══════════════════════════════════════════
//  DATABASE / FTS5 (SQLite full-text search)
// ═══════════════════════════════════════════

/// Open a SQLite DB (same trustmesh.db) and create the FTS5 table.
/// Returns opaque handle, or null on error.
export fn podos_db_open(path: [*]const u8, path_len: u32) callconv(.c) ?*anyopaque {
    // Copy path to null-terminated buffer on the stack
    var buf: [4096]u8 = undefined;
    const len: usize = @min(path_len, buf.len - 1);
    @memcpy(buf[0..len], path[0..len]);
    buf[len] = 0;
    const path_z: [*:0]const u8 = buf[0..len :0];

    var database = ffi_allocator.create(db.Database) catch return null;
    database.* = db.Database.open(path_z) catch {
        ffi_allocator.destroy(database);
        return null;
    };

    // Create FTS5 table
    fts.initFtsTable(database) catch {
        database.close();
        ffi_allocator.destroy(database);
        return null;
    };

    // Create timeline persistence tables
    timeline_persist.initTables(database) catch {
        database.close();
        ffi_allocator.destroy(database);
        return null;
    };

    return @ptrCast(database);
}

/// Close a DB handle opened by podos_db_open.
export fn podos_db_close(handle: ?*anyopaque) callconv(.c) void {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return));
    database.close();
    ffi_allocator.destroy(database);
}

/// Upsert a capsule into the FTS5 index.
/// Returns 0 on success, negative on error.
export fn podos_fts_upsert(
    handle: ?*anyopaque,
    capsule_id: [*]const u8,
    id_len: u32,
    title_ptr: [*]const u8,
    title_len: u32,
    content_ptr: [*]const u8,
    content_len: u32,
    category_ptr: [*]const u8,
    category_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    fts.upsertCapsule(
        database,
        capsule_id,
        id_len,
        title_ptr,
        title_len,
        content_ptr,
        content_len,
        category_ptr,
        category_len,
    ) catch return -2;
    return 0;
}

/// Delete a capsule from the FTS5 index.
/// Returns 0 on success, negative on error.
export fn podos_fts_delete(
    handle: ?*anyopaque,
    capsule_id: [*]const u8,
    id_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    fts.deleteCapsule(database, capsule_id, id_len) catch return -2;
    return 0;
}

/// Search capsules via FTS5 MATCH with BM25 ranking.
/// `accessible_ids_json` is a JSON array: '["id1","id2",...]'
/// Results written to out_buf as JSON. out_len set to bytes written.
/// Returns 0 on success, negative on error.
export fn podos_fts_search(
    handle: ?*anyopaque,
    query: [*]const u8,
    query_len: u32,
    accessible_ids_json: [*]const u8,
    ids_len: u32,
    top_k: u32,
    out_buf: [*]u8,
    out_capacity: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    const written = fts.searchCapsules(
        database,
        query,
        query_len,
        accessible_ids_json,
        ids_len,
        top_k,
        out_buf,
        out_capacity,
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Drop and recreate the FTS5 table (for testing/seeding).
/// Returns 0 on success, negative on error.
export fn podos_fts_reset(handle: ?*anyopaque) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    fts.resetFts(database) catch return -2;
    return 0;
}

// ═══════════════════════════════════════════
//  TIMELINE PERSISTENCE (SQLite)
// ═══════════════════════════════════════════

/// Upsert an entry spec into timeline_entries.
/// entry_id and owner_id are UTF-8 strings.
/// spec_json must be a JSON object (stored verbatim).
export fn podos_timeline_entry_upsert(
    handle: ?*anyopaque,
    entry_id: [*]const u8,
    entry_id_len: u32,
    owner_id: [*]const u8,
    owner_id_len: u32,
    entry_state: i32,
    spec_json: [*]const u8,
    spec_json_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    timeline_persist.upsertEntry(
        database,
        entry_id,
        entry_id_len,
        owner_id,
        owner_id_len,
        entry_state,
        spec_json,
        spec_json_len,
    ) catch return -2;
    return 0;
}

/// Update the persisted state for an entry (best-effort mirror).
export fn podos_timeline_entry_update_state(
    handle: ?*anyopaque,
    entry_id: [*]const u8,
    entry_id_len: u32,
    entry_state: i32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    timeline_persist.updateEntryState(database, entry_id, entry_id_len, entry_state) catch return -2;
    return 0;
}

/// Delete an entry from timeline_entries.
export fn podos_timeline_entry_delete(
    handle: ?*anyopaque,
    entry_id: [*]const u8,
    entry_id_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    timeline_persist.deleteEntry(database, entry_id, entry_id_len) catch return -2;
    return 0;
}

/// Load persisted entry specs as a JSON array written into out_buf.
/// If owner_id_len == 0, loads all entries.
/// Returns 0 on success, -3 if buffer too small.
export fn podos_timeline_entries_load(
    handle: ?*anyopaque,
    owner_id: [*]const u8,
    owner_id_len: u32,
    out_buf: [*]u8,
    out_capacity: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    const owner_ptr: ?[*]const u8 = if (owner_id_len > 0) owner_id else null;
    const written = timeline_persist.loadEntrySpecsJson(
        database,
        owner_ptr,
        owner_id_len,
        out_buf,
        out_capacity,
    ) catch |err| switch (err) {
        timeline_persist.PersistError.BufferTooSmall => return -3,
        else => return -2,
    };
    out_len.* = @intCast(written);
    return 0;
}

/// Lookup persisted owner_id for an entry_id. Writes raw UTF-8 string into out_buf.
/// Returns 0 on success, -3 if buffer too small.
export fn podos_timeline_entry_get_owner(
    handle: ?*anyopaque,
    entry_id: [*]const u8,
    entry_id_len: u32,
    out_buf: [*]u8,
    out_capacity: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    const written = timeline_persist.getEntryOwner(
        database,
        entry_id,
        entry_id_len,
        out_buf,
        out_capacity,
    ) catch |err| switch (err) {
        timeline_persist.PersistError.BufferTooSmall => return -3,
        else => return -2,
    };
    out_len.* = @intCast(written);
    return 0;
}

/// Append a JSON event to the outbox (for catch-up sync).
export fn podos_timeline_outbox_append(
    handle: ?*anyopaque,
    tick: u64,
    event_json: [*]const u8,
    event_json_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    timeline_persist.appendOutboxEvent(database, tick, event_json, event_json_len) catch return -2;
    return 0;
}

/// Pull outbox JSON events since a given tick. Writes a JSON array into out_buf.
/// Returns 0 on success, -3 if buffer too small.
export fn podos_timeline_outbox_pull(
    handle: ?*anyopaque,
    since_tick: u64,
    out_buf: [*]u8,
    out_capacity: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    const written = timeline_persist.pullOutboxEventsJson(
        database,
        since_tick,
        out_buf,
        out_capacity,
    ) catch |err| switch (err) {
        timeline_persist.PersistError.BufferTooSmall => return -3,
        else => return -2,
    };
    out_len.* = @intCast(written);
    return 0;
}

/// Mark a sync event as seen in the inbox (dedupe). Uses INSERT OR IGNORE.
export fn podos_timeline_inbox_mark(
    handle: ?*anyopaque,
    event_id: [*]const u8,
    event_id_len: u32,
    event_json: [*]const u8,
    event_json_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    timeline_persist.markInboxEvent(database, event_id, event_id_len, event_json, event_json_len) catch return -2;
    return 0;
}

// ═══════════════════════════════════════════
//  CRYPTO
// ═══════════════════════════════════════════

/// Generate a random 32-byte AES-256 key.
export fn podos_crypto_generate_key(out_key: [*]u8) callconv(.c) void {
    const key = crypto.generateKey();
    @memcpy(out_key[0..32], &key);
}

/// Encrypt plaintext with AES-256-GCM.
/// Output: nonce(12) || ciphertext || tag(16). Returns bytes written, or negative on error.
export fn podos_crypto_encrypt(
    plaintext: [*]const u8,
    pt_len: u32,
    key: [*]const u8,
    out_buf: [*]u8,
    out_capacity: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const k: *const [32]u8 = @ptrCast(key);
    const written = crypto.encrypt(
        plaintext[0..pt_len],
        k,
        out_buf[0..out_capacity],
    ) catch return -1;
    out_len.* = @intCast(written);
    return 0;
}

/// Decrypt AES-256-GCM data. Returns plaintext bytes written, or negative on error.
export fn podos_crypto_decrypt(
    data: [*]const u8,
    data_len: u32,
    key: [*]const u8,
    out_buf: [*]u8,
    out_capacity: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const k: *const [32]u8 = @ptrCast(key);
    const written = crypto.decrypt(
        data[0..data_len],
        k,
        out_buf[0..out_capacity],
    ) catch return -1;
    out_len.* = @intCast(written);
    return 0;
}

/// Derive vault key from password using Argon2id.
/// If salt_in is null, generates random salt. Returns 0 on success.
export fn podos_crypto_derive_vault_key(
    password: [*]const u8,
    pw_len: u32,
    salt_in: ?[*]const u8,
    salt_len: u32,
    out_key: [*]u8,
    out_salt: [*]u8,
) callconv(.c) i32 {
    var salt_ptr: ?*const [16]u8 = null;
    if (salt_in) |s| {
        if (salt_len >= 16) {
            salt_ptr = @ptrCast(s);
        }
    }
    var key_buf: [32]u8 = undefined;
    defer std.crypto.secureZero(u8, &key_buf);
    var salt_buf: [16]u8 = undefined;
    crypto.deriveVaultKey(
        ffi_allocator,
        password[0..pw_len],
        salt_ptr,
        &key_buf,
        &salt_buf,
    ) catch return -1;
    @memcpy(out_key[0..32], &key_buf);
    @memcpy(out_salt[0..16], &salt_buf);
    return 0;
}

/// Hash a PIN with Argon2id. Writes "hex(salt)$hex(hash)" to out_buf.
/// Returns bytes written, or negative on error.
export fn podos_crypto_hash_pin(
    pin: [*]const u8,
    pin_len: u32,
    out_buf: [*]u8,
    out_len: *u32,
) callconv(.c) i32 {
    var buf: [128]u8 = undefined;
    const written = crypto.hashPin(ffi_allocator, pin[0..pin_len], &buf) catch return -1;
    @memcpy(out_buf[0..written], buf[0..written]);
    out_len.* = @intCast(written);
    return 0;
}

/// Verify a PIN against its Argon2id hash. Returns 1 if match, 0 if not.
export fn podos_crypto_verify_pin(
    pin: [*]const u8,
    pin_len: u32,
    hash_str: [*]const u8,
    hash_len: u32,
) callconv(.c) i32 {
    return if (crypto.verifyPin(ffi_allocator, pin[0..pin_len], hash_str[0..hash_len])) 1 else 0;
}

/// Generate an Ed25519 keypair. Writes 32-byte seed + 32-byte public key.
export fn podos_crypto_ed25519_keygen(
    out_seed: [*]u8,
    out_pub: [*]u8,
) callconv(.c) void {
    const kp = crypto.ed25519Keygen();
    @memcpy(out_seed[0..32], &kp.seed);
    @memcpy(out_pub[0..32], &kp.public_key);
}

/// Sign a message with Ed25519. Returns 0 on success, writes 64-byte signature.
export fn podos_crypto_ed25519_sign(
    msg: [*]const u8,
    msg_len: u32,
    seed: [*]const u8,
    out_sig: [*]u8,
) callconv(.c) i32 {
    const s: *const [32]u8 = @ptrCast(seed);
    const sig = crypto.ed25519Sign(msg[0..msg_len], s) catch return -1;
    @memcpy(out_sig[0..64], &sig);
    return 0;
}

/// Verify an Ed25519 signature. Returns 1 if valid, 0 if not.
export fn podos_crypto_ed25519_verify(
    msg: [*]const u8,
    msg_len: u32,
    sig: [*]const u8,
    pub_key: [*]const u8,
) callconv(.c) i32 {
    const s: *const [64]u8 = @ptrCast(sig);
    const p: *const [32]u8 = @ptrCast(pub_key);
    return if (crypto.ed25519Verify(msg[0..msg_len], s, p)) 1 else 0;
}

/// SHA-256 hash → 64-char hex string.
export fn podos_crypto_sha256_hex(
    data: [*]const u8,
    data_len: u32,
    out_hex: [*]u8,
) callconv(.c) void {
    var hex: [64]u8 = undefined;
    crypto.sha256Hex(data[0..data_len], &hex);
    @memcpy(out_hex[0..64], &hex);
}

/// Convert ed25519 public key to did:key string. Returns chars written.
export fn podos_crypto_pubkey_to_did(
    pub_key: [*]const u8,
    out_buf: [*]u8,
    out_capacity: u32,
) callconv(.c) i32 {
    const pk: *const [32]u8 = @ptrCast(pub_key);
    const len = crypto.publicKeyToDid(pk, out_buf[0..out_capacity]);
    return @intCast(len);
}

/// Extract raw ed25519 public key from did:key string. Returns 0 on success.
export fn podos_crypto_did_to_pubkey(
    did: [*]const u8,
    did_len: u32,
    out_key: [*]u8,
) callconv(.c) i32 {
    var key: [32]u8 = undefined;
    crypto.didKeyToPublicKey(did[0..did_len], &key) catch return -1;
    @memcpy(out_key[0..32], &key);
    return 0;
}

/// Base64url encode (no padding). Returns chars written.
export fn podos_crypto_b64url_encode(
    data: [*]const u8,
    data_len: u32,
    out_buf: [*]u8,
    out_capacity: u32,
) callconv(.c) i32 {
    const len = crypto.base64urlEncode(data[0..data_len], out_buf[0..out_capacity]);
    return @intCast(len);
}

/// Base64url decode (no padding). Returns bytes written, or negative on error.
export fn podos_crypto_b64url_decode(
    encoded: [*]const u8,
    enc_len: u32,
    out_buf: [*]u8,
    out_capacity: u32,
) callconv(.c) i32 {
    const len = crypto.base64urlDecode(encoded[0..enc_len], out_buf[0..out_capacity]) catch return -1;
    return @intCast(len);
}

// ═══════════════════════════════════════════
//  TRUST
// ═══════════════════════════════════════════

/// Resolve trust level between two users via SQLite queries.
/// Uses the same db_handle as FTS5. Returns JSON bytes written, or negative on error.
export fn podos_trust_resolve(
    handle: ?*anyopaque,
    from_id: [*]const u8,
    from_id_len: u32,
    to_id: [*]const u8,
    to_id_len: u32,
    out_buf: [*]u8,
    out_capacity: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(handle orelse return -1));
    const written = trust.resolveTrustLevel(
        database,
        from_id,
        from_id_len,
        to_id,
        to_id_len,
        out_buf,
        out_capacity,
    ) catch return -2;
    return @intCast(written);
}

// ═══════════════════════════════════════════
//  SESSION MANAGEMENT
// ═══════════════════════════════════════════

/// Initialize the global session store. Call once on startup.
export fn podos_session_init() callconv(.c) i32 {
    if (_session_store != null) return 0; // already initialized
    const store = ffi_allocator.create(session.SessionStore) catch return -1;
    store.* = session.SessionStore.init(ffi_allocator);
    _session_store = store;
    return 0;
}

/// Destroy the global session store. Call on shutdown.
export fn podos_session_deinit() callconv(.c) void {
    if (_session_store) |store| {
        store.deinit();
        ffi_allocator.destroy(store);
        _session_store = null;
    }
}

/// Create a new session (backward compat — no fingerprint binding).
/// Writes token to out_token. Returns token length, or negative on error.
export fn podos_session_create(
    user_id: [*]const u8,
    user_id_len: u32,
    out_token: [*]u8,
    out_capacity: u32,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    const len = store.createSession(
        user_id[0..user_id_len],
        "", // empty fingerprint for backward compat
        out_token[0..out_capacity],
    ) catch return -2;
    return @intCast(len);
}

/// Create a new session with fingerprint binding (Phase 2).
/// Fingerprint = SHA-256(user_agent + "|" + client_ip).
/// Enforces per-user session cap (evicts oldest on overflow).
export fn podos_session_create_fp(
    uid_ptr: [*]const u8,
    uid_len: usize,
    fp_ptr: [*]const u8,
    fp_len: usize,
    out_token: [*]u8,
    out_cap: usize,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    const len = store.createSession(
        uid_ptr[0..uid_len],
        fp_ptr[0..fp_len],
        out_token[0..out_cap],
    ) catch return -2;
    return @intCast(len);
}

/// Validate a session token (backward compat — no fingerprint check).
/// Writes user_id to out_user_id. Returns user_id length, or -1 if invalid.
export fn podos_session_validate(
    token: [*]const u8,
    token_len: u32,
    out_user_id: [*]u8,
    out_capacity: u32,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    const uid = store.validateSession(token[0..token_len], "") orelse return -1;
    if (uid.len > out_capacity) return -2;
    @memcpy(out_user_id[0..uid.len], uid);
    return @intCast(uid.len);
}

/// Validate a session token with fingerprint verification (Phase 2).
/// Checks TTL, inactivity timeout, and fingerprint binding.
/// Returns user_id length, or -1 if invalid/expired/fingerprint mismatch.
export fn podos_session_validate_fp(
    tok_ptr: [*]const u8,
    tok_len: usize,
    fp_ptr: [*]const u8,
    fp_len: usize,
    out_uid: [*]u8,
    out_cap: usize,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    const uid = store.validateSession(tok_ptr[0..tok_len], fp_ptr[0..fp_len]) orelse return -1;
    if (uid.len > out_cap) return -2;
    @memcpy(out_uid[0..uid.len], uid);
    return @intCast(uid.len);
}

/// Invalidate a session by token.
export fn podos_session_invalidate(
    token: [*]const u8,
    token_len: u32,
) callconv(.c) void {
    const store = _session_store orelse return;
    store.invalidateSession(token[0..token_len]);
}

/// Invalidate all sessions for a user.
export fn podos_session_invalidate_user(
    user_id: [*]const u8,
    user_id_len: u32,
) callconv(.c) void {
    const store = _session_store orelse return;
    store.invalidateUserSessions(user_id[0..user_id_len]);
}

/// Check login rate limit. Returns 1 if allowed, 0 if rate limited, -1 on error.
export fn podos_session_check_login_rate(
    ip: [*]const u8,
    ip_len: u32,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    const allowed = store.checkLoginRateLimit(ip[0..ip_len]) catch return -1;
    return if (allowed) 1 else 0;
}

/// Reset all session state (test helper).
export fn podos_session_reset() callconv(.c) void {
    const store = _session_store orelse return;
    store.reset();
}

/// Inject a session (test helper, backward compat — no fingerprint). Returns 0 on success.
export fn podos_session_inject(
    token: [*]const u8,
    token_len: u32,
    user_id: [*]const u8,
    user_id_len: u32,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    store.injectSession(
        token[0..token_len],
        user_id[0..user_id_len],
        "", // empty fingerprint for backward compat (all-zeros hash, skips verification)
    ) catch return -2;
    return 0;
}

/// Count active sessions for a user. Returns count, or -1 on error.
export fn podos_session_count_user(
    uid_ptr: [*]const u8,
    uid_len: usize,
) callconv(.c) i32 {
    const store = _session_store orelse return -1;
    const count = store.countUserSessions(uid_ptr[0..uid_len]);
    return @intCast(count);
}

// ═══════════════════════════════════════════
//  RATE LIMITING
// ═══════════════════════════════════════════

/// Initialize the global rate limiter. Call once on startup.
export fn podos_rate_init() callconv(.c) i32 {
    if (_rate_limiter != null) return 0;
    const limiter = ffi_allocator.create(rate_limit.RateLimiter) catch return -1;
    limiter.* = rate_limit.RateLimiter.init(ffi_allocator);
    _rate_limiter = limiter;
    return 0;
}

/// Destroy the global rate limiter. Call on shutdown.
export fn podos_rate_deinit() callconv(.c) void {
    if (_rate_limiter) |limiter| {
        limiter.deinit();
        ffi_allocator.destroy(limiter);
        _rate_limiter = null;
    }
}

/// Check connection rate limit. Returns 1 if allowed, 0 if denied.
/// If denied, writes reason to out_msg, sets out_msg_len.
export fn podos_rate_check_connection(
    user_id: [*]const u8,
    user_id_len: u32,
    out_msg: [*]u8,
    out_msg_len: *u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    const result = limiter.checkConnection(user_id[0..user_id_len]);
    const msg = result.getMessage();
    @memcpy(out_msg[0..msg.len], msg);
    out_msg_len.* = @intCast(msg.len);
    return if (result.allowed) 1 else 0;
}

/// Record a connection request.
export fn podos_rate_record_connection(
    user_id: [*]const u8,
    user_id_len: u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    limiter.recordConnection(user_id[0..user_id_len]) catch return -2;
    return 0;
}

/// Check query rate limit. Returns 1 if allowed, 0 if denied.
/// is_public: 1 for public trust, 0 for trusted.
export fn podos_rate_check_query(
    user_id: [*]const u8,
    user_id_len: u32,
    target_id: [*]const u8,
    target_id_len: u32,
    is_public: i32,
    out_msg: [*]u8,
    out_msg_len: *u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    const result = limiter.checkQuery(
        user_id[0..user_id_len],
        target_id[0..target_id_len],
        is_public != 0,
    );
    const msg = result.getMessage();
    @memcpy(out_msg[0..msg.len], msg);
    out_msg_len.* = @intCast(msg.len);
    return if (result.allowed) 1 else 0;
}

/// Record a query.
export fn podos_rate_record_query(
    user_id: [*]const u8,
    user_id_len: u32,
    target_id: [*]const u8,
    target_id_len: u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    limiter.recordQuery(
        user_id[0..user_id_len],
        target_id[0..target_id_len],
    ) catch return -2;
    return 0;
}

/// Reset all rate limit state (test helper).
export fn podos_rate_reset() callconv(.c) void {
    const limiter = _rate_limiter orelse return;
    limiter.reset();
}

/// Check PIN attempt rate. Returns 1 if allowed, 0 if denied, -1 on error.
export fn podos_rate_check_pin(
    uid_ptr: [*]const u8,
    uid_len: u32,
    out_msg: [*]u8,
    out_msg_len: *u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    const result = limiter.checkPin(uid_ptr[0..uid_len]);
    const msg = result.getMessage();
    @memcpy(out_msg[0..msg.len], msg);
    out_msg_len.* = @intCast(msg.len);
    return if (result.allowed) 1 else 0;
}

/// Record a PIN attempt.
export fn podos_rate_record_pin(uid_ptr: [*]const u8, uid_len: u32) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    limiter.recordPin(uid_ptr[0..uid_len]) catch return -2;
    return 0;
}

/// Check emergency token issuance rate. Returns 1 if allowed, 0 if denied, -1 on error.
export fn podos_rate_check_emergency_issue(
    key_ptr: [*]const u8,
    key_len: u32,
    out_msg: [*]u8,
    out_msg_len: *u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    const result = limiter.checkEmergencyIssue(key_ptr[0..key_len]);
    const msg = result.getMessage();
    @memcpy(out_msg[0..msg.len], msg);
    out_msg_len.* = @intCast(msg.len);
    return if (result.allowed) 1 else 0;
}

/// Record an emergency token issuance.
export fn podos_rate_record_emergency_issue(key_ptr: [*]const u8, key_len: u32) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    limiter.recordEmergencyIssue(key_ptr[0..key_len]) catch return -2;
    return 0;
}

/// Check emergency access rate. Returns 1 if allowed, 0 if denied, -1 on error.
export fn podos_rate_check_emergency_present(
    key_ptr: [*]const u8,
    key_len: u32,
    out_msg: [*]u8,
    out_msg_len: *u32,
) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    const result = limiter.checkEmergencyPresent(key_ptr[0..key_len]);
    const msg = result.getMessage();
    @memcpy(out_msg[0..msg.len], msg);
    out_msg_len.* = @intCast(msg.len);
    return if (result.allowed) 1 else 0;
}

/// Record an emergency access attempt.
export fn podos_rate_record_emergency_present(key_ptr: [*]const u8, key_len: u32) callconv(.c) i32 {
    const limiter = _rate_limiter orelse return -1;
    limiter.recordEmergencyPresent(key_ptr[0..key_len]) catch return -2;
    return 0;
}

// ═══════════════════════════════════════════
//  TRANSIT ENGINE (in-memory keyring)
// ═══════════════════════════════════════════

/// Initialize the global transit engine. Call once on startup.
export fn podos_transit_init() callconv(.c) i32 {
    if (_transit_engine != null) return 0;
    const engine = ffi_allocator.create(transit.TransitEngine) catch return -1;
    engine.* = transit.TransitEngine.init(ffi_allocator);
    _transit_engine = engine;
    return 0;
}

/// Destroy the global transit engine. secureZero all keys. Call on shutdown.
export fn podos_transit_deinit() callconv(.c) void {
    if (_transit_engine) |engine| {
        engine.deinit();
        ffi_allocator.destroy(engine);
        _transit_engine = null;
    }
}

/// Store a key for a user. Returns version number, or negative on error.
export fn podos_transit_store_key(
    user_id: [*]const u8,
    uid_len: u32,
    key_ptr: [*]const u8,
) callconv(.c) i32 {
    const engine = _transit_engine orelse return -1;
    const key: *const [32]u8 = @ptrCast(key_ptr);
    const version = engine.storeKey(user_id[0..uid_len], key) catch return -2;
    return @intCast(version);
}

/// Encrypt plaintext for a user with AAD.
/// Output: "v{N}.{nonce}{ciphertext}{tag}" written to out_buf.
/// Returns 0 on success, writes out_len. Negative on error.
export fn podos_transit_encrypt(
    user_id: [*]const u8,
    uid_len: u32,
    pt: [*]const u8,
    pt_len: u32,
    aad: [*]const u8,
    aad_len: u32,
    out: [*]u8,
    out_cap: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const engine = _transit_engine orelse return -1;
    const written = engine.encryptForUser(
        user_id[0..uid_len],
        pt[0..pt_len],
        aad[0..aad_len],
        out[0..out_cap],
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Decrypt ciphertext for a user with AAD.
/// Handles versioned and legacy formats. Returns 0 on success. Negative on error.
export fn podos_transit_decrypt(
    user_id: [*]const u8,
    uid_len: u32,
    ct: [*]const u8,
    ct_len: u32,
    aad: [*]const u8,
    aad_len: u32,
    out: [*]u8,
    out_cap: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const engine = _transit_engine orelse return -1;
    const written = engine.decryptForUser(
        user_id[0..uid_len],
        ct[0..ct_len],
        aad[0..aad_len],
        out[0..out_cap],
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Rotate key for a user. Returns new version, or negative on error.
export fn podos_transit_rotate(
    user_id: [*]const u8,
    uid_len: u32,
) callconv(.c) i32 {
    const engine = _transit_engine orelse return -1;
    const version = engine.rotateKey(user_id[0..uid_len]) catch return -2;
    return @intCast(version);
}

/// Remove all keys for a user. secureZero all material.
export fn podos_transit_remove(
    user_id: [*]const u8,
    uid_len: u32,
) callconv(.c) void {
    const engine = _transit_engine orelse return;
    engine.removeUser(user_id[0..uid_len]);
}

/// Check if a user has a key loaded. Returns 1 if yes, 0 if no.
export fn podos_transit_has_key(
    user_id: [*]const u8,
    uid_len: u32,
) callconv(.c) i32 {
    const engine = _transit_engine orelse return 0;
    return if (engine.hasKey(user_id[0..uid_len])) 1 else 0;
}

// ═══════════════════════════════════════════
//  FEDERATION AUTH (Phase 6)
// ═══════════════════════════════════════════

/// Initialize the federation auth nonce cache. Call once at startup.
/// Returns 0 on success.
export fn podos_federation_auth_init() callconv(.c) i32 {
    federation_auth.initNonceCache(ffi_allocator);
    return 0;
}

/// Destroy the federation auth nonce cache. Call on shutdown.
export fn podos_federation_auth_deinit() callconv(.c) void {
    federation_auth.deinitNonceCache();
}

// ═══════════════════════════════════════════
//  CREDENTIAL STORE (Phase 7)
// ═══════════════════════════════════════════

/// Create a credential. `secret_encrypted` is already encrypted by the transit engine.
/// `scoped_tools_json` is a JSON array string. `expires_at` may be null (pass len=0).
/// Returns 0 on success, negative on error.
export fn podos_credential_create(
    db_handle: ?*anyopaque,
    id: [*]const u8,
    id_len: u32,
    owner_id: [*]const u8,
    owner_len: u32,
    name: [*]const u8,
    name_len: u32,
    service: [*]const u8,
    service_len: u32,
    category: [*]const u8,
    cat_len: u32,
    secret_enc: [*]const u8,
    secret_enc_len: u32,
    scoped_tools_json: [*]const u8,
    tools_len: u32,
    expires_at: ?[*]const u8,
    exp_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const exp = if (expires_at != null and exp_len > 0) expires_at.?[0..exp_len] else null;
    credential.create(
        database,
        id[0..id_len],
        owner_id[0..owner_len],
        name[0..name_len],
        service[0..service_len],
        category[0..cat_len],
        secret_enc[0..secret_enc_len],
        scoped_tools_json[0..tools_len],
        exp,
    ) catch return -2;
    return 0;
}

/// List credentials for owner (metadata only, no secrets).
/// Writes JSON array to out_buf. Returns bytes written, or negative on error.
export fn podos_credential_list(
    db_handle: ?*anyopaque,
    owner_id: [*]const u8,
    owner_len: u32,
    out_buf: [*]u8,
    out_cap: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const written = credential.list(
        database,
        owner_id[0..owner_len],
        out_buf[0..out_cap],
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Find credentials scoped to a specific tool. Returns JSON array with encrypted blobs.
export fn podos_credential_for_tool(
    db_handle: ?*anyopaque,
    owner_id: [*]const u8,
    owner_len: u32,
    tool_name: [*]const u8,
    tool_len: u32,
    out_buf: [*]u8,
    out_cap: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const written = credential.forTool(
        database,
        owner_id[0..owner_len],
        tool_name[0..tool_len],
        out_buf[0..out_cap],
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Update use count + last_used_at for a credential.
export fn podos_credential_update_use(
    db_handle: ?*anyopaque,
    id: [*]const u8,
    id_len: u32,
    actor_id: [*]const u8,
    actor_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    credential.updateUse(database, id[0..id_len], actor_id[0..actor_len]) catch return -2;
    return 0;
}

/// Soft-delete a credential (owner check enforced).
export fn podos_credential_deactivate(
    db_handle: ?*anyopaque,
    id: [*]const u8,
    id_len: u32,
    owner_id: [*]const u8,
    owner_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    credential.deactivate(database, id[0..id_len], owner_id[0..owner_len]) catch |err| switch (err) {
        credential.CredentialError.PermissionDenied => return -3,
        else => return -2,
    };
    return 0;
}

/// Create a credential share.
export fn podos_credential_share_create(
    db_handle: ?*anyopaque,
    share_id: [*]const u8,
    share_id_len: u32,
    cred_id: [*]const u8,
    cred_id_len: u32,
    grantor_id: [*]const u8,
    grantor_len: u32,
    grantee_id: [*]const u8,
    grantee_len: u32,
    grantee_type: [*]const u8,
    gtype_len: u32,
    expires_at: [*]const u8,
    exp_len: u32,
    max_uses: i32,
    secret_reenc: ?[*]const u8,
    secret_reenc_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const reenc = if (secret_reenc != null and secret_reenc_len > 0) secret_reenc.?[0..secret_reenc_len] else null;
    credential.shareCreate(
        database,
        share_id[0..share_id_len],
        cred_id[0..cred_id_len],
        grantor_id[0..grantor_len],
        grantee_id[0..grantee_len],
        grantee_type[0..gtype_len],
        expires_at[0..exp_len],
        if (max_uses > 0) max_uses else null,
        reenc,
    ) catch |err| switch (err) {
        credential.CredentialError.PermissionDenied => return -3,
        else => return -2,
    };
    return 0;
}

/// Check grantee share access. Returns bytes written to out_buf, or 0 if no valid share.
export fn podos_credential_share_check(
    db_handle: ?*anyopaque,
    cred_id: [*]const u8,
    cred_id_len: u32,
    grantee_id: [*]const u8,
    grantee_len: u32,
    out_buf: [*]u8,
    out_cap: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const written = credential.shareCheck(
        database,
        cred_id[0..cred_id_len],
        grantee_id[0..grantee_len],
        out_buf[0..out_cap],
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Revoke a share (grantor check enforced).
export fn podos_credential_share_revoke(
    db_handle: ?*anyopaque,
    share_id: [*]const u8,
    share_id_len: u32,
    grantor_id: [*]const u8,
    grantor_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    credential.shareRevoke(
        database,
        share_id[0..share_id_len],
        grantor_id[0..grantor_len],
    ) catch return -2;
    return 0;
}

/// Append a credential audit record. Returns 0 on success.
/// Caller must treat non-zero as a fail-safe abort condition.
export fn podos_credential_audit_append(
    db_handle: ?*anyopaque,
    cred_id: [*]const u8,
    cred_id_len: u32,
    operation: [*]const u8,
    op_len: u32,
    actor_id: [*]const u8,
    actor_len: u32,
    tool_name: ?[*]const u8,
    tool_len: u32,
    share_id: ?[*]const u8,
    share_len: u32,
    ip_fp: ?[*]const u8,
    ip_len: u32,
    decision: [*]const u8,
    decision_len: u32,
    details_json: ?[*]const u8,
    details_len: u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const tn = if (tool_name != null and tool_len > 0) tool_name.?[0..tool_len] else null;
    const sid = if (share_id != null and share_len > 0) share_id.?[0..share_len] else null;
    const ipfp = if (ip_fp != null and ip_len > 0) ip_fp.?[0..ip_len] else null;
    const dj = if (details_json != null and details_len > 0) details_json.?[0..details_len] else null;
    credential_audit.append(
        database,
        cred_id[0..cred_id_len],
        operation[0..op_len],
        actor_id[0..actor_len],
        tn, sid, ipfp,
        decision[0..decision_len],
        dj,
    ) catch return -2;
    return 0;
}

/// Query audit log for a credential. Returns JSON array in out_buf.
export fn podos_credential_audit_query(
    db_handle: ?*anyopaque,
    cred_id: [*]const u8,
    cred_id_len: u32,
    limit_n: u32,
    out_buf: [*]u8,
    out_cap: u32,
    out_len: *u32,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const written = credential_audit.query(
        database,
        cred_id[0..cred_id_len],
        limit_n,
        out_buf[0..out_cap],
    ) catch return -2;
    out_len.* = @intCast(written);
    return 0;
}

/// Sweep expired shares and mark them revoked. For cron use.
export fn podos_credential_sweep_expiry(
    db_handle: ?*anyopaque,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    credential_audit.sweepExpiredShares(database) catch return -2;
    return 0;
}

/// Also init credential tables when opening the DB. (helper called from podos_db_open callers)
export fn podos_credential_init_tables(
    db_handle: ?*anyopaque,
) callconv(.c) i32 {
    const database: *db.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    database.initCredentialTables() catch return -2;
    return 0;
}
