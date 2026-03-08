// handlers/connections.zig — Native Zig handlers for connection reads + mutations.
//
// Routes:
//   GET /api/users/{id}/connections         → handleListConnections
//   GET /api/users/{id}/connection-requests → handleListConnectionRequests
//   PUT /api/connection-requests/{id}       → handleUpdateConnectionRequest

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;
const federation = podos.federation;

var _db: ?*podos.db.Database = null;
var _session_store: ?*podos.session.SessionStore = null;
var _transit_engine: ?*podos.transit.TransitEngine = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

pub fn setTransitEngine(engine: *podos.transit.TransitEngine) void {
    _transit_engine = engine;
}

pub fn registerRoutes() void {
    // Use prefix matching — disambiguate by path content in handler
    router.addPrefix(.GET, "/api/users/", handleGetConnections);
    router.addPrefix(.PUT, "/api/connection-requests/", handleUpdateConnectionRequest);
}

fn handleGetConnections(ctx: *http.RequestContext) !void {
    if (std.mem.indexOf(u8, ctx.path, "/connection-requests")) |_| {
        return handleListConnectionRequests(ctx);
    }
    if (std.mem.indexOf(u8, ctx.path, "/connections")) |_| {
        return handleListConnections(ctx);
    }
    // Not a connections route — forward to Python proxy
    return http.proxyFromHandler(ctx);
}

// ═══════════════════════════════════════════
//  GET /api/users/{id}/connections
// ═══════════════════════════════════════════

fn handleListConnections(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract user_id from path
    const prefix = "/api/users/";
    const rest = ctx.path[prefix.len..];
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse
        return ctx.sendError(.bad_request, "Invalid path");
    const path_user_id = rest[0..slash];

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    // Bidirectional connection query with peer info
    var stmt = database.prepare(
        "SELECT c.id, c.from_user_id, c.to_user_id, c.context, c.status, " ++
            "c.relationship_type, c.from_label, c.to_label, c.created_at, c.accepted_at, " ++
            "u.id, u.username, u.display_name, u.user_type, u.bio " ++
            "FROM connections c " ++
            "JOIN users u ON (CASE WHEN c.from_user_id = ? THEN u.id = c.to_user_id ELSE u.id = c.from_user_id END) " ++
            "WHERE (c.from_user_id = ? OR c.to_user_id = ?) AND c.status = 'accepted' " ++
            "ORDER BY c.accepted_at DESC",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(2, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(3, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first_entry = true;
    while (stmt.step() catch false) {
        if (!first_entry) try result.appendSlice(ctx.allocator, ",");
        first_entry = false;

        const cid_ptr = stmt.getText(0) orelse continue;
        const cid_s = std.mem.span(cid_ptr);
        const from_ptr = stmt.getText(1) orelse continue;
        const from_s = std.mem.span(from_ptr);
        const to_ptr = stmt.getText(2) orelse continue;
        const to_s = std.mem.span(to_ptr);
        const context_ptr = stmt.getText(3);
        const context_s = if (context_ptr) |p| std.mem.span(p) else "personal";
        const status_ptr = stmt.getText(4);
        const status_s = if (status_ptr) |p| std.mem.span(p) else "accepted";
        const rel_ptr = stmt.getText(5);
        const rel_s = if (rel_ptr) |p| std.mem.span(p) else "";
        const flabel_ptr = stmt.getText(6);
        const flabel_s = if (flabel_ptr) |p| std.mem.span(p) else "";
        const tlabel_ptr = stmt.getText(7);
        const tlabel_s = if (tlabel_ptr) |p| std.mem.span(p) else "";
        const peer_id_ptr = stmt.getText(10) orelse continue;
        const peer_id_s = std.mem.span(peer_id_ptr);
        const peer_username_ptr = stmt.getText(11);
        const peer_username_s = if (peer_username_ptr) |p| std.mem.span(p) else "";
        const peer_display_ptr = stmt.getText(12) orelse continue;
        const peer_display_s = std.mem.span(peer_display_ptr);
        const peer_type_ptr = stmt.getText(13);
        const peer_type_s = if (peer_type_ptr) |p| std.mem.span(p) else "person";

        var esc_cid: [128]u8 = undefined;
        var esc_ctx: [64]u8 = undefined;
        var esc_status: [64]u8 = undefined;
        var esc_rel: [64]u8 = undefined;
        var esc_flabel: [128]u8 = undefined;
        var esc_tlabel: [128]u8 = undefined;
        var esc_pid: [128]u8 = undefined;
        var esc_puname: [128]u8 = undefined;
        var esc_pdname: [256]u8 = undefined;
        var esc_ptype: [64]u8 = undefined;
        const ecid = json_mod.escapeJsonString(cid_s, &esc_cid) catch continue;
        const ectx = json_mod.escapeJsonString(context_s, &esc_ctx) catch continue;
        const estatus = json_mod.escapeJsonString(status_s, &esc_status) catch continue;
        const erel = json_mod.escapeJsonString(rel_s, &esc_rel) catch continue;
        const eflabel = json_mod.escapeJsonString(flabel_s, &esc_flabel) catch continue;
        const etlabel = json_mod.escapeJsonString(tlabel_s, &esc_tlabel) catch continue;
        const epid = json_mod.escapeJsonString(peer_id_s, &esc_pid) catch continue;
        const epuname = json_mod.escapeJsonString(peer_username_s, &esc_puname) catch continue;
        const epdname = json_mod.escapeJsonString(peer_display_s, &esc_pdname) catch continue;
        const eptype = json_mod.escapeJsonString(peer_type_s, &esc_ptype) catch continue;

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"from_user_id\":\"{s}\",\"to_user_id\":\"{s}\"," ++
                "\"context\":\"{s}\",\"status\":\"{s}\",\"relationship_type\":\"{s}\"," ++
                "\"from_label\":\"{s}\",\"to_label\":\"{s}\"," ++
                "\"peer\":{{\"id\":\"{s}\",\"username\":\"{s}\",\"display_name\":\"{s}\",\"user_type\":\"{s}\"}}}}",
            .{
                esc_cid[0..ecid], from_s, to_s,
                esc_ctx[0..ectx], esc_status[0..estatus], esc_rel[0..erel],
                esc_flabel[0..eflabel], esc_tlabel[0..etlabel],
                esc_pid[0..epid], esc_puname[0..epuname], esc_pdname[0..epdname], esc_ptype[0..eptype],
            },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}

// ═══════════════════════════════════════════
//  GET /api/users/{id}/connection-requests
// ═══════════════════════════════════════════

fn handleListConnectionRequests(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    const prefix = "/api/users/";
    const rest = ctx.path[prefix.len..];
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse
        return ctx.sendError(.bad_request, "Invalid path");
    const path_user_id = rest[0..slash];

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    var stmt = database.prepare(
        "SELECT cr.id, cr.from_user_id, cr.to_user_id, cr.message, cr.status, cr.created_at, " ++
            "u.display_name, u.user_type " ++
            "FROM connection_requests cr " ++
            "JOIN users u ON u.id = cr.from_user_id " ++
            "WHERE cr.to_user_id = ? AND cr.status = 'pending' " ++
            "ORDER BY cr.created_at DESC",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first_entry = true;
    while (stmt.step() catch false) {
        if (!first_entry) try result.appendSlice(ctx.allocator, ",");
        first_entry = false;

        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        const from_ptr = stmt.getText(1) orelse continue;
        const from_s = std.mem.span(from_ptr);
        const msg_ptr = stmt.getText(3);
        const msg_s = if (msg_ptr) |p| std.mem.span(p) else "";
        const created_ptr = stmt.getText(5);
        const created_s = if (created_ptr) |p| std.mem.span(p) else "";
        const sender_name_ptr = stmt.getText(6) orelse continue;
        const sender_name_s = std.mem.span(sender_name_ptr);

        var esc_id: [128]u8 = undefined;
        var esc_msg: [1024]u8 = undefined;
        var esc_created: [64]u8 = undefined;
        var esc_sender: [256]u8 = undefined;
        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const emsg = json_mod.escapeJsonString(msg_s, &esc_msg) catch continue;
        const ecreated = json_mod.escapeJsonString(created_s, &esc_created) catch continue;
        const esender = json_mod.escapeJsonString(sender_name_s, &esc_sender) catch continue;

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"from_user_id\":\"{s}\",\"to_user_id\":\"{s}\",\"message\":\"{s}\",\"status\":\"pending\",\"created_at\":\"{s}\",\"from_display_name\":\"{s}\"}}",
            .{ esc_id[0..eid], from_s, auth_user_id, esc_msg[0..emsg], esc_created[0..ecreated], esc_sender[0..esender] },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}

// ═══════════════════════════════════════════
//  PUT /api/connection-requests/{id}
// ═══════════════════════════════════════════

fn handleUpdateConnectionRequest(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract request_id from path: /api/connection-requests/{id}
    const prefix = "/api/connection-requests/";
    if (!std.mem.startsWith(u8, ctx.path, prefix)) {
        return ctx.sendError(.bad_request, "Invalid path");
    }
    const request_id = ctx.path[prefix.len..];
    // Strip any trailing path segments
    const clean_id = if (std.mem.indexOfScalar(u8, request_id, '/')) |s| request_id[0..s] else request_id;

    // Validate UUID format (36 chars)
    if (clean_id.len != 36) return ctx.sendError(.bad_request, "Invalid request ID");

    // Parse body
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    const UpdateRequest = struct {
        status: ?[]const u8 = null,
    };

    const parsed = json_mod.parse(UpdateRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();

    const new_status = parsed.value.status orelse return ctx.sendError(.bad_request, "status required");

    // Validate new status
    if (!std.mem.eql(u8, new_status, "accepted") and !std.mem.eql(u8, new_status, "declined")) {
        return ctx.sendError(.bad_request, "status must be 'accepted' or 'declined'");
    }

    // Fetch request + remote user info
    var req_to_user_id_buf: [64]u8 = undefined;
    var req_to_user_id_len: usize = 0;
    var req_from_user_id_buf: [64]u8 = undefined;
    var req_from_user_id_len: usize = 0;
    var req_status_buf: [20]u8 = undefined;
    var req_status_len: usize = 0;
    var is_remote: bool = false;
    var remote_pod_url_buf: [512]u8 = undefined;
    var remote_pod_url_len: usize = 0;
    var remote_did_buf: [150]u8 = undefined;
    var remote_did_len: usize = 0;
    var from_display_buf: [256]u8 = undefined;
    var from_display_len: usize = 0;

    {
        var stmt = database.prepare(
            "SELECT cr.from_user_id, cr.to_user_id, cr.status, " ++
                "u.is_remote, u.remote_pod_url, u.remote_did, u.display_name " ++
                "FROM connection_requests cr " ++
                "JOIN users u ON u.id = cr.from_user_id " ++
                "WHERE cr.id = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, clean_id.ptr, @intCast(clean_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Connection request not found");
        }

        // from_user_id
        const from_ptr = stmt.getText(0);
        const from_s = if (from_ptr) |p| std.mem.span(p) else "";
        if (from_s.len <= req_from_user_id_buf.len) {
            @memcpy(req_from_user_id_buf[0..from_s.len], from_s);
            req_from_user_id_len = from_s.len;
        }
        // to_user_id
        const to_ptr = stmt.getText(1);
        const to_s = if (to_ptr) |p| std.mem.span(p) else "";
        if (to_s.len <= req_to_user_id_buf.len) {
            @memcpy(req_to_user_id_buf[0..to_s.len], to_s);
            req_to_user_id_len = to_s.len;
        }
        // status
        const st_ptr = stmt.getText(2);
        const st_s = if (st_ptr) |p| std.mem.span(p) else "";
        if (st_s.len <= req_status_buf.len) {
            @memcpy(req_status_buf[0..st_s.len], st_s);
            req_status_len = st_s.len;
        }
        // is_remote
        is_remote = (stmt.getInt(3) != 0);
        // remote_pod_url
        const rpu_ptr = stmt.getText(4);
        const rpu_s = if (rpu_ptr) |p| std.mem.span(p) else "";
        if (rpu_s.len <= remote_pod_url_buf.len) {
            @memcpy(remote_pod_url_buf[0..rpu_s.len], rpu_s);
            remote_pod_url_len = rpu_s.len;
        }
        // remote_did
        const rdid_ptr = stmt.getText(5);
        const rdid_s = if (rdid_ptr) |p| std.mem.span(p) else "";
        if (rdid_s.len <= remote_did_buf.len) {
            @memcpy(remote_did_buf[0..rdid_s.len], rdid_s);
            remote_did_len = rdid_s.len;
        }
        // display_name
        const dn_ptr = stmt.getText(6);
        const dn_s = if (dn_ptr) |p| std.mem.span(p) else "";
        if (dn_s.len <= from_display_buf.len) {
            @memcpy(from_display_buf[0..dn_s.len], dn_s);
            from_display_len = dn_s.len;
        }
    }

    const req_to_user_id = req_to_user_id_buf[0..req_to_user_id_len];
    const req_from_user_id = req_from_user_id_buf[0..req_from_user_id_len];
    const req_status = req_status_buf[0..req_status_len];
    const remote_pod_url = remote_pod_url_buf[0..remote_pod_url_len];
    const remote_did = remote_did_buf[0..remote_did_len];

    // Authorization: only the recipient can accept/decline
    if (!std.mem.eql(u8, req_to_user_id, auth_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    // Verify request is still pending
    if (!std.mem.eql(u8, req_status, "pending")) {
        return ctx.sendError(.conflict, "Request already processed");
    }

    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // BEGIN IMMEDIATE transaction
    database.exec("BEGIN IMMEDIATE") catch return ctx.sendError(.internal_server_error, "DB error");
    errdefer database.exec("ROLLBACK") catch {};

    // UPDATE connection_request
    {
        var stmt = database.prepare(
            "UPDATE connection_requests SET status=?, reviewed_at=? WHERE id=?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, new_status.ptr, @intCast(new_status.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, clean_id.ptr, @intCast(clean_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }

    var conn_id_buf: [36]u8 = undefined;
    if (std.mem.eql(u8, new_status, "accepted")) {
        // INSERT connection
        common.generateUuid(&conn_id_buf);
        const conn_id = conn_id_buf[0..36];

        var stmt = database.prepare(
            "INSERT INTO connections " ++
                "(id, from_user_id, to_user_id, status, created_at, accepted_at) " ++
                "VALUES (?, ?, ?, 'accepted', ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, conn_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, req_from_user_id.ptr, @intCast(req_from_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, req_to_user_id.ptr, @intCast(req_to_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Connection insert failed");
    }

    database.exec("COMMIT") catch return ctx.sendError(.internal_server_error, "Commit failed");

    // If accepted and from a remote user: send outbound accept callback (inline, fire-and-forget)
    if (std.mem.eql(u8, new_status, "accepted") and is_remote and remote_pod_url.len > 0 and remote_did.len > 0) {
        const transit = _transit_engine orelse {
            std.log.warn("accept callback: transit engine not ready, skipping", .{});
            // Fall through — DB is committed, this is best-effort
            try sendAcceptCallbackResponse(ctx, clean_id, new_status);
            return;
        };

        // Check vault key availability
        if (!transit.hasKey(auth_user_id)) {
            std.log.warn("accept callback: vault key not loaded for user, skipping callback", .{});
            try sendAcceptCallbackResponse(ctx, clean_id, new_status);
            return;
        }

        // Get accepting user's agent DID + encrypted private key
        var our_did_buf: [150]u8 = undefined;
        var our_did_len: usize = 0;
        var enc_pk_buf: [512]u8 = undefined;
        var enc_pk_len: usize = 0;
        var our_display_buf: [256]u8 = undefined;
        var our_display_len: usize = 0;

        {
            var stmt = database.prepare(
                "SELECT a.did, a.encrypted_private_key, u.display_name " ++
                    "FROM agents a JOIN users u ON u.id = a.owner_id " ++
                    "WHERE a.owner_id = ? LIMIT 1",
            ) catch {
                std.log.warn("accept callback: DB error fetching agent", .{});
                try sendAcceptCallbackResponse(ctx, clean_id, new_status);
                return;
            };
            defer stmt.finalize();
            stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch {
                try sendAcceptCallbackResponse(ctx, clean_id, new_status);
                return;
            };
            if (!(stmt.step() catch false)) {
                std.log.warn("accept callback: agent not found for user", .{});
                try sendAcceptCallbackResponse(ctx, clean_id, new_status);
                return;
            }

            const did_ptr = stmt.getText(0);
            const did_s = if (did_ptr) |p| std.mem.span(p) else "";
            if (did_s.len <= our_did_buf.len) {
                @memcpy(our_did_buf[0..did_s.len], did_s);
                our_did_len = did_s.len;
            }

            const epk_blob = stmt.getBlob(1) orelse {
                std.log.warn("accept callback: no encrypted private key", .{});
                try sendAcceptCallbackResponse(ctx, clean_id, new_status);
                return;
            };
            if (epk_blob.len <= enc_pk_buf.len) {
                @memcpy(enc_pk_buf[0..epk_blob.len], epk_blob);
                enc_pk_len = epk_blob.len;
            }

            const dn_ptr = stmt.getText(2);
            const dn_s = if (dn_ptr) |p| std.mem.span(p) else "";
            if (dn_s.len <= our_display_buf.len) {
                @memcpy(our_display_buf[0..dn_s.len], dn_s);
                our_display_len = dn_s.len;
            }
        }

        const our_did = our_did_buf[0..our_did_len];
        const enc_pk = enc_pk_buf[0..enc_pk_len];
        const our_display = our_display_buf[0..our_display_len];

        if (our_did.len == 0 or enc_pk.len == 0) {
            std.log.warn("accept callback: missing DID or private key, skipping", .{});
            try sendAcceptCallbackResponse(ctx, clean_id, new_status);
            return;
        }

        // Decrypt private key seed (32 bytes)
        var seed_buf: [256]u8 = undefined;
        const seed_len = transit.decryptForUser(auth_user_id, enc_pk, "", &seed_buf) catch |err| {
            std.log.warn("accept callback: failed to decrypt private key: {}", .{err});
            std.crypto.secureZero(u8, &seed_buf);
            try sendAcceptCallbackResponse(ctx, clean_id, new_status);
            return;
        };
        defer std.crypto.secureZero(u8, seed_buf[0..@min(seed_len, 256)]);

        if (seed_len < 32) {
            std.log.warn("accept callback: decrypted key too short ({d} bytes)", .{seed_len});
            try sendAcceptCallbackResponse(ctx, clean_id, new_status);
            return;
        }
        const seed_32: *const [32]u8 = seed_buf[0..32];

        // Send callback (synchronous, inline — this is a UI action, brief delay is acceptable)
        const ok = federation.sendConnectionAcceptCallback(
            remote_pod_url,
            our_did,
            remote_did,
            our_display,
            seed_32,
            ctx.allocator,
        );
        if (!ok) {
            std.log.warn("accept callback to {s} failed (non-fatal, DB already committed)", .{
                remote_pod_url[0..@min(remote_pod_url.len, 60)],
            });
        }
    }

    try sendAcceptCallbackResponse(ctx, clean_id, new_status);
}

fn sendAcceptCallbackResponse(ctx: *http.RequestContext, req_id: []const u8, status: []const u8) !void {
    var esc_id: [128]u8 = undefined;
    var esc_status: [32]u8 = undefined;
    const eid = json_mod.escapeJsonString(req_id, &esc_id) catch req_id.len;
    const est = json_mod.escapeJsonString(status, &esc_status) catch status.len;
    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"status\":\"{s}\",\"id\":\"{s}\"}}",
        .{ esc_status[0..est], esc_id[0..eid] },
    );
    try ctx.json(.ok, body);
}
