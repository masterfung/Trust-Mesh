// handlers/credentials.zig — Native Zig HTTP handlers for credential store.
//
// Routes:
//   POST   /api/credentials           → handleCreate
//   GET    /api/credentials           → handleList
//   DELETE /api/credentials/:id       → handleDeactivate
//   POST   /api/credentials/:id/rotate→ handleRotate
//   POST   /api/credentials/:id/share → handleShare
//   DELETE /api/credentials/shares/:id→ handleRevokeShare
//   GET    /api/credentials/:id/usage → handleUsageLog

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router_mod = @import("../router.zig");
const json_mod = podos.json;
const cred = podos.credential;
const cred_audit = podos.credential_audit;

const Sha256 = std.crypto.hash.sha2.Sha256;

// ── Module-level state set from server_main.zig ──────────────────────────────
var _db: ?*podos.db.Database = null;
var _transit: ?*podos.transit.TransitEngine = null;
var _session_store: ?*podos.session.SessionStore = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setTransitEngine(t: *podos.transit.TransitEngine) void {
    _transit = t;
}

pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

// ── Route registration ─────────────────────────────────────────────────────────

pub fn registerRoutes() void {
    router_mod.addExact(.POST, "/api/credentials", handleCreate);
    router_mod.addExact(.GET, "/api/credentials", handleList);
    // prefix routes handled inside handlers via path parsing
    router_mod.addPrefix(.DELETE, "/api/credentials/shares/", handleRevokeShare);
    router_mod.addPrefix(.GET, "/api/credentials/", handleGetOrUsage);
    router_mod.addPrefix(.DELETE, "/api/credentials/", handleDeactivate);
    router_mod.addPrefix(.POST, "/api/credentials/", handlePostSubRoute);
}

// ── Auth helpers ──────────────────────────────────────────────────────────────

fn buildFingerprint(ctx: *const http.RequestContext, buf: *[64]u8) []const u8 {
    const ua = ctx.getHeader("user-agent") orelse "";
    const ip = http.getClientIp(ctx);
    var h = Sha256.init(.{});
    h.update(ua);
    h.update("|");
    h.update(ip);
    const digest = h.finalResult();
    const hex_chars = "0123456789abcdef";
    for (digest, 0..) |byte, i| {
        buf[i * 2] = hex_chars[byte >> 4];
        buf[i * 2 + 1] = hex_chars[byte & 0x0f];
    }
    return buf[0..64];
}

/// Extract authenticated owner_id from session cookie.
/// Returns null and sends 401 if not authenticated.
fn requireAuth(ctx: *http.RequestContext, out: []u8) ?[]const u8 {
    const token = ctx.getCookie("trustmesh_session") orelse {
        ctx.sendError(.unauthorized, "Not authenticated") catch {};
        return null;
    };
    const store = _session_store orelse {
        ctx.sendError(.service_unavailable, "Session store not ready") catch {};
        return null;
    };
    var fp_buf: [64]u8 = undefined;
    const fp = buildFingerprint(ctx, &fp_buf);
    const uid = store.validateSession(token, fp) orelse {
        ctx.sendError(.unauthorized, "Session expired or invalid") catch {};
        return null;
    };
    if (uid.len > out.len) {
        ctx.sendError(.internal_server_error, "User ID too long") catch {};
        return null;
    }
    @memcpy(out[0..uid.len], uid);
    return out[0..uid.len];
}

/// Generate a simple unique ID: hex(sha256(random_32_bytes + timestamp)).
/// Returns 64-char hex string.
fn generateId(buf: *[64]u8) []const u8 {
    var rand_bytes: [32]u8 = undefined;
    std.crypto.random.bytes(&rand_bytes);
    var h = Sha256.init(.{});
    h.update(&rand_bytes);
    const t_bytes = std.mem.toBytes(std.time.nanoTimestamp());
    h.update(&t_bytes);
    const digest = h.finalResult();
    const hex_chars = "0123456789abcdef";
    for (digest, 0..) |byte, i| {
        buf[i * 2] = hex_chars[byte >> 4];
        buf[i * 2 + 1] = hex_chars[byte & 0x0f];
    }
    return buf[0..64];
}

/// SHA-256 of IP address (never store raw IP).
fn hashIp(ip: []const u8, buf: *[64]u8) []const u8 {
    var h = Sha256.init(.{});
    h.update(ip);
    const digest = h.finalResult();
    const hex_chars = "0123456789abcdef";
    for (digest, 0..) |byte, i| {
        buf[i * 2] = hex_chars[byte >> 4];
        buf[i * 2 + 1] = hex_chars[byte & 0x0f];
    }
    return buf[0..64];
}

// ── Audit helper ──────────────────────────────────────────────────────────────

/// Append an audit entry. Returns false if the append fails (caller should abort).
fn auditAppend(
    database: *podos.db.Database,
    cred_id: []const u8,
    operation: []const u8,
    actor_id: []const u8,
    tool_name: ?[]const u8,
    share_id_opt: ?[]const u8,
    ip_fp: []const u8,
    decision: []const u8,
) bool {
    cred_audit.append(
        database, cred_id, operation, actor_id,
        tool_name, share_id_opt, ip_fp, decision, null,
    ) catch return false;
    return true;
}

// ── Encrypt / decrypt via transit engine ─────────────────────────────────────

const AAD = "credential:secret";

fn encryptSecret(
    engine: *podos.transit.TransitEngine,
    owner_id: []const u8,
    secret: []const u8,
    out: []u8,
) !usize {
    return engine.encryptForUser(owner_id, secret, AAD, out);
}

// ── HANDLER: POST /api/credentials ───────────────────────────────────────────

const CreateRequest = struct {
    name: []const u8 = "",
    service: []const u8 = "",
    category: []const u8 = "",
    secret: []const u8 = "",          // plaintext — encrypted immediately, never logged
    scoped_tools: ?std.json.Value = null,
    expires_at: ?[]const u8 = null,
};

fn handleCreate(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_engine = _transit orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [256]u8 = undefined;
    const owner_id = requireAuth(ctx, &uid_buf) orelse return;

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    const parsed = json_mod.parse(CreateRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    if (req.name.len == 0) return ctx.sendError(.bad_request, "name required");
    if (req.secret.len == 0) return ctx.sendError(.bad_request, "secret required");

    // Encrypt secret via transit engine
    var enc_buf: [4096]u8 = undefined;
    const enc_len = encryptSecret(transit_engine, owner_id, req.secret, &enc_buf) catch
        return ctx.sendError(.internal_server_error, "Encryption failed — is vault unlocked?");

    // Build scoped_tools JSON
    var tools_buf: [512]u8 = undefined;
    const tools_json: []const u8 = if (req.scoped_tools) |tv| blk: {
        const len = json_mod.stringifyBuf(tv, &tools_buf) catch break :blk "[]";
        break :blk tools_buf[0..len];
    } else "[]";

    // Generate ID
    var id_buf: [64]u8 = undefined;
    const new_id = generateId(&id_buf);

    // Audit BEFORE write (fail-safe: if audit fails, abort)
    var ip_fp_buf: [64]u8 = undefined;
    const ip_fp = hashIp(http.getClientIp(ctx), &ip_fp_buf);
    if (!auditAppend(database, new_id, "created", owner_id, null, null, ip_fp, "allowed")) {
        return ctx.sendError(.internal_server_error, "Audit write failed");
    }

    cred.create(
        database, new_id, owner_id,
        req.name, req.service, req.category,
        enc_buf[0..enc_len], tools_json, req.expires_at,
    ) catch return ctx.sendError(.internal_server_error, "Store failed");

    var resp_buf: [512]u8 = undefined;
    var esc_id: [128]u8 = undefined;
    const id_len_esc = json_mod.escapeJsonString(new_id, &esc_id) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const body = std.fmt.bufPrint(&resp_buf, "{{\"id\":\"{s}\",\"status\":\"stored\"}}", .{esc_id[0..id_len_esc]}) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    try ctx.json(.created, body);
}

// ── HANDLER: GET /api/credentials ────────────────────────────────────────────

fn handleList(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [256]u8 = undefined;
    const owner_id = requireAuth(ctx, &uid_buf) orelse return;

    var out_buf: [65536]u8 = undefined;
    const n = cred.list(database, owner_id, &out_buf) catch
        return ctx.sendError(.internal_server_error, "List failed");

    try ctx.json(.ok, out_buf[0..n]);
}

// ── HANDLER: GET /api/credentials/:id and /api/credentials/:id/usage ─────────

fn handleGetOrUsage(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [256]u8 = undefined;
    const owner_id = requireAuth(ctx, &uid_buf) orelse return;

    // Path: /api/credentials/{id} or /api/credentials/{id}/usage
    const prefix = "/api/credentials/";
    if (ctx.path.len <= prefix.len) return ctx.sendError(.bad_request, "Missing credential ID");
    const rest = ctx.path[prefix.len..];

    const is_usage = std.mem.endsWith(u8, rest, "/usage");
    const cred_id = if (is_usage) rest[0 .. rest.len - "/usage".len] else rest;

    if (is_usage) {
        // GET /api/credentials/:id/usage
        var out_buf: [65536]u8 = undefined;
        const n = cred_audit.query(database, cred_id, 50, &out_buf) catch
            return ctx.sendError(.internal_server_error, "Query failed");
        try ctx.json(.ok, out_buf[0..n]);
    } else {
        // GET /api/credentials/:id — metadata only (no secret)
        var out_buf: [65536]u8 = undefined;
        const n = cred.list(database, owner_id, &out_buf) catch
            return ctx.sendError(.internal_server_error, "List failed");
        // Filter client-side in JSON (simple approach — find the matching id)
        // For a single credential, extract the matching item
        try ctx.json(.ok, out_buf[0..n]);
    }
}

// ── HANDLER: DELETE /api/credentials/:id ──────────────────────────────────────

fn handleDeactivate(ctx: *http.RequestContext) !void {
    if (ctx.method != .DELETE) return ctx.sendError(.method_not_allowed, "Method not allowed");
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [256]u8 = undefined;
    const owner_id = requireAuth(ctx, &uid_buf) orelse return;

    const prefix = "/api/credentials/";
    if (ctx.path.len <= prefix.len) return ctx.sendError(.bad_request, "Missing credential ID");
    const cred_id = ctx.path[prefix.len..];

    var ip_fp_buf: [64]u8 = undefined;
    const ip_fp = hashIp(http.getClientIp(ctx), &ip_fp_buf);

    // Audit first
    if (!auditAppend(database, cred_id, "deactivated", owner_id, null, null, ip_fp, "allowed")) {
        return ctx.sendError(.internal_server_error, "Audit write failed");
    }

    cred.deactivate(database, cred_id, owner_id) catch |err| switch (err) {
        cred.CredentialError.PermissionDenied => return ctx.sendError(.forbidden, "Access denied"),
        else => return ctx.sendError(.internal_server_error, "Deactivation failed"),
    };

    try ctx.json(.ok, "{\"status\":\"deactivated\"}");
}

// ── HANDLER: POST /api/credentials/:id/rotate and /api/credentials/:id/share ─

const RotateRequest = struct {
    new_secret: []const u8 = "",
};

const ShareRequest = struct {
    grantee_id: []const u8 = "",
    grantee_type: []const u8 = "user",
    expires_at: []const u8 = "",
    max_uses: ?i32 = null,
};

fn handlePostSubRoute(ctx: *http.RequestContext) !void {
    if (ctx.method != .POST) return ctx.sendError(.method_not_allowed, "Method not allowed");

    const prefix = "/api/credentials/";
    if (ctx.path.len <= prefix.len) return ctx.sendError(.bad_request, "Missing credential ID");
    const rest = ctx.path[prefix.len..];

    if (std.mem.endsWith(u8, rest, "/rotate")) {
        const cred_id = rest[0 .. rest.len - "/rotate".len];
        return handleRotate(ctx, cred_id);
    } else if (std.mem.endsWith(u8, rest, "/share")) {
        const cred_id = rest[0 .. rest.len - "/share".len];
        return handleShare(ctx, cred_id);
    } else {
        return ctx.sendError(.not_found, "Unknown sub-route");
    }
}

fn handleRotate(ctx: *http.RequestContext, cred_id: []const u8) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_engine = _transit orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [256]u8 = undefined;
    const owner_id = requireAuth(ctx, &uid_buf) orelse return;

    const parsed = json_mod.parse(RotateRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    if (parsed.value.new_secret.len == 0) return ctx.sendError(.bad_request, "new_secret required");

    var enc_buf: [4096]u8 = undefined;
    const enc_len = encryptSecret(transit_engine, owner_id, parsed.value.new_secret, &enc_buf) catch
        return ctx.sendError(.internal_server_error, "Encryption failed");

    var ip_fp_buf: [64]u8 = undefined;
    const ip_fp = hashIp(http.getClientIp(ctx), &ip_fp_buf);
    if (!auditAppend(database, cred_id, "rotated", owner_id, null, null, ip_fp, "allowed")) {
        return ctx.sendError(.internal_server_error, "Audit write failed");
    }

    cred.updateSecret(database, cred_id, owner_id, enc_buf[0..enc_len]) catch |err| switch (err) {
        cred.CredentialError.PermissionDenied => return ctx.sendError(.forbidden, "Access denied"),
        else => return ctx.sendError(.internal_server_error, "Rotation failed"),
    };

    try ctx.json(.ok, "{\"status\":\"rotated\"}");
}

fn handleShare(ctx: *http.RequestContext, cred_id: []const u8) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [256]u8 = undefined;
    const owner_id = requireAuth(ctx, &uid_buf) orelse return;

    const parsed = json_mod.parse(ShareRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    if (req.grantee_id.len == 0) return ctx.sendError(.bad_request, "grantee_id required");
    if (req.expires_at.len == 0) return ctx.sendError(.bad_request, "expires_at required");

    var id_buf: [64]u8 = undefined;
    const share_id = generateId(&id_buf);

    var ip_fp_buf: [64]u8 = undefined;
    const ip_fp = hashIp(http.getClientIp(ctx), &ip_fp_buf);
    if (!auditAppend(database, cred_id, "shared", owner_id, null, share_id, ip_fp, "allowed")) {
        return ctx.sendError(.internal_server_error, "Audit write failed");
    }

    cred.shareCreate(
        database,
        share_id, cred_id, owner_id,
        req.grantee_id, req.grantee_type,
        req.expires_at,
        req.max_uses, null,
    ) catch |err| switch (err) {
        cred.CredentialError.PermissionDenied => return ctx.sendError(.forbidden, "Access denied"),
        else => return ctx.sendError(.internal_server_error, "Share creation failed"),
    };

    var resp_buf: [256]u8 = undefined;
    var esc_sid: [128]u8 = undefined;
    const sid_len = json_mod.escapeJsonString(share_id, &esc_sid) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const body = std.fmt.bufPrint(&resp_buf, "{{\"share_id\":\"{s}\",\"status\":\"shared\"}}", .{esc_sid[0..sid_len]}) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    try ctx.json(.created, body);
}

// ── HANDLER: DELETE /api/credentials/shares/:id ──────────────────────────────

fn handleRevokeShare(ctx: *http.RequestContext) !void {
    if (ctx.method != .DELETE) return ctx.sendError(.method_not_allowed, "Method not allowed");
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [256]u8 = undefined;
    const grantor_id = requireAuth(ctx, &uid_buf) orelse return;

    const prefix = "/api/credentials/shares/";
    if (ctx.path.len <= prefix.len) return ctx.sendError(.bad_request, "Missing share ID");
    const share_id = ctx.path[prefix.len..];

    // Lookup cred_id from the share for audit
    var cred_id_buf: [128]u8 = "unknown".*;
    var cred_id_len: usize = 7;
    {
        var q = database.prepare("SELECT credential_id FROM credential_shares WHERE id = ?") catch {};
        defer q.finalize();
        q.bindText(1, share_id.ptr, @intCast(share_id.len)) catch {};
        if (q.step() catch false) {
            if (q.getText(0)) |ptr| {
                const s = std.mem.span(ptr);
                const cp = @min(s.len, cred_id_buf.len);
                @memcpy(cred_id_buf[0..cp], s[0..cp]);
                cred_id_len = cp;
            }
        }
    }

    var ip_fp_buf: [64]u8 = undefined;
    const ip_fp = hashIp(http.getClientIp(ctx), &ip_fp_buf);
    if (!auditAppend(database, cred_id_buf[0..cred_id_len], "share_revoked", grantor_id, null, share_id, ip_fp, "allowed")) {
        return ctx.sendError(.internal_server_error, "Audit write failed");
    }

    cred.shareRevoke(database, share_id, grantor_id) catch
        return ctx.sendError(.internal_server_error, "Revoke failed");

    try ctx.json(.ok, "{\"status\":\"revoked\"}");
}
