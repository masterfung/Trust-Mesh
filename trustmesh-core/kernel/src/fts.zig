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

/// Upsert a capsule into the FTS5 index (DELETE + INSERT in a single transaction).
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
    // Wrap DELETE + INSERT in a single transaction for atomicity
    database.exec("BEGIN IMMEDIATE") catch return FtsError.UpsertFailed;
    errdefer database.exec("ROLLBACK") catch {};

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

    database.exec("COMMIT") catch return FtsError.UpsertFailed;
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

/// Maximum query length to prevent abuse.
pub const MAX_QUERY_LEN: usize = 500;

/// FTS5 operator words that must be stripped from user queries.
const FTS5_OPERATORS = [_][]const u8{ "AND", "OR", "NOT", "NEAR" };

/// Sanitize a query: strip FTS5 operators, enforce length limit.
/// Returns bytes written to out_buf (OR-joined words).
fn sanitizeQuery(raw: []const u8, out: []u8) usize {
    const limited = if (raw.len > MAX_QUERY_LEN) raw[0..MAX_QUERY_LEN] else raw;
    var pos: usize = 0;
    var word_count: usize = 0;
    var it = std.mem.splitAny(u8, limited, " \t\n\r");
    while (it.next()) |word| {
        if (word.len == 0) continue;
        // Skip FTS5 operators (case-insensitive)
        var skip = false;
        for (FTS5_OPERATORS) |op| {
            if (std.ascii.eqlIgnoreCase(word, op)) {
                skip = true;
                break;
            }
        }
        if (skip) continue;
        // Add OR separator between words
        if (word_count > 0) {
            if (pos + 4 >= out.len) break;
            @memcpy(out[pos..][0..4], " OR ");
            pos += 4;
        }
        if (pos + word.len >= out.len) break;
        @memcpy(out[pos..][0..word.len], word);
        pos += word.len;
        word_count += 1;
    }
    return pos;
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
    // Sanitize query: strip FTS5 operators, enforce length limit
    var sanitized_buf: [MAX_QUERY_LEN * 2]u8 = undefined;
    const san_len = sanitizeQuery(query[0..query_len], &sanitized_buf);
    if (san_len == 0) {
        // Empty query after sanitization — return empty array
        if (out_capacity >= 2) {
            out_buf[0] = '[';
            out_buf[1] = ']';
            return 2;
        }
        return FtsError.BufferTooSmall;
    }

    var stmt = database.prepare(
        "SELECT capsule_id, bm25(capsule_fts) as rank " ++
            "FROM capsule_fts " ++
            "WHERE capsule_fts MATCH ? " ++
            "AND capsule_id IN (SELECT value FROM json_each(?)) " ++
            "ORDER BY rank " ++
            "LIMIT ?",
    ) catch return FtsError.SearchFailed;
    defer stmt.finalize();

    stmt.bindText(1, &sanitized_buf, @intCast(san_len)) catch return FtsError.SearchFailed;
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
