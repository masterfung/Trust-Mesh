// handlers/auth.zig — Native Zig handlers for auth routes (Phase 3b).
//
// Migrates:
//   POST /api/auth/login   → handleLogin
//   POST /api/auth/logout  → handleLogout
//   GET  /api/auth/me      → handleMe

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const json_mod = podos.json;

const Sha256 = std.crypto.hash.sha2.Sha256;

// ═══════════════════════════════════════════
//  ROUTE REGISTRATION
// ═══════════════════════════════════════════

pub fn registerRoutes() void {
    router.addExact(.POST, "/api/auth/login", handleLogin);
    router.addExact(.POST, "/api/auth/logout", handleLogout);
    router.addExact(.GET, "/api/auth/me", handleMe);
}

// ═══════════════════════════════════════════
//  DB HELPERS
// ═══════════════════════════════════════════

const UserRow = struct {
    id: []const u8,
    username: ?[]const u8,
    email: ?[]const u8,
    display_name: []const u8,
    user_type: []const u8,
    is_remote: bool,
    is_demo: bool,
    is_discoverable: bool,
    vault_key_salt: ?[]const u8,
    encrypted_vault_key: ?[]const u8,
};

fn lookupUserByLoginId(database: *podos.db.Database, login_id: []const u8, allocator: std.mem.Allocator) !?UserRow {
    // Try username (exact), email (case-insensitive), display_name (case-insensitive)
    const queries = [_][*:0]const u8{
        "SELECT id, username, email, display_name, user_type, is_remote, is_demo, is_discoverable, vault_key_salt, encrypted_vault_key FROM users WHERE username = ? LIMIT 1",
        "SELECT id, username, email, display_name, user_type, is_remote, is_demo, is_discoverable, vault_key_salt, encrypted_vault_key FROM users WHERE lower(email) = lower(?) LIMIT 1",
        "SELECT id, username, email, display_name, user_type, is_remote, is_demo, is_discoverable, vault_key_salt, encrypted_vault_key FROM users WHERE lower(display_name) = lower(?) LIMIT 1",
    };
    for (queries) |sql| {
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, login_id.ptr, @intCast(login_id.len));
        if (try stmt.step()) {
            return try readUserRow(&stmt, allocator);
        }
    }
    return null;
}

fn lookupUserById(database: *podos.db.Database, user_id: []const u8, allocator: std.mem.Allocator) !?UserRow {
    const sql = "SELECT id, username, email, display_name, user_type, is_remote, is_demo, is_discoverable, vault_key_salt, encrypted_vault_key FROM users WHERE id = ? LIMIT 1";
    var stmt = try database.prepare(sql);
    defer stmt.finalize();
    try stmt.bindText(1, user_id.ptr, @intCast(user_id.len));
    if (try stmt.step()) {
        return try readUserRow(&stmt, allocator);
    }
    return null;
}

fn dupCol(stmt: *podos.db.Statement, col: c_int, allocator: std.mem.Allocator) !?[]u8 {
    const ptr = stmt.getText(col) orelse return null;
    const s = std.mem.span(ptr);
    if (s.len == 0) return null;
    const dup = try allocator.alloc(u8, s.len);
    @memcpy(dup, s);
    return dup;
}

/// Duplicate a BLOB column into allocator-owned memory.
/// Unlike dupCol (which uses getText and stops at null bytes), this reads
/// raw binary data via sqlite3_column_blob + sqlite3_column_bytes.
fn dupBlob(stmt: *podos.db.Statement, col: c_int, allocator: std.mem.Allocator) !?[]u8 {
    const blob = stmt.getBlob(col) orelse return null;
    if (blob.len == 0) return null;
    const dup = try allocator.alloc(u8, blob.len);
    @memcpy(dup, blob);
    return dup;
}

fn readUserRow(stmt: *podos.db.Statement, allocator: std.mem.Allocator) !UserRow {
    return UserRow{
        .id = (try dupCol(stmt, 0, allocator)) orelse return error.MissingColumn,
        .username = try dupCol(stmt, 1, allocator),
        .email = try dupCol(stmt, 2, allocator),
        .display_name = (try dupCol(stmt, 3, allocator)) orelse return error.MissingColumn,
        .user_type = (try dupCol(stmt, 4, allocator)) orelse return error.MissingColumn,
        .is_remote = stmt.getInt(5) != 0,
        .is_demo = stmt.getInt(6) != 0,
        .is_discoverable = stmt.getInt(7) != 0,
        // vault_key_salt and encrypted_vault_key are LargeBinary (BLOB) columns —
        // must use getBlob(), not getText(), to avoid truncation at null bytes.
        .vault_key_salt = try dupBlob(stmt, 8, allocator),
        .encrypted_vault_key = try dupBlob(stmt, 9, allocator),
    };
}

// ═══════════════════════════════════════════
//  FINGERPRINT
// ═══════════════════════════════════════════

fn buildFingerprint(ctx: *const http.RequestContext, buf: *[64]u8) []const u8 {
    const ua = ctx.getHeader("user-agent") orelse "";
    const ip = http.getClientIp(ctx);

    var h = Sha256.init(.{});
    h.update(ua);
    h.update("|");
    h.update(ip);
    const digest = h.finalResult();

    // Manual hex encode (fmtSliceHexLower removed in 0.15.2)
    const hex_chars = "0123456789abcdef";
    for (digest, 0..) |byte, i| {
        buf[i * 2] = hex_chars[byte >> 4];
        buf[i * 2 + 1] = hex_chars[byte & 0x0f];
    }
    return buf[0..64];
}

// ═══════════════════════════════════════════
//  SESSION + VAULT (Zig internal calls)
// ═══════════════════════════════════════════

// Global DB handle — set from server_main.zig.
var _db: ?*podos.db.Database = null;
var _session_store: ?*podos.session.SessionStore = null;
var _transit_engine: ?*podos.transit.TransitEngine = null;

pub fn setDatabase(database: *podos.db.Database) void {
    _db = database;
}

pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

pub fn setTransitEngine(engine: *podos.transit.TransitEngine) void {
    _transit_engine = engine;
}

fn createSessionFp(user_id: []const u8, fingerprint: []const u8, out: []u8) ![]const u8 {
    const store = _session_store orelse return error.NotInitialized;
    const len = try store.createSession(user_id, fingerprint, out);
    return out[0..len];
}

fn validateSessionFp(token: []const u8, fingerprint: []const u8, out_uid: []u8) ?[]const u8 {
    const store = _session_store orelse return null;
    const uid = store.validateSession(token, fingerprint) orelse return null;
    if (uid.len > out_uid.len) return null;
    @memcpy(out_uid[0..uid.len], uid);
    return out_uid[0..uid.len];
}

fn invalidateUserSessions(user_id: []const u8) void {
    const store = _session_store orelse return;
    store.invalidateUserSessions(user_id);
}

fn invalidateToken(token: []const u8) void {
    const store = _session_store orelse return;
    store.invalidateSession(token);
}

fn unlockVault(
    user_id: []const u8,
    password: []const u8,
    raw_salt: []const u8,
    raw_enc_vk: []const u8,
) !void {
    const transit_eng = _transit_engine orelse return error.NotInitialized;

    // Salt is stored as raw 16 bytes (LargeBinary BLOB in SQLite)
    if (raw_salt.len != 16) return error.InvalidSalt;
    const salt: *const [16]u8 = raw_salt[0..16];

    // Derive vault key via Argon2id
    var derived_key: [32]u8 = undefined;
    defer std.crypto.secureZero(u8, &derived_key);
    const argon2 = std.crypto.pwhash.argon2;
    argon2.kdf(std.heap.page_allocator, &derived_key, password, salt, .{
        .t = 3,
        .m = 65536,
        .p = 4,
    }, .argon2id) catch return error.DeriveKeyFailed;

    // encrypted_vault_key is stored as raw bytes: nonce(12) || ciphertext(32) || tag(16) = 60 bytes
    if (raw_enc_vk.len < podos.crypto.NONCE_SIZE + podos.crypto.TAG_SIZE)
        return error.VaultDecryptFailed;

    var vault_key: [32]u8 = undefined;
    defer std.crypto.secureZero(u8, &vault_key);
    _ = podos.crypto.decrypt(raw_enc_vk, &derived_key, &vault_key) catch
        return error.VaultDecryptFailed;

    // Store in transit engine
    _ = try transit_eng.storeKey(user_id, &vault_key);
}

fn removeVaultKey(user_id: []const u8) void {
    const transit_eng = _transit_engine orelse return;
    transit_eng.removeUser(user_id);
}

// ═══════════════════════════════════════════
//  SAFE JSON RESPONSE BUILDER
// ═══════════════════════════════════════════

/// Build a JSON response body for a user with proper escaping of all user-controlled fields.
/// Allocates on the per-connection arena — safe for concurrent requests.
fn buildUserJson(user: UserRow, allocator: std.mem.Allocator) ![]const u8 {
    // Escape user-controlled fields
    var esc_display: [512]u8 = undefined;
    var esc_type: [128]u8 = undefined;
    var esc_id: [128]u8 = undefined;

    const display_len = json_mod.escapeJsonString(user.display_name, &esc_display) catch return error.SerializeFailed;
    const type_len = json_mod.escapeJsonString(user.user_type, &esc_type) catch return error.SerializeFailed;
    const id_len = json_mod.escapeJsonString(user.id, &esc_id) catch return error.SerializeFailed;

    return std.fmt.allocPrint(allocator,
        "{{\"id\":\"{s}\",\"display_name\":\"{s}\",\"user_type\":\"{s}\",\"is_demo\":{s},\"is_discoverable\":{s},\"is_remote\":false}}",
        .{
            esc_id[0..id_len],
            esc_display[0..display_len],
            esc_type[0..type_len],
            if (user.is_demo) "true" else "false",
            if (user.is_discoverable) "true" else "false",
        },
    ) catch return error.SerializeFailed;
}

// ═══════════════════════════════════════════
//  REQUEST TYPES
// ═══════════════════════════════════════════

const LoginRequest = struct {
    email: ?[]const u8 = null,
    name: ?[]const u8 = null,
    username: ?[]const u8 = null,
    password: []const u8 = "",
};

// ═══════════════════════════════════════════
//  HANDLER: POST /api/auth/login
// ═══════════════════════════════════════════

fn handleLogin(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    // Rate check — SEC-05: use safe client IP extraction
    const ip = http.getClientIp(ctx);
    if (_session_store) |store| {
        if (!(store.checkLoginRateLimit(ip) catch true)) {
            return ctx.sendError(.too_many_requests, "Too many login attempts");
        }
    }

    // Parse body
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    const parsed = json_mod.parse(LoginRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const login_id = req.email orelse req.name orelse req.username orelse "";
    if (login_id.len == 0) return ctx.sendError(.unauthorized, "Name, email, or username required");

    // Lookup user
    const user = try lookupUserByLoginId(database, login_id, ctx.allocator) orelse
        return ctx.sendError(.unauthorized, "Invalid credentials");

    if (user.is_remote) return ctx.sendError(.forbidden, "Remote ghost users cannot log in");

    const raw_salt = user.vault_key_salt orelse
        return ctx.sendError(.unauthorized, "Account not set up properly");
    const raw_enc_vk = user.encrypted_vault_key orelse
        return ctx.sendError(.unauthorized, "Account not set up properly");

    // Unlock vault (salt and encrypted_vault_key are raw BLOB bytes from SQLite)
    unlockVault(user.id, req.password, raw_salt, raw_enc_vk) catch
        return ctx.sendError(.unauthorized, "Invalid credentials");

    // Session rotation + create
    invalidateUserSessions(user.id);

    var fp_buf: [64]u8 = undefined;
    const fingerprint = buildFingerprint(ctx, &fp_buf);
    var token_buf: [128]u8 = undefined;
    const token = createSessionFp(user.id, fingerprint, &token_buf) catch
        return ctx.sendError(.internal_server_error, "Session creation failed");

    // Build response body with proper JSON escaping for user-controlled fields
    const body_bytes = buildUserJson(user, ctx.allocator) catch
        return ctx.sendError(.internal_server_error, "Serialization failed");

    // Set-Cookie header
    const cookie_val = try ctx.buildSetCookieHeader("trustmesh_session", token, .{ .same_site = .lax });

    try ctx.jsonWithHeaders(.ok, body_bytes, &.{
        .{ .name = "set-cookie", .value = cookie_val },
    });
}

// ═══════════════════════════════════════════
//  HANDLER: POST /api/auth/logout
// ═══════════════════════════════════════════

fn handleLogout(ctx: *http.RequestContext) !void {
    const token = ctx.getCookie("trustmesh_session");

    if (token) |tok| {
        var fp_buf: [64]u8 = undefined;
        const fp = buildFingerprint(ctx, &fp_buf);
        var uid_buf: [128]u8 = undefined;
        if (validateSessionFp(tok, fp, &uid_buf)) |uid| {
            invalidateUserSessions(uid);
            removeVaultKey(uid);
        }
        invalidateToken(tok);
    }

    // Clear cookie
    const clear_cookie = try ctx.buildSetCookieHeader("trustmesh_session", "", .{ .same_site = .lax, .max_age = 0 });

    try ctx.jsonWithHeaders(.ok, "{\"status\":\"ok\"}", &.{
        .{ .name = "set-cookie", .value = clear_cookie },
    });
}

// ═══════════════════════════════════════════
//  HANDLER: GET /api/auth/me
// ═══════════════════════════════════════════

fn handleMe(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    const token = ctx.getCookie("trustmesh_session") orelse
        return ctx.sendError(.unauthorized, "Not authenticated");

    var fp_buf: [64]u8 = undefined;
    const fp = buildFingerprint(ctx, &fp_buf);
    var uid_buf: [128]u8 = undefined;
    const user_id = validateSessionFp(token, fp, &uid_buf) orelse
        return ctx.sendError(.unauthorized, "Session expired or invalid");

    const user = try lookupUserById(database, user_id, ctx.allocator) orelse
        return ctx.sendError(.not_found, "User not found");

    const body_bytes = buildUserJson(user, ctx.allocator) catch
        return ctx.sendError(.internal_server_error, "Serialization failed");

    try ctx.json(.ok, body_bytes);
}
