// handlers/audit.zig — Native Zig handler for audit log reads.
//
// Routes:
//   GET /api/users/{id}/audit → handleListAudit

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
    router.addPrefix(.GET, "/api/users/", handleGetAudit);
}

fn handleGetAudit(ctx: *http.RequestContext) !void {
    // Only handle /api/users/{id}/audit
    if (std.mem.indexOf(u8, ctx.path, "/audit") == null) {
        return ctx.sendError(.not_found, "Not found");
    }

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

    // Query params for filtering
    const type_filter = common.getQueryParam(ctx.query, "type");
    const action_filter = common.getQueryParam(ctx.query, "action");
    const limit_str = common.getQueryParam(ctx.query, "limit");
    const limit_val: u32 = if (limit_str) |ls| std.fmt.parseInt(u32, ls, 10) catch 50 else 50;
    const effective_limit = @min(limit_val, 200);

    // Build query dynamically based on filters
    var sql_buf: [512]u8 = undefined;
    var bind_count: usize = 1; // user_id is always bound

    var sql_len: usize = 0;
    const base = "SELECT id, user_id, audit_type, action, target_id, details, ip_address, created_at FROM audit_logs WHERE user_id = ?";
    @memcpy(sql_buf[0..base.len], base);
    sql_len = base.len;

    if (type_filter != null) {
        const clause = " AND audit_type = ?";
        @memcpy(sql_buf[sql_len..][0..clause.len], clause);
        sql_len += clause.len;
        bind_count += 1;
    }
    if (action_filter != null) {
        const clause = " AND action = ?";
        @memcpy(sql_buf[sql_len..][0..clause.len], clause);
        sql_len += clause.len;
        bind_count += 1;
    }
    const order = " ORDER BY created_at DESC LIMIT ?";
    @memcpy(sql_buf[sql_len..][0..order.len], order);
    sql_len += order.len;
    sql_buf[sql_len] = 0; // null terminate

    var stmt = database.prepare(@ptrCast(sql_buf[0..sql_len :0])) catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();

    var bind_idx: c_int = 1;
    stmt.bindText(bind_idx, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    bind_idx += 1;

    if (type_filter) |tf| {
        stmt.bindText(bind_idx, tf.ptr, @intCast(tf.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        bind_idx += 1;
    }
    if (action_filter) |af| {
        stmt.bindText(bind_idx, af.ptr, @intCast(af.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        bind_idx += 1;
    }
    stmt.bindInt(bind_idx, @intCast(effective_limit)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first = true;
    while (stmt.step() catch false) {
        if (!first) try result.appendSlice(ctx.allocator, ",");
        first = false;

        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        const atype_ptr = stmt.getText(2);
        const atype_s = if (atype_ptr) |p| std.mem.span(p) else "";
        const action_ptr = stmt.getText(3);
        const action_s = if (action_ptr) |p| std.mem.span(p) else "";
        const target_ptr = stmt.getText(4);
        const target_s = if (target_ptr) |p| std.mem.span(p) else "";
        const details_ptr = stmt.getText(5);
        const details_s = if (details_ptr) |p| std.mem.span(p) else "null";
        const ip_ptr = stmt.getText(6);
        const ip_s = if (ip_ptr) |p| std.mem.span(p) else "";
        const created_ptr = stmt.getText(7);
        const created_s = if (created_ptr) |p| std.mem.span(p) else "";

        var esc_id: [128]u8 = undefined;
        var esc_type: [64]u8 = undefined;
        var esc_action: [64]u8 = undefined;
        var esc_target: [128]u8 = undefined;
        var esc_ip: [64]u8 = undefined;
        var esc_created: [64]u8 = undefined;
        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const etype = json_mod.escapeJsonString(atype_s, &esc_type) catch continue;
        const eaction = json_mod.escapeJsonString(action_s, &esc_action) catch continue;
        const etarget = json_mod.escapeJsonString(target_s, &esc_target) catch continue;
        const eip = json_mod.escapeJsonString(ip_s, &esc_ip) catch continue;
        const ecreated = json_mod.escapeJsonString(created_s, &esc_created) catch continue;

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"user_id\":\"{s}\",\"audit_type\":\"{s}\",\"action\":\"{s}\",\"target_id\":\"{s}\",\"details\":{s},\"ip_address\":\"{s}\",\"created_at\":\"{s}\"}}",
            .{
                esc_id[0..eid],
                auth_user_id,
                esc_type[0..etype],
                esc_action[0..eaction],
                esc_target[0..etarget],
                details_s,
                esc_ip[0..eip],
                esc_created[0..ecreated],
            },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}
