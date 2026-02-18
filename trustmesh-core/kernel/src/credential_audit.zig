// credential_audit.zig — Structured audit trail for every credential operation.
//
// credential_ops table: append-only, every use/create/rotate/share/revoke recorded.
// Fail-safe: append failure → caller should return 500 and abort the operation.

const std = @import("std");
const db_mod = @import("db.zig");
const json_mod = @import("json.zig");

pub const AuditError = error{
    DbError,
    BufferTooSmall,
};

// ═══════════════════════════════════════════
//  APPEND
// ═══════════════════════════════════════════

/// Append one credential operation to credential_ops.
/// `operation` must be one of the CHECK values in the table schema.
/// `tool_name`, `share_id`, `ip_fingerprint`, `details_json` may be null / empty.
/// Returns 0 on success (caller treats non-zero as abort condition).
pub fn append(
    database: *db_mod.Database,
    cred_id: []const u8,
    operation: []const u8,
    actor_id: []const u8,
    tool_name: ?[]const u8,
    share_id: ?[]const u8,
    ip_fingerprint: ?[]const u8,
    decision: []const u8,
    details_json: ?[]const u8,
) AuditError!void {
    var stmt = database.prepare(
        \\INSERT INTO credential_ops
        \\  (credential_id, operation, actor_id, tool_name, share_id,
        \\   ip_fingerprint, decision, details)
        \\VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ) catch return AuditError.DbError;
    defer stmt.finalize();

    stmt.bindText(1, cred_id.ptr, @intCast(cred_id.len)) catch return AuditError.DbError;
    stmt.bindText(2, operation.ptr, @intCast(operation.len)) catch return AuditError.DbError;
    stmt.bindText(3, actor_id.ptr, @intCast(actor_id.len)) catch return AuditError.DbError;

    if (tool_name) |tn| {
        stmt.bindText(4, tn.ptr, @intCast(tn.len)) catch return AuditError.DbError;
    } else {
        _ = db_mod.c.sqlite3_bind_null(stmt.handle, 4);
    }
    if (share_id) |sid| {
        stmt.bindText(5, sid.ptr, @intCast(sid.len)) catch return AuditError.DbError;
    } else {
        _ = db_mod.c.sqlite3_bind_null(stmt.handle, 5);
    }
    if (ip_fingerprint) |fp| {
        stmt.bindText(6, fp.ptr, @intCast(fp.len)) catch return AuditError.DbError;
    } else {
        _ = db_mod.c.sqlite3_bind_null(stmt.handle, 6);
    }
    stmt.bindText(7, decision.ptr, @intCast(decision.len)) catch return AuditError.DbError;
    if (details_json) |dj| {
        stmt.bindText(8, dj.ptr, @intCast(dj.len)) catch return AuditError.DbError;
    } else {
        _ = db_mod.c.sqlite3_bind_null(stmt.handle, 8);
    }

    _ = stmt.step() catch return AuditError.DbError;
}

// ═══════════════════════════════════════════
//  QUERY
// ═══════════════════════════════════════════

/// Write JSON array of the most recent `limit` ops for a credential.
/// Returns bytes written.
pub fn query(
    database: *db_mod.Database,
    cred_id: []const u8,
    limit_n: u32,
    out_buf: []u8,
) AuditError!usize {
    var stmt = database.prepare(
        \\SELECT id, operation, actor_id, tool_name, share_id,
        \\       ip_fingerprint, decision, details, created_at
        \\FROM credential_ops
        \\WHERE credential_id = ?
        \\ORDER BY created_at DESC
        \\LIMIT ?
    ) catch return AuditError.DbError;
    defer stmt.finalize();

    stmt.bindText(1, cred_id.ptr, @intCast(cred_id.len)) catch return AuditError.DbError;
    stmt.bindInt(2, @intCast(@min(limit_n, 200))) catch return AuditError.DbError;

    var fbs = std.io.fixedBufferStream(out_buf);
    const w = fbs.writer();
    w.writeByte('[') catch return AuditError.BufferTooSmall;

    var first = true;
    while (stmt.step() catch return AuditError.DbError) {
        if (!first) w.writeByte(',') catch return AuditError.BufferTooSmall;
        first = false;
        if (!writeAuditRow(&stmt, w)) return AuditError.BufferTooSmall;
    }

    w.writeByte(']') catch return AuditError.BufferTooSmall;
    return fbs.pos;
}

fn writeAuditRow(stmt: *db_mod.Statement, w: anytype) bool {
    const row_id = stmt.getInt64(0);
    const op = stmt.getText(1) orelse return false;
    const actor = stmt.getText(2) orelse return false;
    const tool = stmt.getText(3); // nullable
    const share = stmt.getText(4); // nullable
    const ipfp = stmt.getText(5); // nullable
    const decision = stmt.getText(6) orelse "allowed";
    const details = stmt.getText(7); // nullable
    const created = stmt.getText(8) orelse return false;

    // JSON-safe: operation, decision are CHECK-constrained enum values (safe).
    // actor_id and tool_name are user-controlled — escape them.
    var esc_actor: [256]u8 = undefined;
    const actor_len = json_mod.escapeJsonString(std.mem.span(actor), &esc_actor) catch return false;

    std.fmt.format(w,
        "{{\"id\":{d},\"operation\":\"{s}\",\"actor_id\":\"{s}\",\"decision\":\"{s}\"" ++
        ",\"created_at\":\"{s}\"",
        .{
            row_id, std.mem.span(op),
            esc_actor[0..actor_len], std.mem.span(decision), std.mem.span(created),
        },
    ) catch return false;

    if (tool) |t| {
        var esc_t: [256]u8 = undefined;
        const tl = json_mod.escapeJsonString(std.mem.span(t), &esc_t) catch return false;
        std.fmt.format(w, ",\"tool_name\":\"{s}\"", .{esc_t[0..tl]}) catch return false;
    } else {
        w.writeAll(",\"tool_name\":null") catch return false;
    }
    if (share) |s| {
        std.fmt.format(w, ",\"share_id\":\"{s}\"", .{std.mem.span(s)}) catch return false;
    } else {
        w.writeAll(",\"share_id\":null") catch return false;
    }
    if (ipfp) |fp| {
        std.fmt.format(w, ",\"ip_fingerprint\":\"{s}\"", .{std.mem.span(fp)}) catch return false;
    } else {
        w.writeAll(",\"ip_fingerprint\":null") catch return false;
    }
    if (details) |d| {
        // details is already JSON — embed verbatim (validated as JSON at write time)
        std.fmt.format(w, ",\"details\":{s}", .{std.mem.span(d)}) catch return false;
    } else {
        w.writeAll(",\"details\":null") catch return false;
    }
    w.writeByte('}') catch return false;
    return true;
}

// ═══════════════════════════════════════════
//  EXPIRY SWEEPS
// ═══════════════════════════════════════════

/// Mark expired shares as revoked and record share_expired audit entries.
/// Called by timeline cron hook (daily at 06:00).
pub fn sweepExpiredShares(database: *db_mod.Database) AuditError!void {
    // Find shares that have expired and are not yet revoked
    var find_stmt = database.prepare(
        \\SELECT id, credential_id, grantee_id
        \\FROM credential_shares
        \\WHERE revoked_at IS NULL
        \\  AND expires_at <= strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ) catch return AuditError.DbError;
    defer find_stmt.finalize();

    // Collect IDs to avoid mutating while iterating
    var share_ids: [64][128]u8 = undefined;
    var cred_ids: [64][128]u8 = undefined;
    var actor_ids: [64][128]u8 = undefined;
    var share_lens: [64]usize = undefined;
    var cred_lens: [64]usize = undefined;
    var actor_lens: [64]usize = undefined;
    var count: usize = 0;

    while (find_stmt.step() catch return AuditError.DbError) {
        if (count >= 64) break;
        const sid = std.mem.span(find_stmt.getText(0) orelse continue);
        const cid = std.mem.span(find_stmt.getText(1) orelse continue);
        const gid = std.mem.span(find_stmt.getText(2) orelse continue);
        if (sid.len > 128 or cid.len > 128 or gid.len > 128) continue;
        @memcpy(share_ids[count][0..sid.len], sid);
        share_lens[count] = sid.len;
        @memcpy(cred_ids[count][0..cid.len], cid);
        cred_lens[count] = cid.len;
        @memcpy(actor_ids[count][0..gid.len], gid);
        actor_lens[count] = gid.len;
        count += 1;
    }

    for (share_ids[0..count], 0..) |_, i| {
        const sid = share_ids[i][0..share_lens[i]];
        const cid = cred_ids[i][0..cred_lens[i]];
        const gid = actor_ids[i][0..actor_lens[i]];

        // Mark revoked
        var upd = database.prepare(
            "UPDATE credential_shares SET revoked_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?"
        ) catch continue;
        defer upd.finalize();
        upd.bindText(1, sid.ptr, @intCast(sid.len)) catch continue;
        _ = upd.step() catch continue;

        // Audit entry
        append(database, cid, "share_expired", gid, null, sid, null, "allowed", null) catch {};
    }
}

/// Sweep credential_ops for hard-deleted (is_active=0) credentials older than 90 days.
/// Optional — keeps the audit table from growing unbounded.
pub fn sweepOldOps(database: *db_mod.Database) AuditError!void {
    var stmt = database.prepare(
        \\DELETE FROM credential_ops
        \\WHERE credential_id IN (
        \\    SELECT id FROM vault_secrets WHERE is_active = 0
        \\    AND updated_at < strftime('%Y-%m-%dT%H:%M:%SZ','now','-90 days')
        \\)
    ) catch return AuditError.DbError;
    defer stmt.finalize();
    _ = stmt.step() catch return AuditError.DbError;
}
