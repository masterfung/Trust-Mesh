// handlers/audit.zig — Native Zig handler for audit log reads.
//
// Routes:
//   GET /api/users/{id}/audit           → handleListAudit (all events)
//   GET /api/users/{id}/audit/emergency → handleEmergencyAudit (emergency events only)

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
    // Only handle /api/users/{id}/audit paths
    if (std.mem.indexOf(u8, ctx.path, "/audit") == null) {
        return ctx.sendError(.not_found, "Not found");
    }

    // Dispatch to emergency sub-route if requested
    if (std.mem.indexOf(u8, ctx.path, "/audit/emergency")) |_| {
        return handleEmergencyAudit(ctx);
    }

    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract user_id from path: /api/users/{user_id}/audit
    const prefix = "/api/users/";
    const rest = ctx.path[prefix.len..];
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse
        return ctx.sendError(.bad_request, "Invalid path");
    const path_user_id = rest[0..slash];

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    // Query params
    const event_type_filter = common.getQueryParam(ctx.query, "event_type");
    const limit_str = common.getQueryParam(ctx.query, "limit");
    const limit_val: u32 = if (limit_str) |ls| std.fmt.parseInt(u32, ls, 10) catch 50 else 50;
    const effective_limit = @min(limit_val, 200);

    // Build SQL — correct column names matching Python AuditLog model
    var sql_buf: [768]u8 = undefined;
    var sql_len: usize = 0;

    const base =
        "SELECT id, actor_user_id, actor_did, actor_role, actor_institution, " ++
        "target_user_id, action, event_type, token_role, decision, " ++
        "reason, categories_accessed, details, created_at " ++
        "FROM audit_logs " ++
        "WHERE (actor_user_id = ? OR target_user_id = ?)";
    @memcpy(sql_buf[0..base.len], base);
    sql_len = base.len;

    if (event_type_filter != null) {
        const clause = " AND event_type = ?";
        @memcpy(sql_buf[sql_len..][0..clause.len], clause);
        sql_len += clause.len;
    }
    const order = " ORDER BY created_at DESC LIMIT ?";
    @memcpy(sql_buf[sql_len..][0..order.len], order);
    sql_len += order.len;
    sql_buf[sql_len] = 0;

    var stmt = database.prepare(@ptrCast(sql_buf[0..sql_len :0])) catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();

    // Bind user_id twice (actor OR target)
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(2, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var bind_idx: c_int = 3;
    if (event_type_filter) |et| {
        stmt.bindText(bind_idx, et.ptr, @intCast(et.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        bind_idx += 1;
    }
    stmt.bindInt(bind_idx, @intCast(effective_limit)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    try writeAuditRows(ctx, &stmt);
}

fn handleEmergencyAudit(ctx: *http.RequestContext) !void {
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

    const limit_str = common.getQueryParam(ctx.query, "limit");
    const limit_val: u32 = if (limit_str) |ls| std.fmt.parseInt(u32, ls, 10) catch 20 else 20;
    const effective_limit = @min(limit_val, 100);

    var stmt = database.prepare(
        "SELECT id, actor_user_id, actor_did, actor_role, actor_institution, " ++
            "target_user_id, action, event_type, token_role, decision, " ++
            "reason, categories_accessed, details, created_at " ++
            "FROM audit_logs " ++
            "WHERE (actor_user_id = ? OR target_user_id = ?) AND event_type = 'emergency' " ++
            "ORDER BY created_at DESC LIMIT ?",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(2, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindInt(3, @intCast(effective_limit)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    try writeAuditRows(ctx, &stmt);
}

fn writeAuditRows(ctx: *http.RequestContext, stmt: *podos.db.Statement) !void {
    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first = true;
    while (stmt.step() catch false) {
        if (!first) try result.appendSlice(ctx.allocator, ",");
        first = false;

        // col 0: id
        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        // col 1: actor_user_id
        const actor_uid_ptr = stmt.getText(1);
        const actor_uid_s = if (actor_uid_ptr) |p| std.mem.span(p) else "";
        // col 2: actor_did
        const actor_did_ptr = stmt.getText(2);
        const actor_did_s = if (actor_did_ptr) |p| std.mem.span(p) else "";
        // col 3: actor_role
        const actor_role_ptr = stmt.getText(3);
        const actor_role_s = if (actor_role_ptr) |p| std.mem.span(p) else "";
        // col 4: actor_institution
        const actor_inst_ptr = stmt.getText(4);
        const actor_inst_s = if (actor_inst_ptr) |p| std.mem.span(p) else "";
        // col 5: target_user_id
        const target_uid_ptr = stmt.getText(5);
        const target_uid_s = if (target_uid_ptr) |p| std.mem.span(p) else "";
        // col 6: action
        const action_ptr = stmt.getText(6);
        const action_s = if (action_ptr) |p| std.mem.span(p) else "";
        // col 7: event_type
        const etype_ptr = stmt.getText(7);
        const etype_s = if (etype_ptr) |p| std.mem.span(p) else "";
        // col 8: token_role
        const trole_ptr = stmt.getText(8);
        const trole_s = if (trole_ptr) |p| std.mem.span(p) else "";
        // col 9: decision
        const decision_ptr = stmt.getText(9);
        const decision_s = if (decision_ptr) |p| std.mem.span(p) else "";
        // col 10: reason
        const reason_ptr = stmt.getText(10);
        const reason_s = if (reason_ptr) |p| std.mem.span(p) else "";
        // col 11: categories_accessed
        const cats_ptr = stmt.getText(11);
        const cats_s = if (cats_ptr) |p| std.mem.span(p) else "null";
        // col 12: details
        const details_ptr = stmt.getText(12);
        const details_s = if (details_ptr) |p| std.mem.span(p) else "null";
        // col 13: created_at
        const created_ptr = stmt.getText(13);
        const created_s = if (created_ptr) |p| std.mem.span(p) else "";

        var esc_id: [128]u8 = undefined;
        var esc_actor_uid: [128]u8 = undefined;
        var esc_actor_did: [256]u8 = undefined;
        var esc_actor_role: [64]u8 = undefined;
        var esc_actor_inst: [256]u8 = undefined;
        var esc_target_uid: [128]u8 = undefined;
        var esc_action: [128]u8 = undefined;
        var esc_etype: [64]u8 = undefined;
        var esc_trole: [64]u8 = undefined;
        var esc_decision: [32]u8 = undefined;
        var esc_reason: [256]u8 = undefined;
        var esc_created: [64]u8 = undefined;

        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const eau = json_mod.escapeJsonString(actor_uid_s, &esc_actor_uid) catch continue;
        const ead = json_mod.escapeJsonString(actor_did_s, &esc_actor_did) catch continue;
        const ear = json_mod.escapeJsonString(actor_role_s, &esc_actor_role) catch continue;
        const eai = json_mod.escapeJsonString(actor_inst_s, &esc_actor_inst) catch continue;
        const etu = json_mod.escapeJsonString(target_uid_s, &esc_target_uid) catch continue;
        const eact = json_mod.escapeJsonString(action_s, &esc_action) catch continue;
        const eet = json_mod.escapeJsonString(etype_s, &esc_etype) catch continue;
        const etr = json_mod.escapeJsonString(trole_s, &esc_trole) catch continue;
        const edec = json_mod.escapeJsonString(decision_s, &esc_decision) catch continue;
        const eras = json_mod.escapeJsonString(reason_s, &esc_reason) catch continue;
        const ecr = json_mod.escapeJsonString(created_s, &esc_created) catch continue;

        // cats_s and details_s are stored as JSON (may be null or JSON array/object)
        const cats_json = if (std.mem.eql(u8, cats_s, "") or std.mem.eql(u8, cats_s, "null")) "null" else cats_s;
        const details_json = if (std.mem.eql(u8, details_s, "") or std.mem.eql(u8, details_s, "null")) "null" else details_s;

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"actor_user_id\":\"{s}\",\"actor_did\":\"{s}\"," ++
                "\"actor_role\":\"{s}\",\"actor_institution\":\"{s}\"," ++
                "\"target_user_id\":\"{s}\",\"action\":\"{s}\",\"event_type\":\"{s}\"," ++
                "\"token_role\":\"{s}\",\"decision\":\"{s}\",\"reason\":\"{s}\"," ++
                "\"categories_accessed\":{s},\"details\":{s},\"created_at\":\"{s}\"}}",
            .{
                esc_id[0..eid],
                esc_actor_uid[0..eau],
                esc_actor_did[0..ead],
                esc_actor_role[0..ear],
                esc_actor_inst[0..eai],
                esc_target_uid[0..etu],
                esc_action[0..eact],
                esc_etype[0..eet],
                esc_trole[0..etr],
                esc_decision[0..edec],
                esc_reason[0..eras],
                cats_json,
                details_json,
                esc_created[0..ecr],
            },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}
