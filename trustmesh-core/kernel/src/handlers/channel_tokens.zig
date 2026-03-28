// handlers/channel_tokens.zig — Channel token CRUD for ZeroClaw/NullClaw integration.
//
// Channel tokens (tm_<base64url>) let external agent runtimes authenticate
// against the TrustMesh Memory and Channel APIs without browser session cookies.
//
// Routes (registered under /api/users/*):
//   POST   /api/users/*/channel-tokens      → handleCreate
//   GET    /api/users/*/channel-tokens      → handleList
//   DELETE /api/users/*/channel-tokens/*   → handleRevoke
//
// Token validation (used by channels.zig):
//   validateToken(db, hash, out_owner_id, out_rel_type) → !ValidateResult

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router_mod = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;

const Sha256 = std.crypto.hash.sha2.Sha256;

// ── Module-level state ──
var _db: ?*podos.db.Database = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

// setSessionStore kept for signature compat — delegates to common
pub fn setSessionStore(_: *podos.session.SessionStore) void {}

// ── Delegates ──
const requireAuth = common.requireAuth;
const generateUuid = common.generateUuid;
const formatIsoTimestamp = common.formatIsoTimestamp;

// ═══════════════════════════════════════════
//  TABLE INIT
// ═══════════════════════════════════════════

/// Create the channel_tokens table (idempotent). Called by registerRoutes().
fn initTable(database: *podos.db.Database) void {
    _ = database.exec(
        \\CREATE TABLE IF NOT EXISTS channel_tokens (
        \\  id TEXT PRIMARY KEY,
        \\  owner_id TEXT NOT NULL REFERENCES users(id),
        \\  token_hash TEXT NOT NULL UNIQUE,
        \\  name TEXT NOT NULL,
        \\  relationship_type TEXT,
        \\  scopes TEXT NOT NULL DEFAULT 'query,memory',
        \\  created_at INTEGER NOT NULL,
        \\  last_used_at INTEGER,
        \\  revoked_at INTEGER
        \\)
    ) catch {};

    _ = database.exec(
        "CREATE INDEX IF NOT EXISTS idx_channel_tokens_hash ON channel_tokens(token_hash)",
    ) catch {};

    _ = database.exec(
        "CREATE INDEX IF NOT EXISTS idx_channel_tokens_owner ON channel_tokens(owner_id)",
    ) catch {};
}

// ═══════════════════════════════════════════
//  ROUTE REGISTRATION
// ═══════════════════════════════════════════

pub fn registerRoutes() void {
    const database = _db orelse return;
    initTable(database);

    // Prefix match for /api/users/*/channel-tokens and /api/users/*/channel-tokens/*
    router_mod.addPrefix(.POST, "/api/users/", handleCreate);
    router_mod.addPrefix(.GET, "/api/users/", handleList);
    router_mod.addPrefix(.DELETE, "/api/users/", handleRevoke);
}

// ═══════════════════════════════════════════
//  ROUTE DISPATCH HELPERS
// ═══════════════════════════════════════════

/// Check that path matches /api/users/{user_id}/channel-tokens[/...]
/// and extract user_id. Returns null if this handler doesn't own the path.
fn extractChannelTokenPath(path: []const u8) ?struct { user_id: []const u8, rest: []const u8 } {
    const prefix = "/api/users/";
    if (!std.mem.startsWith(u8, path, prefix)) return null;
    const after_prefix = path[prefix.len..];

    // Find next '/'
    const slash = std.mem.indexOfScalar(u8, after_prefix, '/') orelse return null;
    const user_id = after_prefix[0..slash];
    const rest = after_prefix[slash + 1 ..]; // e.g., "channel-tokens" or "channel-tokens/abc"

    if (!std.mem.startsWith(u8, rest, "channel-tokens")) return null;
    const after_ct = rest["channel-tokens".len..]; // "" or "/abc"
    return .{ .user_id = user_id, .rest = after_ct };
}

// ═══════════════════════════════════════════
//  TOKEN GENERATION
// ═══════════════════════════════════════════

/// Generate a raw token: "tm_" + base64url(32 random bytes). ~47 chars total.
/// Writes into `buf` (must be >= 64 bytes). Returns slice of written bytes.
fn generateRawToken(buf: []u8) []const u8 {
    var random_bytes: [32]u8 = undefined;
    std.crypto.random.bytes(&random_bytes);

    const b64 = std.base64.url_safe_no_pad;
    const b64_len = b64.Encoder.calcSize(32);

    buf[0] = 't';
    buf[1] = 'm';
    buf[2] = '_';
    _ = b64.Encoder.encode(buf[3..3 + b64_len], &random_bytes);
    return buf[0..3 + b64_len];
}

/// SHA-256 hex of token. Writes 64 hex chars into `out`.
fn hashToken(token: []const u8, out: *[64]u8) void {
    common.sha256Hex(token, out);
}

// ═══════════════════════════════════════════
//  HANDLER: POST /api/users/{id}/channel-tokens
// ═══════════════════════════════════════════

const CreateRequest = struct {
    name: ?[]const u8 = null,
    relationship_type: ?[]const u8 = null,
    scopes: ?[]const u8 = null,
};

fn handleCreate(ctx: *http.RequestContext) !void {
    const parsed_path = extractChannelTokenPath(ctx.path) orelse
        return http.proxyFromHandler(ctx);

    // Only handle exact /api/users/{id}/channel-tokens (no trailing segment)
    if (parsed_path.rest.len > 0) return http.proxyFromHandler(ctx);

    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = requireAuth(ctx, &uid_buf) orelse return;

    // Verify requesting user owns the resource
    if (!std.mem.eql(u8, auth_user_id, parsed_path.user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    const parsed = json_mod.parse(CreateRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const name = req.name orelse return ctx.sendError(.bad_request, "name required");
    const relationship_type = req.relationship_type orelse "";
    const scopes = req.scopes orelse "query,memory";

    // Generate token
    var raw_token_buf: [64]u8 = undefined;
    const raw_token = generateRawToken(&raw_token_buf);

    // Hash for storage
    var hash_buf: [64]u8 = undefined;
    hashToken(raw_token, &hash_buf);
    const token_hash = hash_buf[0..64];

    // Generate token ID
    var token_id_buf: [36]u8 = undefined;
    generateUuid(&token_id_buf);
    const token_id = token_id_buf[0..36];

    const now = std.time.timestamp();

    // INSERT
    {
        var stmt = database.prepare(
            "INSERT INTO channel_tokens (id, owner_id, token_hash, name, relationship_type, scopes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();

        stmt.bindText(1, token_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, auth_user_id.ptr, @intCast(auth_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, token_hash.ptr, 64) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, name.ptr, @intCast(name.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, relationship_type.ptr, @intCast(relationship_type.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(6, scopes.ptr, @intCast(scopes.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindInt(7, @intCast(now)) catch return ctx.sendError(.internal_server_error, "DB error");

        _ = stmt.step() catch return ctx.sendError(.conflict, "Token name already in use");
    }

    // Build response — include raw_token (returned ONCE)
    var esc_id: [128]u8 = undefined;
    var esc_name: [256]u8 = undefined;
    var esc_token: [128]u8 = undefined;
    const eid_len = json_mod.escapeJsonString(token_id, &esc_id) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const ename_len = json_mod.escapeJsonString(name, &esc_name) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const etoken_len = json_mod.escapeJsonString(raw_token, &esc_token) catch return ctx.sendError(.internal_server_error, "Serialize failed");

    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"id\":\"{s}\",\"name\":\"{s}\",\"raw_token\":\"{s}\"}}",
        .{ esc_id[0..eid_len], esc_name[0..ename_len], esc_token[0..etoken_len] },
    );
    try ctx.json(.created, body);
}

// ═══════════════════════════════════════════
//  HANDLER: GET /api/users/{id}/channel-tokens
// ═══════════════════════════════════════════

fn handleList(ctx: *http.RequestContext) !void {
    const parsed_path = extractChannelTokenPath(ctx.path) orelse
        return http.proxyFromHandler(ctx);

    if (parsed_path.rest.len > 0) return http.proxyFromHandler(ctx);

    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = requireAuth(ctx, &uid_buf) orelse return;

    if (!std.mem.eql(u8, auth_user_id, parsed_path.user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "{\"tokens\":[");

    var stmt = database.prepare(
        "SELECT id, name, relationship_type, scopes, created_at, last_used_at FROM channel_tokens WHERE owner_id = ? AND revoked_at IS NULL ORDER BY created_at DESC",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();

    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var first = true;
    while (stmt.step() catch false) {
        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        const name_ptr = stmt.getText(1) orelse continue;
        const name_s = std.mem.span(name_ptr);
        const rel_ptr = stmt.getText(2);
        const rel_s: []const u8 = if (rel_ptr) |p| std.mem.span(p) else "";
        const scopes_ptr = stmt.getText(3) orelse continue;
        const scopes_s = std.mem.span(scopes_ptr);
        const created_at = stmt.getInt(4);
        const last_used_at = stmt.getInt(5); // may be 0 if null

        if (!first) try result.appendSlice(ctx.allocator, ",");
        first = false;

        var esc_id: [128]u8 = undefined;
        var esc_name: [256]u8 = undefined;
        var esc_rel: [128]u8 = undefined;
        var esc_scopes: [128]u8 = undefined;
        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const ename = json_mod.escapeJsonString(name_s, &esc_name) catch continue;
        const erel = json_mod.escapeJsonString(rel_s, &esc_rel) catch continue;
        const escopes = json_mod.escapeJsonString(scopes_s, &esc_scopes) catch continue;

        const entry = try std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"name\":\"{s}\",\"relationship_type\":\"{s}\",\"scopes\":\"{s}\",\"created_at\":{d},\"last_used_at\":{d}}}",
            .{ esc_id[0..eid], esc_name[0..ename], esc_rel[0..erel], esc_scopes[0..escopes], created_at, last_used_at },
        );
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]}");
    try ctx.json(.ok, result.items);
}

// ═══════════════════════════════════════════
//  HANDLER: DELETE /api/users/{id}/channel-tokens/{token_id}
// ═══════════════════════════════════════════

fn handleRevoke(ctx: *http.RequestContext) !void {
    const parsed_path = extractChannelTokenPath(ctx.path) orelse
        return http.proxyFromHandler(ctx);

    // Expect rest to be "/" + token_id (with leading slash stripped)
    // rest starts with "/" so: "/abc..." after "channel-tokens"
    if (parsed_path.rest.len == 0) return http.proxyFromHandler(ctx);

    // rest is "/token_id" — strip leading slash
    const token_id = if (parsed_path.rest[0] == '/') parsed_path.rest[1..] else parsed_path.rest;
    if (token_id.len == 0 or token_id.len > 36) return ctx.sendError(.bad_request, "Invalid token ID");

    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = requireAuth(ctx, &uid_buf) orelse return;

    if (!std.mem.eql(u8, auth_user_id, parsed_path.user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    const now = std.time.timestamp();

    var stmt = database.prepare(
        "UPDATE channel_tokens SET revoked_at = ? WHERE id = ? AND owner_id = ? AND revoked_at IS NULL",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();

    stmt.bindInt(1, @intCast(now)) catch return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(2, token_id.ptr, @intCast(token_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(3, auth_user_id.ptr, @intCast(auth_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");

    _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Revoke failed");

    try ctx.json(.ok, "{\"status\":\"revoked\"}");
}

// ═══════════════════════════════════════════
//  TOKEN VALIDATION (called by channels.zig)
// ═══════════════════════════════════════════

pub const ValidateResult = struct {
    owner_id: [128]u8,
    owner_id_len: usize,
    relationship_type: [64]u8,
    relationship_type_len: usize,

    pub fn getOwnerId(self: *const ValidateResult) []const u8 {
        return self.owner_id[0..self.owner_id_len];
    }

    pub fn getRelationshipType(self: *const ValidateResult) []const u8 {
        return self.relationship_type[0..self.relationship_type_len];
    }
};

/// Look up a token by its SHA-256 hex hash. Updates last_used_at (best-effort).
/// Returns error.NotFound if token doesn't exist or is revoked.
pub fn validateToken(database: *podos.db.Database, token_hash: []const u8, out: *ValidateResult) !void {
    var stmt = try database.prepare(
        "SELECT owner_id, relationship_type FROM channel_tokens WHERE token_hash = ? AND revoked_at IS NULL",
    );
    defer stmt.finalize();

    try stmt.bindText(1, token_hash.ptr, @intCast(token_hash.len));

    if (!(try stmt.step())) return error.NotFound;

    const owner_ptr = stmt.getText(0) orelse return error.NotFound;
    const owner_s = std.mem.span(owner_ptr);
    if (owner_s.len > 128) return error.NotFound;

    const rel_ptr = stmt.getText(1);
    const rel_s: []const u8 = if (rel_ptr) |p| std.mem.span(p) else "";

    @memcpy(out.owner_id[0..owner_s.len], owner_s);
    out.owner_id_len = owner_s.len;

    const rel_len = @min(rel_s.len, 64);
    @memcpy(out.relationship_type[0..rel_len], rel_s[0..rel_len]);
    out.relationship_type_len = rel_len;

    // Non-critical: update last_used_at
    const now = std.time.timestamp();
    var upd = database.prepare("UPDATE channel_tokens SET last_used_at = ? WHERE token_hash = ?") catch return;
    defer upd.finalize();
    upd.bindInt(1, @intCast(now)) catch return;
    upd.bindText(2, token_hash.ptr, @intCast(token_hash.len)) catch return;
    _ = upd.step() catch {};
}
