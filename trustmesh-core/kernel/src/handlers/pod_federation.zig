// handlers/pod_federation.zig — Native Zig handlers for inbound federation routes.
//
// Handles cross-pod connection requests arriving from remote pods.
// These endpoints are unauthenticated (DID-signed), rate-limited by from_did.
//
// Routes:
//   POST /api/pod/connection-request → handleInboundConnectionRequest
//   POST /api/pod/connection-accept  → handleInboundConnectionAccept

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;
const fed_auth = podos.federation_auth;

// ── Module-level state set from server_main.zig ──
var _db: ?*podos.db.Database = null;
var _rate_limiter: ?*podos.rate_limit.RateLimiter = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setRateLimiter(rl: *podos.rate_limit.RateLimiter) void {
    _rate_limiter = rl;
}

pub fn registerRoutes() void {
    router.addExact(.POST, "/api/pod/connection-request", handleInboundConnectionRequest);
    router.addExact(.POST, "/api/pod/connection-accept", handleInboundConnectionAccept);
}

// ═══════════════════════════════════════════
//  INPUT VALIDATION
// ═══════════════════════════════════════════

fn isValidDid(s: []const u8) bool {
    if (s.len < 10 or s.len > 150) return false;
    return std.mem.startsWith(u8, s, "did:key:");
}

fn isValidPodUrl(s: []const u8) bool {
    if (s.len < 10 or s.len > 500) return false;
    return std.mem.startsWith(u8, s, "https://") or std.mem.startsWith(u8, s, "http://");
}

/// Extract hostname from URL for ghost username construction.
/// Strips scheme, strips path, strips port, truncates to 253 chars, replaces @ with _.
fn extractHostnameForGhost(url: []const u8, buf: []u8) []const u8 {
    // Must have "://" separator
    const sep = std.mem.indexOf(u8, url, "://") orelse return "unknown";
    const after_scheme = url[sep + 3 ..];

    // Stop at path separator
    var host_end: usize = after_scheme.len;
    if (std.mem.indexOfScalar(u8, after_scheme, '/')) |slash| {
        host_end = slash;
    }
    var host = after_scheme[0..host_end];

    // Strip port (colon after host)
    if (std.mem.indexOfScalar(u8, host, ':')) |colon| {
        host = host[0..colon];
    }

    // Truncate to 253 chars (DNS limit)
    if (host.len > 253) host = host[0..253];

    // Copy to buf, replacing @ with _ (prevent username injection)
    const copy_len = @min(host.len, buf.len);
    for (host[0..copy_len], 0..) |ch, i| {
        buf[i] = if (ch == '@') '_' else ch;
    }
    return buf[0..copy_len];
}

// ═══════════════════════════════════════════
//  POST /api/pod/connection-request
// ═══════════════════════════════════════════

fn handleInboundConnectionRequest(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    const InboundRequest = struct {
        from_did: ?[]const u8 = null,
        from_pod_url: ?[]const u8 = null,
        from_display_name: ?[]const u8 = null,
        to_did: ?[]const u8 = null,
        message: ?[]const u8 = null,
    };

    const parsed = json_mod.parse(InboundRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const from_did = req.from_did orelse return ctx.sendError(.bad_request, "from_did required");
    const from_pod_url = req.from_pod_url orelse return ctx.sendError(.bad_request, "from_pod_url required");
    const from_display_name = req.from_display_name orelse return ctx.sendError(.bad_request, "from_display_name required");
    const to_did = req.to_did orelse return ctx.sendError(.bad_request, "to_did required");
    const message = req.message orelse "";

    // Input validation (SEC: length-check all fields before touching DB)
    if (!isValidDid(from_did)) return ctx.sendError(.bad_request, "Invalid from_did");
    if (!isValidDid(to_did)) return ctx.sendError(.bad_request, "Invalid to_did");
    if (!isValidPodUrl(from_pod_url)) return ctx.sendError(.bad_request, "Invalid from_pod_url");
    if (from_display_name.len < 1 or from_display_name.len > 100)
        return ctx.sendError(.bad_request, "from_display_name must be 1-100 chars");
    if (message.len > 500)
        return ctx.sendError(.bad_request, "message too long (max 500)");

    // Rate limit by from_did (prevents ghost-flooding)
    if (_rate_limiter) |rl| {
        const check = rl.checkConnection(from_did);
        if (!check.allowed) return ctx.sendError(.too_many_requests, check.getMessage());
    }

    // Verify federation signature
    const verify_status = fed_auth.verifyRequest(
        from_did,
        ctx.body,
        ctx.getHeader("X-TrustMesh-Timestamp"),
        ctx.getHeader("X-TrustMesh-Nonce"),
        ctx.getHeader("X-TrustMesh-Signature"),
        ctx.getHeader("X-TrustMesh-Method"),
        ctx.getHeader("X-TrustMesh-Path"),
        ctx.allocator,
    ) catch return ctx.sendError(.internal_server_error, "Verification error");

    if (verify_status == .invalid) {
        return ctx.sendError(.unauthorized, "Invalid federation signature");
    }
    // .missing = backward compat (log a warning but allow)
    if (verify_status == .missing) {
        std.log.warn("connection-request from {s}: missing federation signature (unsigned)", .{from_did[0..@min(from_did.len, 30)]});
    }

    // Resolve recipient by DID (must be a local non-remote user)
    var local_user_id_buf: [64]u8 = undefined;
    var local_user_id_len: usize = 0;
    {
        var stmt = database.prepare(
            "SELECT u.id FROM agents a JOIN users u ON u.id = a.owner_id " ++
                "WHERE a.did = ? AND u.is_remote = 0 LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, to_did.ptr, @intCast(to_did.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Recipient not found on this pod");
        }
        const id_ptr = stmt.getText(0) orelse return ctx.sendError(.not_found, "Recipient not found");
        const id_s = std.mem.span(id_ptr);
        if (id_s.len > local_user_id_buf.len) return ctx.sendError(.internal_server_error, "ID too long");
        @memcpy(local_user_id_buf[0..id_s.len], id_s);
        local_user_id_len = id_s.len;
    }
    const local_user_id = local_user_id_buf[0..local_user_id_len];

    // Ghost upsert: idempotently create ghost user for sender
    // Username: "remote:{from_did}@{hostname}"
    var hostname_buf: [256]u8 = undefined;
    const hostname = extractHostnameForGhost(from_pod_url, &hostname_buf);

    var ghost_username_buf: [512]u8 = undefined;
    const ghost_username = std.fmt.bufPrint(&ghost_username_buf, "remote:{s}@{s}", .{
        from_did, hostname,
    }) catch return ctx.sendError(.internal_server_error, "Username build failed");
    // Truncate to 500 chars max (users.username VARCHAR(50) — but ghost names can be longer)
    const safe_username = ghost_username[0..@min(ghost_username.len, 499)];

    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // Generate a UUID for the potential new ghost
    var ghost_id_gen_buf: [36]u8 = undefined;
    common.generateUuid(&ghost_id_gen_buf);

    // Build ghost bio: "Remote user on {hostname}"
    var ghost_bio_buf: [320]u8 = undefined;
    const ghost_bio = std.fmt.bufPrint(&ghost_bio_buf, "Remote user on {s}", .{hostname}) catch "Remote user";

    // INSERT ghost (ON CONFLICT(username) DO NOTHING — username has UNIQUE constraint)
    // Must include all NOT NULL columns: bio, agent_mode, active_context
    {
        var stmt = database.prepare(
            "INSERT INTO users " ++
                "(id, username, display_name, bio, user_type, agent_mode, is_remote, is_discoverable, " ++
                "is_demo, remote_did, remote_pod_url, connectivity_mode, active_context, created_at) " ++
                "VALUES (?,?,?,?,?,?,1,0,0,?,?,'invite_only','all',?) " ++
                "ON CONFLICT(username) DO NOTHING",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, &ghost_id_gen_buf, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, safe_username.ptr, @intCast(safe_username.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, from_display_name.ptr, @intCast(from_display_name.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, ghost_bio.ptr, @intCast(ghost_bio.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, "person", 6) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(6, "private", 7) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(7, from_did.ptr, @intCast(from_did.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(8, from_pod_url.ptr, @intCast(from_pod_url.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(9, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Ghost insert failed");
    }

    // Fetch ghost ID by remote_did
    var ghost_id_buf: [64]u8 = undefined;
    var ghost_id_len: usize = 0;
    {
        var stmt = database.prepare(
            "SELECT id FROM users WHERE remote_did = ? AND is_remote = 1 LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, from_did.ptr, @intCast(from_did.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.internal_server_error, "Ghost user not found after upsert");
        }
        const gid_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "Ghost ID null");
        const gid_s = std.mem.span(gid_ptr);
        if (gid_s.len > ghost_id_buf.len) return ctx.sendError(.internal_server_error, "Ghost ID too long");
        @memcpy(ghost_id_buf[0..gid_s.len], gid_s);
        ghost_id_len = gid_s.len;
    }
    const ghost_id = ghost_id_buf[0..ghost_id_len];

    // Idempotency: check existing Connection (both directions)
    {
        var stmt = database.prepare(
            "SELECT id FROM connections WHERE " ++
                "((from_user_id = ? AND to_user_id = ?) OR " ++
                "(from_user_id = ? AND to_user_id = ?)) " ++
                "AND status = 'accepted' LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, ghost_id.ptr, @intCast(ghost_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, local_user_id.ptr, @intCast(local_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, local_user_id.ptr, @intCast(local_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, ghost_id.ptr, @intCast(ghost_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        if (stmt.step() catch false) {
            return ctx.json(.ok, "{\"status\":\"already_connected\"}");
        }
    }

    // Idempotency: check existing pending ConnectionRequest (ghost → local)
    {
        var stmt = database.prepare(
            "SELECT id FROM connection_requests " ++
                "WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending' LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, ghost_id.ptr, @intCast(ghost_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, local_user_id.ptr, @intCast(local_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        if (stmt.step() catch false) {
            return ctx.json(.ok, "{\"status\":\"already_pending\"}");
        }
    }

    // Generate IDs for new records
    var req_id_buf: [36]u8 = undefined;
    common.generateUuid(&req_id_buf);
    const req_id = req_id_buf[0..36];

    var notif_id_buf: [36]u8 = undefined;
    common.generateUuid(&notif_id_buf);
    const notif_id = notif_id_buf[0..36];

    // Build notification body
    var notif_body_buf: [256]u8 = undefined;
    const notif_body = std.fmt.bufPrint(
        &notif_body_buf,
        "{s} wants to connect with you.",
        .{from_display_name},
    ) catch return ctx.sendError(.internal_server_error, "Notification text failed");

    // BEGIN IMMEDIATE transaction
    database.exec("BEGIN IMMEDIATE") catch return ctx.sendError(.internal_server_error, "DB error");
    errdefer database.exec("ROLLBACK") catch {};

    // INSERT connection_request
    {
        var stmt = database.prepare(
            "INSERT INTO connection_requests " ++
                "(id, from_user_id, to_user_id, message, status, created_at) " ++
                "VALUES (?, ?, ?, ?, 'pending', ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, req_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ghost_id.ptr, @intCast(ghost_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, local_user_id.ptr, @intCast(local_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, message.ptr, @intCast(message.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "ConnectionRequest insert failed");
    }

    // INSERT notification
    {
        var stmt = database.prepare(
            "INSERT INTO notifications " ++
                "(id, user_id, notification_type, title, body, is_read, related_id, created_at) " ++
                "VALUES (?, ?, 'connection_request', 'New connection request', ?, 0, ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, notif_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, local_user_id.ptr, @intCast(local_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, notif_body.ptr, @intCast(notif_body.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, req_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Notification insert failed");
    }

    database.exec("COMMIT") catch return ctx.sendError(.internal_server_error, "Commit failed");

    // Record rate limit hit (after commit succeeds)
    if (_rate_limiter) |rl| {
        rl.recordConnection(from_did) catch {};
    }

    const response = try std.fmt.allocPrint(ctx.allocator,
        "{{\"status\":\"ok\",\"request_id\":\"{s}\"}}",
        .{req_id},
    );
    try ctx.json(.ok, response);
}

// ═══════════════════════════════════════════
//  POST /api/pod/connection-accept
// ═══════════════════════════════════════════

fn handleInboundConnectionAccept(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    const InboundAccept = struct {
        accepted_by_did: ?[]const u8 = null,
        requester_did: ?[]const u8 = null,
        accepted_by_display_name: ?[]const u8 = null,
    };

    const parsed = json_mod.parse(InboundAccept, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const accepted_by_did = req.accepted_by_did orelse return ctx.sendError(.bad_request, "accepted_by_did required");
    const requester_did = req.requester_did orelse return ctx.sendError(.bad_request, "requester_did required");
    const accepted_by_display_name = req.accepted_by_display_name orelse return ctx.sendError(.bad_request, "accepted_by_display_name required");

    // Input validation
    if (!isValidDid(accepted_by_did)) return ctx.sendError(.bad_request, "Invalid accepted_by_did");
    if (!isValidDid(requester_did)) return ctx.sendError(.bad_request, "Invalid requester_did");
    if (accepted_by_display_name.len < 1 or accepted_by_display_name.len > 100)
        return ctx.sendError(.bad_request, "accepted_by_display_name must be 1-100 chars");

    // Rate limit by accepted_by_did
    if (_rate_limiter) |rl| {
        const check = rl.checkConnection(accepted_by_did);
        if (!check.allowed) return ctx.sendError(.too_many_requests, check.getMessage());
    }

    // Verify federation signature (signer = accepted_by_did)
    const verify_status = fed_auth.verifyRequest(
        accepted_by_did,
        ctx.body,
        ctx.getHeader("X-TrustMesh-Timestamp"),
        ctx.getHeader("X-TrustMesh-Nonce"),
        ctx.getHeader("X-TrustMesh-Signature"),
        ctx.getHeader("X-TrustMesh-Method"),
        ctx.getHeader("X-TrustMesh-Path"),
        ctx.allocator,
    ) catch return ctx.sendError(.internal_server_error, "Verification error");

    if (verify_status == .invalid) {
        return ctx.sendError(.unauthorized, "Invalid federation signature");
    }
    if (verify_status == .missing) {
        std.log.warn("connection-accept from {s}: missing federation signature (unsigned)", .{accepted_by_did[0..@min(accepted_by_did.len, 30)]});
    }

    // Resolve local requester by DID
    var local_user_id_buf: [64]u8 = undefined;
    var local_user_id_len: usize = 0;
    {
        var stmt = database.prepare(
            "SELECT u.id FROM agents a JOIN users u ON u.id = a.owner_id " ++
                "WHERE a.did = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, requester_did.ptr, @intCast(requester_did.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Original requester not found on this pod");
        }
        const id_ptr = stmt.getText(0) orelse return ctx.sendError(.not_found, "Requester not found");
        const id_s = std.mem.span(id_ptr);
        if (id_s.len > local_user_id_buf.len) return ctx.sendError(.internal_server_error, "ID too long");
        @memcpy(local_user_id_buf[0..id_s.len], id_s);
        local_user_id_len = id_s.len;
    }
    const local_user_id = local_user_id_buf[0..local_user_id_len];

    // Try to find ghost user for the accepting remote user
    var ghost_id_buf: [64]u8 = undefined;
    var ghost_id_len: usize = 0;
    var has_ghost = false;
    {
        var stmt = database.prepare(
            "SELECT id FROM users WHERE remote_did = ? AND is_remote = 1 LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, accepted_by_did.ptr, @intCast(accepted_by_did.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (stmt.step() catch false) {
            const gid_ptr = stmt.getText(0) orelse "";
            const gid_s = std.mem.span(gid_ptr);
            if (gid_s.len > 0 and gid_s.len <= ghost_id_buf.len) {
                @memcpy(ghost_id_buf[0..gid_s.len], gid_s);
                ghost_id_len = gid_s.len;
                has_ghost = true;
            }
        }
    }
    const ghost_id = if (has_ghost) ghost_id_buf[0..ghost_id_len] else "";

    // Find the pending ConnectionRequest
    // (local_user sent the original request; ghost/unknown accepted it)
    var req_id_buf: [64]u8 = undefined;
    var req_id_len: usize = 0;
    var req_from_id_buf: [64]u8 = undefined;
    var req_from_id_len: usize = 0;
    var req_to_id_buf: [64]u8 = undefined;
    var req_to_id_len: usize = 0;

    if (has_ghost) {
        // Local user sent to ghost: from_user_id=local, to_user_id=ghost
        var stmt = database.prepare(
            "SELECT id, from_user_id, to_user_id FROM connection_requests " ++
                "WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending' LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, local_user_id.ptr, @intCast(local_user_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ghost_id.ptr, @intCast(ghost_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "No matching pending connection request found");
        }
        const rid_ptr = stmt.getText(0) orelse return ctx.sendError(.not_found, "Request ID null");
        const rid_s = std.mem.span(rid_ptr);
        if (rid_s.len > req_id_buf.len) return ctx.sendError(.internal_server_error, "ID too long");
        @memcpy(req_id_buf[0..rid_s.len], rid_s);
        req_id_len = rid_s.len;

        const from_ptr = stmt.getText(1);
        const from_s = if (from_ptr) |p| std.mem.span(p) else "";
        if (from_s.len <= req_from_id_buf.len) {
            @memcpy(req_from_id_buf[0..from_s.len], from_s);
            req_from_id_len = from_s.len;
        }
        const to_ptr = stmt.getText(2);
        const to_s = if (to_ptr) |p| std.mem.span(p) else "";
        if (to_s.len <= req_to_id_buf.len) {
            @memcpy(req_to_id_buf[0..to_s.len], to_s);
            req_to_id_len = to_s.len;
        }
    } else {
        // Ghost not found — fallback to most recent pending request from local user
        var stmt = database.prepare(
            "SELECT id, from_user_id, to_user_id FROM connection_requests " ++
                "WHERE from_user_id = ? AND status = 'pending' " ++
                "ORDER BY created_at DESC LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, local_user_id.ptr, @intCast(local_user_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "No matching pending connection request found");
        }
        const rid_ptr = stmt.getText(0) orelse return ctx.sendError(.not_found, "Request ID null");
        const rid_s = std.mem.span(rid_ptr);
        if (rid_s.len > req_id_buf.len) return ctx.sendError(.internal_server_error, "ID too long");
        @memcpy(req_id_buf[0..rid_s.len], rid_s);
        req_id_len = rid_s.len;

        const from_ptr = stmt.getText(1);
        const from_s = if (from_ptr) |p| std.mem.span(p) else "";
        if (from_s.len <= req_from_id_buf.len) {
            @memcpy(req_from_id_buf[0..from_s.len], from_s);
            req_from_id_len = from_s.len;
        }
        const to_ptr = stmt.getText(2);
        const to_s = if (to_ptr) |p| std.mem.span(p) else "";
        if (to_s.len <= req_to_id_buf.len) {
            @memcpy(req_to_id_buf[0..to_s.len], to_s);
            req_to_id_len = to_s.len;
        }
    }

    const req_id = req_id_buf[0..req_id_len];
    const from_user_id = req_from_id_buf[0..req_from_id_len];
    const to_user_id = req_to_id_buf[0..req_to_id_len];

    // Generate IDs for new records
    var conn_id_buf: [36]u8 = undefined;
    common.generateUuid(&conn_id_buf);
    const conn_id = conn_id_buf[0..36];

    var notif_id_buf: [36]u8 = undefined;
    common.generateUuid(&notif_id_buf);
    const notif_id = notif_id_buf[0..36];

    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // Build notification body
    var notif_body_buf: [256]u8 = undefined;
    const notif_body = std.fmt.bufPrint(
        &notif_body_buf,
        "{s} accepted your connection request.",
        .{accepted_by_display_name},
    ) catch return ctx.sendError(.internal_server_error, "Notification text failed");

    // BEGIN IMMEDIATE transaction
    database.exec("BEGIN IMMEDIATE") catch return ctx.sendError(.internal_server_error, "DB error");
    errdefer database.exec("ROLLBACK") catch {};

    // UPDATE connection_request → accepted
    {
        var stmt = database.prepare(
            "UPDATE connection_requests SET status='accepted', reviewed_at=? WHERE id=?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, req_id.ptr, @intCast(req_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }

    // INSERT connection
    {
        var stmt = database.prepare(
            "INSERT INTO connections " ++
                "(id, from_user_id, to_user_id, status, created_at, accepted_at) " ++
                "VALUES (?, ?, ?, 'accepted', ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, conn_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, from_user_id.ptr, @intCast(from_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, to_user_id.ptr, @intCast(to_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Connection insert failed");
    }

    // INSERT notification for local requester
    {
        var stmt = database.prepare(
            "INSERT INTO notifications " ++
                "(id, user_id, notification_type, title, body, is_read, related_id, created_at) " ++
                "VALUES (?, ?, 'connection_accepted', 'Connection request accepted', ?, 0, ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, notif_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, local_user_id.ptr, @intCast(local_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, notif_body.ptr, @intCast(notif_body.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, conn_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Notification insert failed");
    }

    database.exec("COMMIT") catch return ctx.sendError(.internal_server_error, "Commit failed");

    const response = try std.fmt.allocPrint(ctx.allocator,
        "{{\"status\":\"ok\",\"connection_id\":\"{s}\"}}",
        .{conn_id},
    );
    try ctx.json(.ok, response);
}
