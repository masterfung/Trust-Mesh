// handlers/connections.zig — Native Zig handlers for connection reads.
//
// Dashboard sidebar loads connections on every visit.
// Mutations stay in Python (rate limiting side effects, notification creation).
//
// Routes:
//   GET /api/users/{id}/connections         → handleListConnections
//   GET /api/users/{id}/connection-requests → handleListConnectionRequests

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;

var _db: ?*podos.db.Database = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn registerRoutes() void {
    // Use prefix matching — disambiguate by path content in handler
    router.addPrefix(.GET, "/api/users/", handleGetConnections);
}

fn handleGetConnections(ctx: *http.RequestContext) !void {
    if (std.mem.indexOf(u8, ctx.path, "/connection-requests")) |_| {
        return handleListConnectionRequests(ctx);
    }
    if (std.mem.indexOf(u8, ctx.path, "/connections")) |_| {
        return handleListConnections(ctx);
    }
    return ctx.sendError(.not_found, "Not found");
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
