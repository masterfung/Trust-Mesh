// credential.zig — Vault credential store.
//
// vault_secrets table:  searchable envelope, encrypted secret blob.
// credential_shares:    time-boxed delegation grants.
// credential_fts:       FTS5 on name+service ONLY — never on secret values.

const std = @import("std");
const db_mod = @import("db.zig");
const json_mod = @import("json.zig");

pub const CredentialError = error{
    NotFound,
    PermissionDenied,
    CredentialExpired,
    BufferTooSmall,
    DbError,
    SerializeFailed,
    ShareExpired,
    ShareRevoked,
    ShareMaxUses,
};

// ═══════════════════════════════════════════
//  CREATE
// ═══════════════════════════════════════════

/// Insert a new credential into vault_secrets + credential_fts.
/// `id` must be a UUID/unique string provided by the caller.
/// `secret_encrypted` is already encrypted — never stored as plaintext.
/// Returns 0 on success, negative on error.
pub fn create(
    database: *db_mod.Database,
    id: []const u8,
    owner_id: []const u8,
    name: []const u8,
    service: []const u8,
    category: []const u8,
    secret_encrypted: []const u8,
    scoped_tools_json: []const u8,
    expires_at: ?[]const u8,
) db_mod.SqliteError!void {
    {
        var stmt = try database.prepare(
            \\INSERT INTO vault_secrets
            \\  (id, owner_id, name, service, category, secret_encrypted,
            \\   scoped_tools, expires_at)
            \\VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        );
        defer stmt.finalize();
        try stmt.bindText(1, id.ptr, @intCast(id.len));
        try stmt.bindText(2, owner_id.ptr, @intCast(owner_id.len));
        try stmt.bindText(3, name.ptr, @intCast(name.len));
        try stmt.bindText(4, service.ptr, @intCast(service.len));
        try stmt.bindText(5, category.ptr, @intCast(category.len));
        // Bind encrypted blob
        const rc = db_mod.c.sqlite3_bind_blob(
            stmt.handle,
            6,
            secret_encrypted.ptr,
            @intCast(secret_encrypted.len),
            null, // SQLITE_STATIC — safe, step() called immediately
        );
        if (rc != db_mod.c.SQLITE_OK) return db_mod.SqliteError.BindFailed;
        try stmt.bindText(7, scoped_tools_json.ptr, @intCast(scoped_tools_json.len));
        if (expires_at) |ea| {
            try stmt.bindText(8, ea.ptr, @intCast(ea.len));
        } else {
            _ = db_mod.c.sqlite3_bind_null(stmt.handle, 8);
        }
        _ = try stmt.step();
    }
    // FTS: index name + service (never the secret)
    {
        var fts_stmt = try database.prepare(
            "INSERT INTO credential_fts(credential_id, name, service, category) VALUES (?, ?, ?, ?)"
        );
        defer fts_stmt.finalize();
        try fts_stmt.bindText(1, id.ptr, @intCast(id.len));
        try fts_stmt.bindText(2, name.ptr, @intCast(name.len));
        try fts_stmt.bindText(3, service.ptr, @intCast(service.len));
        try fts_stmt.bindText(4, category.ptr, @intCast(category.len));
        _ = try fts_stmt.step();
    }
}

// ═══════════════════════════════════════════
//  LIST (metadata only, no secrets)
// ═══════════════════════════════════════════

/// Write JSON array of credential metadata for owner into out_buf.
/// Returns bytes written. Secret values are NEVER included.
pub fn list(
    database: *db_mod.Database,
    owner_id: []const u8,
    out_buf: []u8,
) CredentialError!usize {
    var fbs = std.io.fixedBufferStream(out_buf);
    const w = fbs.writer();
    w.writeByte('[') catch return CredentialError.BufferTooSmall;

    var stmt = database.prepare(
        \\SELECT id, name, service, category, scoped_tools,
        \\       expires_at, is_active, use_count, last_used_at, created_at
        \\FROM vault_secrets
        \\WHERE owner_id = ? AND is_active = 1
        \\ORDER BY created_at DESC
    ) catch return CredentialError.DbError;
    defer stmt.finalize();

    stmt.bindText(1, owner_id.ptr, @intCast(owner_id.len)) catch return CredentialError.DbError;

    var first = true;
    while (stmt.step() catch return CredentialError.DbError) {
        if (!first) w.writeByte(',') catch return CredentialError.BufferTooSmall;
        first = false;
        if (!writeCredentialMetaRow(&stmt, w)) return CredentialError.BufferTooSmall;
    }

    w.writeByte(']') catch return CredentialError.BufferTooSmall;
    return fbs.pos;
}

/// Write one credential's metadata row as JSON object (no secret).
fn writeCredentialMetaRow(stmt: *db_mod.Statement, w: anytype) bool {
    const id = stmt.getText(0) orelse return false;
    const name = stmt.getText(1) orelse return false;
    const service = stmt.getText(2) orelse return false;
    const category_ptr = stmt.getText(3);
    const scoped_tools = stmt.getText(4) orelse return false;
    const expires_at = stmt.getText(5); // nullable
    const is_active = stmt.getInt(6);
    const use_count = stmt.getInt(7);
    const last_used = stmt.getText(8); // nullable
    const created_at = stmt.getText(9) orelse return false;

    var esc_id: [256]u8 = undefined;
    var esc_name: [512]u8 = undefined;
    var esc_svc: [256]u8 = undefined;
    var esc_cat: [128]u8 = undefined;

    const id_len = json_mod.escapeJsonString(std.mem.span(id), &esc_id) catch return false;
    const name_len = json_mod.escapeJsonString(std.mem.span(name), &esc_name) catch return false;
    const svc_len = json_mod.escapeJsonString(std.mem.span(service), &esc_svc) catch return false;
    const cat_str = if (category_ptr) |p| std.mem.span(p) else "";
    const cat_len = json_mod.escapeJsonString(cat_str, &esc_cat) catch return false;
    const tools_str = std.mem.span(scoped_tools);
    const ca_str = std.mem.span(created_at);

    std.fmt.format(w,
        "{{\"id\":\"{s}\",\"name\":\"{s}\",\"service\":\"{s}\",\"category\":\"{s}\"" ++
        ",\"scoped_tools\":{s},\"is_active\":{s},\"use_count\":{d},\"created_at\":\"{s}\"",
        .{
            esc_id[0..id_len], esc_name[0..name_len], esc_svc[0..svc_len],
            esc_cat[0..cat_len], tools_str,
            if (is_active != 0) "true" else "false", use_count, ca_str,
        },
    ) catch return false;

    if (expires_at) |ea| {
        std.fmt.format(w, ",\"expires_at\":\"{s}\"", .{std.mem.span(ea)}) catch return false;
    } else {
        w.writeAll(",\"expires_at\":null") catch return false;
    }
    if (last_used) |lu| {
        std.fmt.format(w, ",\"last_used_at\":\"{s}\"", .{std.mem.span(lu)}) catch return false;
    } else {
        w.writeAll(",\"last_used_at\":null") catch return false;
    }
    w.writeByte('}') catch return false;
    return true;
}

// ═══════════════════════════════════════════
//  LOOKUP FOR TOOL (returns encrypted blob)
// ═══════════════════════════════════════════

/// Find active credentials for a specific tool_name.
/// Writes JSON array: [{id, name, service, scoped_tools, secret_encrypted_b64}]
/// Returns bytes written or 0 if none found.
pub fn forTool(
    database: *db_mod.Database,
    owner_id: []const u8,
    tool_name: []const u8,
    out_buf: []u8,
) CredentialError!usize {
    // Use json_each to match tool_name inside scoped_tools JSON array
    var stmt = database.prepare(
        \\SELECT id, name, service, scoped_tools, secret_encrypted
        \\FROM vault_secrets
        \\WHERE owner_id = ? AND is_active = 1
        \\  AND (expires_at IS NULL OR expires_at > strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        \\  AND EXISTS (
        \\    SELECT 1 FROM json_each(scoped_tools) WHERE json_each.value = ?
        \\  )
        \\ORDER BY created_at DESC
        \\LIMIT 10
    ) catch return CredentialError.DbError;
    defer stmt.finalize();

    stmt.bindText(1, owner_id.ptr, @intCast(owner_id.len)) catch return CredentialError.DbError;
    stmt.bindText(2, tool_name.ptr, @intCast(tool_name.len)) catch return CredentialError.DbError;

    var fbs = std.io.fixedBufferStream(out_buf);
    const w = fbs.writer();
    w.writeByte('[') catch return CredentialError.BufferTooSmall;

    var first = true;
    while (stmt.step() catch return CredentialError.DbError) {
        if (!first) w.writeByte(',') catch return CredentialError.BufferTooSmall;
        first = false;

        const id = stmt.getText(0) orelse continue;
        const name = stmt.getText(1) orelse continue;
        const service = stmt.getText(2) orelse continue;
        const scoped_tools = stmt.getText(3) orelse "[]";
        const enc_blob = stmt.getBlob(4) orelse continue;

        // base64-encode the encrypted blob so it can be safely embedded in JSON
        var b64_buf: [8192]u8 = undefined;
        const enc = std.base64.standard.Encoder;
        const b64_len = enc.calcSize(enc_blob.len);
        if (b64_len > b64_buf.len) continue;
        _ = enc.encode(&b64_buf, enc_blob);

        var esc_id: [256]u8 = undefined;
        var esc_name: [512]u8 = undefined;
        var esc_svc: [256]u8 = undefined;
        const id_len2 = json_mod.escapeJsonString(std.mem.span(id), &esc_id) catch continue;
        const name_len2 = json_mod.escapeJsonString(std.mem.span(name), &esc_name) catch continue;
        const svc_len2 = json_mod.escapeJsonString(std.mem.span(service), &esc_svc) catch continue;

        std.fmt.format(w,
            "{{\"id\":\"{s}\",\"name\":\"{s}\",\"service\":\"{s}\"" ++
            ",\"scoped_tools\":{s},\"secret_encrypted_b64\":\"{s}\"}}",
            .{
                esc_id[0..id_len2], esc_name[0..name_len2], esc_svc[0..svc_len2],
                std.mem.span(scoped_tools), b64_buf[0..b64_len],
            },
        ) catch return CredentialError.BufferTooSmall;
    }

    w.writeByte(']') catch return CredentialError.BufferTooSmall;
    return fbs.pos;
}

// ═══════════════════════════════════════════
//  UPDATE USE COUNT
// ═══════════════════════════════════════════

pub fn updateUse(
    database: *db_mod.Database,
    id: []const u8,
    actor_id: []const u8,
) db_mod.SqliteError!void {
    _ = actor_id; // recorded in credential_ops separately
    var stmt = try database.prepare(
        \\UPDATE vault_secrets
        \\SET use_count = use_count + 1,
        \\    last_used_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
        \\WHERE id = ? AND is_active = 1
    );
    defer stmt.finalize();
    try stmt.bindText(1, id.ptr, @intCast(id.len));
    _ = try stmt.step();
}

// ═══════════════════════════════════════════
//  UPDATE SECRET (rotation)
// ═══════════════════════════════════════════

pub fn updateSecret(
    database: *db_mod.Database,
    id: []const u8,
    owner_id: []const u8,
    new_secret_encrypted: []const u8,
) CredentialError!void {
    var stmt = database.prepare(
        \\UPDATE vault_secrets
        \\SET secret_encrypted = ?,
        \\    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
        \\WHERE id = ? AND owner_id = ? AND is_active = 1
    ) catch return CredentialError.DbError;
    defer stmt.finalize();

    const rc = db_mod.c.sqlite3_bind_blob(
        stmt.handle,
        1,
        new_secret_encrypted.ptr,
        @intCast(new_secret_encrypted.len),
        null,
    );
    if (rc != db_mod.c.SQLITE_OK) return CredentialError.DbError;
    stmt.bindText(2, id.ptr, @intCast(id.len)) catch return CredentialError.DbError;
    stmt.bindText(3, owner_id.ptr, @intCast(owner_id.len)) catch return CredentialError.DbError;
    _ = stmt.step() catch return CredentialError.DbError;
}

// ═══════════════════════════════════════════
//  DEACTIVATE (soft-delete)
// ═══════════════════════════════════════════

/// Soft-delete a credential. Returns 0 on success, PermissionDenied if owner mismatch.
pub fn deactivate(
    database: *db_mod.Database,
    id: []const u8,
    owner_id: []const u8,
) CredentialError!void {
    // Check ownership first
    var check = database.prepare(
        "SELECT id FROM vault_secrets WHERE id = ? AND owner_id = ?"
    ) catch return CredentialError.DbError;
    defer check.finalize();
    check.bindText(1, id.ptr, @intCast(id.len)) catch return CredentialError.DbError;
    check.bindText(2, owner_id.ptr, @intCast(owner_id.len)) catch return CredentialError.DbError;
    const found = check.step() catch return CredentialError.DbError;
    if (!found) return CredentialError.PermissionDenied;

    var stmt = database.prepare(
        \\UPDATE vault_secrets
        \\SET is_active = 0,
        \\    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
        \\WHERE id = ? AND owner_id = ?
    ) catch return CredentialError.DbError;
    defer stmt.finalize();
    stmt.bindText(1, id.ptr, @intCast(id.len)) catch return CredentialError.DbError;
    stmt.bindText(2, owner_id.ptr, @intCast(owner_id.len)) catch return CredentialError.DbError;
    _ = stmt.step() catch return CredentialError.DbError;

    // Remove from FTS
    var fts_stmt = database.prepare(
        "DELETE FROM credential_fts WHERE credential_id = ?"
    ) catch return;
    defer fts_stmt.finalize();
    fts_stmt.bindText(1, id.ptr, @intCast(id.len)) catch return;
    _ = fts_stmt.step() catch {};
}

// ═══════════════════════════════════════════
//  SHARES — CREATE
// ═══════════════════════════════════════════

pub fn shareCreate(
    database: *db_mod.Database,
    share_id: []const u8,
    cred_id: []const u8,
    grantor_id: []const u8,
    grantee_id: []const u8,
    grantee_type: []const u8,
    expires_at: []const u8,
    max_uses: ?i32,
    secret_reencrypted: ?[]const u8,
) CredentialError!void {
    // Verify credential belongs to grantor
    var check = database.prepare(
        "SELECT id FROM vault_secrets WHERE id = ? AND owner_id = ? AND is_active = 1"
    ) catch return CredentialError.DbError;
    defer check.finalize();
    check.bindText(1, cred_id.ptr, @intCast(cred_id.len)) catch return CredentialError.DbError;
    check.bindText(2, grantor_id.ptr, @intCast(grantor_id.len)) catch return CredentialError.DbError;
    if (!(check.step() catch return CredentialError.DbError)) return CredentialError.PermissionDenied;

    var stmt = database.prepare(
        \\INSERT INTO credential_shares
        \\  (id, credential_id, grantor_id, grantee_id, grantee_type,
        \\   expires_at, max_uses, can_reshare, secret_reencrypted)
        \\VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
    ) catch return CredentialError.DbError;
    defer stmt.finalize();
    stmt.bindText(1, share_id.ptr, @intCast(share_id.len)) catch return CredentialError.DbError;
    stmt.bindText(2, cred_id.ptr, @intCast(cred_id.len)) catch return CredentialError.DbError;
    stmt.bindText(3, grantor_id.ptr, @intCast(grantor_id.len)) catch return CredentialError.DbError;
    stmt.bindText(4, grantee_id.ptr, @intCast(grantee_id.len)) catch return CredentialError.DbError;
    stmt.bindText(5, grantee_type.ptr, @intCast(grantee_type.len)) catch return CredentialError.DbError;
    stmt.bindText(6, expires_at.ptr, @intCast(expires_at.len)) catch return CredentialError.DbError;
    if (max_uses) |mu| {
        stmt.bindInt(7, mu) catch return CredentialError.DbError;
    } else {
        _ = db_mod.c.sqlite3_bind_null(stmt.handle, 7);
    }
    if (secret_reencrypted) |sec| {
        const rc = db_mod.c.sqlite3_bind_blob(stmt.handle, 8, sec.ptr, @intCast(sec.len), null);
        if (rc != db_mod.c.SQLITE_OK) return CredentialError.DbError;
    } else {
        _ = db_mod.c.sqlite3_bind_null(stmt.handle, 8);
    }
    _ = stmt.step() catch return CredentialError.DbError;
}

// ═══════════════════════════════════════════
//  SHARES — CHECK (grantee access)
// ═══════════════════════════════════════════

/// Check if grantee has an active share for cred_id.
/// Writes the share metadata as JSON. Returns bytes written, or 0 if no valid share.
pub fn shareCheck(
    database: *db_mod.Database,
    cred_id: []const u8,
    grantee_id: []const u8,
    out_buf: []u8,
) CredentialError!usize {
    var stmt = database.prepare(
        \\SELECT id, max_uses, use_count, expires_at, secret_reencrypted
        \\FROM credential_shares
        \\WHERE credential_id = ? AND grantee_id = ?
        \\  AND revoked_at IS NULL
        \\  AND expires_at > strftime('%Y-%m-%dT%H:%M:%SZ','now')
        \\  AND (max_uses IS NULL OR use_count < max_uses)
        \\ORDER BY created_at DESC
        \\LIMIT 1
    ) catch return CredentialError.DbError;
    defer stmt.finalize();
    stmt.bindText(1, cred_id.ptr, @intCast(cred_id.len)) catch return CredentialError.DbError;
    stmt.bindText(2, grantee_id.ptr, @intCast(grantee_id.len)) catch return CredentialError.DbError;

    if (!(stmt.step() catch return CredentialError.DbError)) return 0;

    const share_id = stmt.getText(0) orelse return 0;
    const max_uses_val = stmt.getInt(1);
    const use_count_val = stmt.getInt(2);
    const exp = stmt.getText(3) orelse "";
    const reenc = stmt.getBlob(4);

    var fbs = std.io.fixedBufferStream(out_buf);
    const w = fbs.writer();

    if (reenc) |blob| {
        var b64_buf: [8192]u8 = undefined;
        const enc = std.base64.standard.Encoder;
        const b64_len = enc.calcSize(blob.len);
        if (b64_len <= b64_buf.len) {
            _ = enc.encode(&b64_buf, blob);
            std.fmt.format(w,
                "{{\"share_id\":\"{s}\",\"max_uses\":{d},\"use_count\":{d}" ++
                ",\"expires_at\":\"{s}\",\"secret_reencrypted_b64\":\"{s}\"}}",
                .{ std.mem.span(share_id), max_uses_val, use_count_val,
                   std.mem.span(exp), b64_buf[0..b64_len] },
            ) catch return CredentialError.BufferTooSmall;
        }
    } else {
        std.fmt.format(w,
            "{{\"share_id\":\"{s}\",\"max_uses\":{d},\"use_count\":{d}" ++
            ",\"expires_at\":\"{s}\",\"secret_reencrypted_b64\":null}}",
            .{ std.mem.span(share_id), max_uses_val, use_count_val, std.mem.span(exp) },
        ) catch return CredentialError.BufferTooSmall;
    }
    return fbs.pos;
}

// ═══════════════════════════════════════════
//  SHARES — REVOKE
// ═══════════════════════════════════════════

pub fn shareRevoke(
    database: *db_mod.Database,
    share_id: []const u8,
    grantor_id: []const u8,
) CredentialError!void {
    var stmt = database.prepare(
        \\UPDATE credential_shares
        \\SET revoked_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
        \\WHERE id = ? AND grantor_id = ? AND revoked_at IS NULL
    ) catch return CredentialError.DbError;
    defer stmt.finalize();
    stmt.bindText(1, share_id.ptr, @intCast(share_id.len)) catch return CredentialError.DbError;
    stmt.bindText(2, grantor_id.ptr, @intCast(grantor_id.len)) catch return CredentialError.DbError;
    _ = stmt.step() catch return CredentialError.DbError;
}
