// fts.zig — FTS5 full-text search operations for capsule retrieval.
// Replaces ChromaDB with SQLite FTS5 BM25 keyword search.
// One flat table (not per-category collections); category is a column.

const std = @import("std");
const db_mod = @import("db.zig");
const Database = db_mod.Database;
const Statement = db_mod.Statement;
const SqliteError = db_mod.SqliteError;

pub const FtsError = error{
    InitFailed,
    UpsertFailed,
    DeleteFailed,
    SearchFailed,
    ResetFailed,
    BufferTooSmall,
} || SqliteError;

/// Create the FTS5 virtual table if it doesn't exist.
pub fn initFtsTable(database: *Database) FtsError!void {
    database.exec(
        "CREATE VIRTUAL TABLE IF NOT EXISTS capsule_fts USING fts5(" ++
            "capsule_id UNINDEXED, " ++
            "title, " ++
            "content, " ++
            "category UNINDEXED, " ++
            "tokenize='porter unicode61'" ++
            ")",
    ) catch return FtsError.InitFailed;
}

/// Upsert a capsule into the FTS5 index (DELETE + INSERT, since FTS5 doesn't support UPDATE well).
pub fn upsertCapsule(
    database: *Database,
    capsule_id: [*]const u8,
    id_len: usize,
    title: [*]const u8,
    title_len: usize,
    content: [*]const u8,
    content_len: usize,
    category: [*]const u8,
    category_len: usize,
) FtsError!void {
    // Delete existing entry first
    var del_stmt = database.prepare("DELETE FROM capsule_fts WHERE capsule_id = ?") catch return FtsError.UpsertFailed;
    defer del_stmt.finalize();
    del_stmt.bindText(1, capsule_id, @intCast(id_len)) catch return FtsError.UpsertFailed;
    _ = del_stmt.step() catch return FtsError.UpsertFailed;

    // Insert new entry
    var ins_stmt = database.prepare(
        "INSERT INTO capsule_fts(capsule_id, title, content, category) VALUES(?, ?, ?, ?)",
    ) catch return FtsError.UpsertFailed;
    defer ins_stmt.finalize();
    ins_stmt.bindText(1, capsule_id, @intCast(id_len)) catch return FtsError.UpsertFailed;
    ins_stmt.bindText(2, title, @intCast(title_len)) catch return FtsError.UpsertFailed;
    ins_stmt.bindText(3, content, @intCast(content_len)) catch return FtsError.UpsertFailed;
    ins_stmt.bindText(4, category, @intCast(category_len)) catch return FtsError.UpsertFailed;
    _ = ins_stmt.step() catch return FtsError.UpsertFailed;
}

/// Delete a capsule from the FTS5 index.
pub fn deleteCapsule(
    database: *Database,
    capsule_id: [*]const u8,
    id_len: usize,
) FtsError!void {
    var stmt = database.prepare("DELETE FROM capsule_fts WHERE capsule_id = ?") catch return FtsError.DeleteFailed;
    defer stmt.finalize();
    stmt.bindText(1, capsule_id, @intCast(id_len)) catch return FtsError.DeleteFailed;
    _ = stmt.step() catch return FtsError.DeleteFailed;
}

/// Search capsules using FTS5 MATCH with BM25 ranking.
/// `accessible_ids_json` is a JSON array of capsule IDs, e.g. '["id1","id2"]'.
/// Results written to `out_buf` as a JSON array: [{"id":"...","rank":0.5}, ...]
/// Returns bytes written to out_buf, or negative error.
pub fn searchCapsules(
    database: *Database,
    query: [*]const u8,
    query_len: usize,
    accessible_ids_json: [*]const u8,
    ids_len: usize,
    top_k: u32,
    out_buf: [*]u8,
    out_capacity: usize,
) FtsError!usize {
    // Build the SQL: we use a subquery with json_each to filter by accessible IDs.
    // FTS5 MATCH uses bm25() for ranking (lower = better match).
    //
    // SELECT capsule_id, bm25(capsule_fts) as rank
    // FROM capsule_fts
    // WHERE capsule_fts MATCH ?
    //   AND capsule_id IN (SELECT value FROM json_each(?))
    // ORDER BY rank
    // LIMIT ?
    var stmt = database.prepare(
        "SELECT capsule_id, bm25(capsule_fts) as rank " ++
            "FROM capsule_fts " ++
            "WHERE capsule_fts MATCH ? " ++
            "AND capsule_id IN (SELECT value FROM json_each(?)) " ++
            "ORDER BY rank " ++
            "LIMIT ?",
    ) catch return FtsError.SearchFailed;
    defer stmt.finalize();

    stmt.bindText(1, query, @intCast(query_len)) catch return FtsError.SearchFailed;
    stmt.bindText(2, accessible_ids_json, @intCast(ids_len)) catch return FtsError.SearchFailed;
    stmt.bindInt(3, @intCast(top_k)) catch return FtsError.SearchFailed;

    // Build JSON output manually to avoid allocator dependency
    var pos: usize = 0;
    if (pos >= out_capacity) return FtsError.BufferTooSmall;
    out_buf[pos] = '[';
    pos += 1;
    var count: u32 = 0;

    while (stmt.step() catch return FtsError.SearchFailed) {
        const id_ptr = stmt.getText(0) orelse continue;
        const rank = stmt.getDouble(1);

        // Determine ID length (null-terminated)
        var id_len: usize = 0;
        while (id_ptr[id_len] != 0) : (id_len += 1) {}

        // Format: {"id":"...","rank":-1.234}
        // We need: comma + {"id":"" + id + ","rank": + rank_str + }
        if (count > 0) {
            if (pos >= out_capacity) return FtsError.BufferTooSmall;
            out_buf[pos] = ',';
            pos += 1;
        }

        // Write {"id":"
        const prefix = "{\"id\":\"";
        if (pos + prefix.len >= out_capacity) return FtsError.BufferTooSmall;
        @memcpy(out_buf[pos..][0..prefix.len], prefix);
        pos += prefix.len;

        // Write the capsule ID
        if (pos + id_len >= out_capacity) return FtsError.BufferTooSmall;
        @memcpy(out_buf[pos..][0..id_len], id_ptr[0..id_len]);
        pos += id_len;

        // Write ","rank":
        const mid = "\",\"rank\":";
        if (pos + mid.len >= out_capacity) return FtsError.BufferTooSmall;
        @memcpy(out_buf[pos..][0..mid.len], mid);
        pos += mid.len;

        // Format rank as float string using bufPrint
        var rank_buf: [32]u8 = undefined;
        const rank_slice = std.fmt.bufPrint(&rank_buf, "{d:.6}", .{rank}) catch {
            // Fallback: write "0"
            if (pos >= out_capacity) return FtsError.BufferTooSmall;
            out_buf[pos] = '0';
            pos += 1;
            if (pos >= out_capacity) return FtsError.BufferTooSmall;
            out_buf[pos] = '}';
            pos += 1;
            count += 1;
            continue;
        };
        if (pos + rank_slice.len >= out_capacity) return FtsError.BufferTooSmall;
        @memcpy(out_buf[pos..][0..rank_slice.len], rank_slice);
        pos += rank_slice.len;

        // Write closing }
        if (pos >= out_capacity) return FtsError.BufferTooSmall;
        out_buf[pos] = '}';
        pos += 1;

        count += 1;
    }

    // Close the JSON array
    if (pos >= out_capacity) return FtsError.BufferTooSmall;
    out_buf[pos] = ']';
    pos += 1;

    return pos;
}

/// Drop and recreate the FTS5 table (for testing/seeding).
pub fn resetFts(database: *Database) FtsError!void {
    database.exec("DROP TABLE IF EXISTS capsule_fts") catch return FtsError.ResetFailed;
    try initFtsTable(database);
}
