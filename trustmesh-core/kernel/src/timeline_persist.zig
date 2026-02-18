// timeline_persist.zig — SQLite persistence for timeline entries + sync event inbox/outbox.
//
// This module is intentionally minimal and allocator-free:
// - Stores the original entry "spec" JSON provided by the host (Python) for crash/restart restore.
// - Provides an outbox of JSON events keyed by engine tick for catch-up sync.
// - Provides an inbox of JSON events keyed by event_id for dedupe.
//
// JSON values are treated as opaque and are written back out as raw JSON objects.

const std = @import("std");
const types = @import("types.zig");
const db_mod = @import("db.zig");

const Database = db_mod.Database;
const Statement = db_mod.Statement;
const SqliteError = db_mod.SqliteError;

pub const PersistError = error{
    InitFailed,
    UpsertFailed,
    UpdateFailed,
    TransitionAppendFailed,
    DeleteFailed,
    LoadFailed,
    OwnerLookupFailed,
    OutboxAppendFailed,
    OutboxPullFailed,
    InboxMarkFailed,
    BufferTooSmall,
} || SqliteError;

pub fn initTables(database: *Database) PersistError!void {
    // timeline_entries: durable storage of entry specs for restore.
    database.exec(
        "CREATE TABLE IF NOT EXISTS timeline_entries (" ++
            "entry_id TEXT PRIMARY KEY, " ++
            "owner_id TEXT NOT NULL, " ++
            "state INTEGER NOT NULL, " ++
            "spec_json TEXT NOT NULL, " ++
            "created_at_ms INTEGER NOT NULL, " ++
            "updated_at_ms INTEGER NOT NULL" ++
            ")",
    ) catch return PersistError.InitFailed;
    database.exec("CREATE INDEX IF NOT EXISTS idx_timeline_entries_owner ON timeline_entries(owner_id)") catch {};
    database.exec("CREATE INDEX IF NOT EXISTS idx_timeline_entries_state ON timeline_entries(state)") catch {};

    // timeline_outbox: append-only sync events (raw JSON), ordered by tick.
    database.exec(
        "CREATE TABLE IF NOT EXISTS timeline_outbox (" ++
            "id INTEGER PRIMARY KEY AUTOINCREMENT, " ++
            "tick INTEGER NOT NULL, " ++
            "created_at_ms INTEGER NOT NULL, " ++
            "event_json TEXT NOT NULL" ++
            ")",
    ) catch return PersistError.InitFailed;
    database.exec("CREATE INDEX IF NOT EXISTS idx_timeline_outbox_tick ON timeline_outbox(tick)") catch {};

    // timeline_inbox: dedupe + audit of received sync events (raw JSON), keyed by event_id.
    database.exec(
        "CREATE TABLE IF NOT EXISTS timeline_inbox (" ++
            "event_id TEXT PRIMARY KEY, " ++
            "received_at_ms INTEGER NOT NULL, " ++
            "event_json TEXT NOT NULL" ++
            ")",
    ) catch return PersistError.InitFailed;

    // timeline_transitions: append-only audit trail of state transitions (authoritative).
    database.exec(
        "CREATE TABLE IF NOT EXISTS timeline_transitions (" ++
            "id INTEGER PRIMARY KEY AUTOINCREMENT, " ++
            "tick INTEGER NOT NULL, " ++
            "at_ms INTEGER NOT NULL, " ++
            "entry_id TEXT NOT NULL, " ++
            "from_state INTEGER NOT NULL, " ++
            "to_state INTEGER NOT NULL, " ++
            "trigger_kind INTEGER NOT NULL" ++
            ")",
    ) catch return PersistError.InitFailed;
    database.exec("CREATE INDEX IF NOT EXISTS idx_timeline_transitions_tick ON timeline_transitions(tick)") catch {};
    database.exec("CREATE INDEX IF NOT EXISTS idx_timeline_transitions_entry ON timeline_transitions(entry_id)") catch {};
}

pub fn upsertEntry(
    database: *Database,
    entry_id: [*]const u8,
    entry_id_len: usize,
    owner_id: [*]const u8,
    owner_id_len: usize,
    state: i32,
    spec_json: [*]const u8,
    spec_len: usize,
) PersistError!void {
    const now_ms: i64 = types.nowMs();
    // Preserve created_at_ms on updates.
    var stmt = database.prepare(
        "INSERT INTO timeline_entries(entry_id, owner_id, state, spec_json, created_at_ms, updated_at_ms) " ++
            "VALUES(?, ?, ?, ?, ?, ?) " ++
            "ON CONFLICT(entry_id) DO UPDATE SET " ++
            "owner_id=excluded.owner_id, " ++
            "state=excluded.state, " ++
            "spec_json=excluded.spec_json, " ++
            "updated_at_ms=excluded.updated_at_ms",
    ) catch return PersistError.UpsertFailed;
    defer stmt.finalize();

    stmt.bindText(1, entry_id, @intCast(entry_id_len)) catch return PersistError.UpsertFailed;
    stmt.bindText(2, owner_id, @intCast(owner_id_len)) catch return PersistError.UpsertFailed;
    stmt.bindInt(3, @intCast(state)) catch return PersistError.UpsertFailed;
    stmt.bindText(4, spec_json, @intCast(spec_len)) catch return PersistError.UpsertFailed;
    stmt.bindInt64(5, now_ms) catch return PersistError.UpsertFailed;
    stmt.bindInt64(6, now_ms) catch return PersistError.UpsertFailed;

    _ = stmt.step() catch return PersistError.UpsertFailed;
}

pub fn updateEntryState(
    database: *Database,
    entry_id: [*]const u8,
    entry_id_len: usize,
    state: i32,
) PersistError!void {
    const now_ms: i64 = types.nowMs();
    var stmt = database.prepare(
        "UPDATE timeline_entries SET state = ?, updated_at_ms = ? WHERE entry_id = ?",
    ) catch return PersistError.UpdateFailed;
    defer stmt.finalize();

    stmt.bindInt(1, @intCast(state)) catch return PersistError.UpdateFailed;
    stmt.bindInt64(2, now_ms) catch return PersistError.UpdateFailed;
    stmt.bindText(3, entry_id, @intCast(entry_id_len)) catch return PersistError.UpdateFailed;

    _ = stmt.step() catch return PersistError.UpdateFailed;
}

pub fn appendTransition(
    database: *Database,
    tick: u64,
    at_ms: i64,
    entry_id: [*]const u8,
    entry_id_len: usize,
    from_state: i32,
    to_state: i32,
    trigger_kind: i32,
) PersistError!void {
    var stmt = database.prepare(
        "INSERT INTO timeline_transitions(tick, at_ms, entry_id, from_state, to_state, trigger_kind) VALUES(?, ?, ?, ?, ?, ?)",
    ) catch return PersistError.TransitionAppendFailed;
    defer stmt.finalize();

    stmt.bindInt64(1, @intCast(tick)) catch return PersistError.TransitionAppendFailed;
    stmt.bindInt64(2, at_ms) catch return PersistError.TransitionAppendFailed;
    stmt.bindText(3, entry_id, @intCast(entry_id_len)) catch return PersistError.TransitionAppendFailed;
    stmt.bindInt(4, @intCast(from_state)) catch return PersistError.TransitionAppendFailed;
    stmt.bindInt(5, @intCast(to_state)) catch return PersistError.TransitionAppendFailed;
    stmt.bindInt(6, @intCast(trigger_kind)) catch return PersistError.TransitionAppendFailed;

    _ = stmt.step() catch return PersistError.TransitionAppendFailed;
}

pub fn deleteEntry(
    database: *Database,
    entry_id: [*]const u8,
    entry_id_len: usize,
) PersistError!void {
    var stmt = database.prepare("DELETE FROM timeline_entries WHERE entry_id = ?") catch return PersistError.DeleteFailed;
    defer stmt.finalize();
    stmt.bindText(1, entry_id, @intCast(entry_id_len)) catch return PersistError.DeleteFailed;
    _ = stmt.step() catch return PersistError.DeleteFailed;
}

pub fn getEntryOwner(
    database: *Database,
    entry_id: [*]const u8,
    entry_id_len: usize,
    out_buf: [*]u8,
    out_capacity: usize,
) PersistError!usize {
    var stmt = database.prepare("SELECT owner_id FROM timeline_entries WHERE entry_id = ? LIMIT 1") catch return PersistError.OwnerLookupFailed;
    defer stmt.finalize();
    stmt.bindText(1, entry_id, @intCast(entry_id_len)) catch return PersistError.OwnerLookupFailed;

    const has_row = stmt.step() catch return PersistError.OwnerLookupFailed;
    if (!has_row) return 0;

    const owner_ptr = stmt.getText(0) orelse return 0;
    var owner_len: usize = 0;
    while (owner_ptr[owner_len] != 0) : (owner_len += 1) {}

    if (owner_len > out_capacity) return PersistError.BufferTooSmall;
    @memcpy(out_buf[0..owner_len], owner_ptr[0..owner_len]);
    return owner_len;
}

pub fn loadEntrySpecsJson(
    database: *Database,
    owner_id: ?[*]const u8,
    owner_id_len: usize,
    out_buf: [*]u8,
    out_capacity: usize,
) PersistError!usize {
    const sql_all =
        "SELECT spec_json FROM timeline_entries ORDER BY updated_at_ms ASC";
    const sql_owner =
        "SELECT spec_json FROM timeline_entries WHERE owner_id = ? ORDER BY updated_at_ms ASC";

    var stmt = database.prepare(if (owner_id != null and owner_id_len > 0) sql_owner else sql_all) catch return PersistError.LoadFailed;
    defer stmt.finalize();
    if (owner_id != null and owner_id_len > 0) {
        stmt.bindText(1, owner_id.?, @intCast(owner_id_len)) catch return PersistError.LoadFailed;
    }

    var pos: usize = 0;
    if (pos >= out_capacity) return PersistError.BufferTooSmall;
    out_buf[pos] = '[';
    pos += 1;

    var count: u32 = 0;
    while (stmt.step() catch return PersistError.LoadFailed) {
        const json_ptr = stmt.getText(0) orelse continue;
        var json_len: usize = 0;
        while (json_ptr[json_len] != 0) : (json_len += 1) {}
        if (json_len == 0) continue;

        if (count > 0) {
            if (pos >= out_capacity) return PersistError.BufferTooSmall;
            out_buf[pos] = ',';
            pos += 1;
        }

        if (pos + json_len >= out_capacity) return PersistError.BufferTooSmall;
        @memcpy(out_buf[pos..][0..json_len], json_ptr[0..json_len]);
        pos += json_len;
        count += 1;
    }

    if (pos >= out_capacity) return PersistError.BufferTooSmall;
    out_buf[pos] = ']';
    pos += 1;
    return pos;
}

pub fn appendOutboxEvent(
    database: *Database,
    tick: u64,
    event_json: [*]const u8,
    event_json_len: usize,
) PersistError!void {
    const now_ms: i64 = types.nowMs();
    var stmt = database.prepare(
        "INSERT INTO timeline_outbox(tick, created_at_ms, event_json) VALUES(?, ?, ?)",
    ) catch return PersistError.OutboxAppendFailed;
    defer stmt.finalize();

    stmt.bindInt64(1, @intCast(tick)) catch return PersistError.OutboxAppendFailed;
    stmt.bindInt64(2, now_ms) catch return PersistError.OutboxAppendFailed;
    stmt.bindText(3, event_json, @intCast(event_json_len)) catch return PersistError.OutboxAppendFailed;
    _ = stmt.step() catch return PersistError.OutboxAppendFailed;
}

pub fn pullOutboxEventsJson(
    database: *Database,
    since_tick: u64,
    out_buf: [*]u8,
    out_capacity: usize,
) PersistError!usize {
    var stmt = database.prepare(
        "SELECT event_json FROM timeline_outbox WHERE tick > ? ORDER BY tick ASC, id ASC LIMIT 1000",
    ) catch return PersistError.OutboxPullFailed;
    defer stmt.finalize();
    stmt.bindInt64(1, @intCast(since_tick)) catch return PersistError.OutboxPullFailed;

    var pos: usize = 0;
    if (pos >= out_capacity) return PersistError.BufferTooSmall;
    out_buf[pos] = '[';
    pos += 1;

    var count: u32 = 0;
    while (stmt.step() catch return PersistError.OutboxPullFailed) {
        const json_ptr = stmt.getText(0) orelse continue;
        var json_len: usize = 0;
        while (json_ptr[json_len] != 0) : (json_len += 1) {}
        if (json_len == 0) continue;

        if (count > 0) {
            if (pos >= out_capacity) return PersistError.BufferTooSmall;
            out_buf[pos] = ',';
            pos += 1;
        }

        if (pos + json_len >= out_capacity) return PersistError.BufferTooSmall;
        @memcpy(out_buf[pos..][0..json_len], json_ptr[0..json_len]);
        pos += json_len;
        count += 1;
    }

    if (pos >= out_capacity) return PersistError.BufferTooSmall;
    out_buf[pos] = ']';
    pos += 1;
    return pos;
}

pub fn markInboxEvent(
    database: *Database,
    event_id: [*]const u8,
    event_id_len: usize,
    event_json: [*]const u8,
    event_json_len: usize,
) PersistError!void {
    const now_ms: i64 = types.nowMs();
    var stmt = database.prepare(
        "INSERT OR IGNORE INTO timeline_inbox(event_id, received_at_ms, event_json) VALUES(?, ?, ?)",
    ) catch return PersistError.InboxMarkFailed;
    defer stmt.finalize();

    stmt.bindText(1, event_id, @intCast(event_id_len)) catch return PersistError.InboxMarkFailed;
    stmt.bindInt64(2, now_ms) catch return PersistError.InboxMarkFailed;
    stmt.bindText(3, event_json, @intCast(event_json_len)) catch return PersistError.InboxMarkFailed;
    _ = stmt.step() catch return PersistError.InboxMarkFailed;
}
