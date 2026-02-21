// handlers/notifications.zig — Native Zig handlers for notification polling.
//
// Frontend polls every 3-5s. Highest frequency, simplest SQL.
//
// Routes:
//   GET  /api/users/{id}/notifications          → handleList
//   GET  /api/users/{id}/notifications/unread-count → handleUnreadCount
//   PUT  /api/notifications/{id}/read           → handleMarkRead
//   PUT  /api/users/{id}/notifications/read-all → handleMarkAllRead

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;

// ── Module-level state ──
var _db: ?*podos.db.Database = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn registerRoutes() void {
    // Prefix routes — match /api/users/{id}/notifications/*
    router.addPrefix(.GET, "/api/users/", handleGetNotifications);
    router.addPrefix(.PUT, "/api/notifications/", handleMarkRead);
    router.addPrefix(.PUT, "/api/users/", handlePutNotifications);
}

// ═══════════════════════════════════════════
//  ROUTE DISPATCH (path-based)
// ═══════════════════════════════════════════

fn handleGetNotifications(ctx: *http.RequestContext) !void {
    // Disambiguate: /api/users/{id}/notifications vs /api/users/{id}/notifications/unread-count
    // vs other /api/users/ GET routes (handled by users_handler exact routes first)
    if (std.mem.indexOf(u8, ctx.path, "/notifications/unread-count")) |_| {
        return handleUnreadCount(ctx);
    }
    if (std.mem.indexOf(u8, ctx.path, "/notifications")) |_| {
        return handleList(ctx);
    }
    // Not a notification route — will be caught by other prefix handlers or proxy
    return ctx.sendError(.not_found, "Not found");
}

fn handlePutNotifications(ctx: *http.RequestContext) !void {
    if (std.mem.indexOf(u8, ctx.path, "/notifications/read-all")) |_| {
        return handleMarkAllRead(ctx);
    }
    return ctx.sendError(.not_found, "Not found");
}

// ═══════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════

fn extractUserIdFromPath(path: []const u8) ?[]const u8 {
    // /api/users/{user_id}/notifications...
    const prefix = "/api/users/";
    if (!std.mem.startsWith(u8, path, prefix)) return null;
    const rest = path[prefix.len..];
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse return null;
    const uid = rest[0..slash];
    if (uid.len == 0 or uid.len > 128) return null;
    return uid;
}

// ═══════════════════════════════════════════
//  GET /api/users/{id}/notifications
// ═══════════════════════════════════════════

fn handleList(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    const path_user_id = extractUserIdFromPath(ctx.path) orelse
        return ctx.sendError(.bad_request, "Missing user ID");

    // Auth check: can only read own notifications
    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    var stmt = database.prepare(
        "SELECT id, user_id, notification_type, title, body, data, is_read, created_at " ++
            "FROM notifications WHERE user_id = ? " ++
            "ORDER BY is_read ASC, created_at DESC LIMIT 50",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first = true;
    while (stmt.step() catch false) {
        if (!first) try result.appendSlice(ctx.allocator, ",");
        first = false;

        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        const ntype_ptr = stmt.getText(2) orelse continue;
        const ntype_s = std.mem.span(ntype_ptr);
        const title_ptr = stmt.getText(3);
        const title_s = if (title_ptr) |p| std.mem.span(p) else "";
        const body_ptr = stmt.getText(4);
        const body_s = if (body_ptr) |p| std.mem.span(p) else "";
        const data_ptr = stmt.getText(5);
        const data_s = if (data_ptr) |p| std.mem.span(p) else "null";
        const is_read = stmt.getInt(6) != 0;
        const created_ptr = stmt.getText(7);
        const created_s = if (created_ptr) |p| std.mem.span(p) else "";

        // Escape strings for JSON
        var esc_id: [128]u8 = undefined;
        var esc_type: [64]u8 = undefined;
        var esc_title: [512]u8 = undefined;
        var esc_body: [2048]u8 = undefined;
        var esc_created: [64]u8 = undefined;
        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const etype = json_mod.escapeJsonString(ntype_s, &esc_type) catch continue;
        const etitle = json_mod.escapeJsonString(title_s, &esc_title) catch continue;
        const ebody = json_mod.escapeJsonString(body_s, &esc_body) catch continue;
        const ecreated = json_mod.escapeJsonString(created_s, &esc_created) catch continue;

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"user_id\":\"{s}\",\"notification_type\":\"{s}\",\"title\":\"{s}\",\"body\":\"{s}\",\"data\":{s},\"is_read\":{s},\"created_at\":\"{s}\"}}",
            .{
                esc_id[0..eid],
                auth_user_id,
                esc_type[0..etype],
                esc_title[0..etitle],
                esc_body[0..ebody],
                data_s,
                if (is_read) "true" else "false",
                esc_created[0..ecreated],
            },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}

// ═══════════════════════════════════════════
//  GET /api/users/{id}/notifications/unread-count
// ═══════════════════════════════════════════

fn handleUnreadCount(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    const path_user_id = extractUserIdFromPath(ctx.path) orelse
        return ctx.sendError(.bad_request, "Missing user ID");

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    var stmt = database.prepare(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    var count: c_int = 0;
    if (stmt.step() catch false) {
        count = stmt.getInt(0);
    }

    const body = try std.fmt.allocPrint(ctx.allocator, "{{\"count\":{d}}}", .{count});
    try ctx.json(.ok, body);
}

// ═══════════════════════════════════════════
//  PUT /api/notifications/{id}/read
// ═══════════════════════════════════════════

fn handleMarkRead(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract notification ID: /api/notifications/{id}/read
    const prefix = "/api/notifications/";
    const rest = if (std.mem.startsWith(u8, ctx.path, prefix))
        ctx.path[prefix.len..]
    else
        return ctx.sendError(.bad_request, "Invalid path");

    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse
        return ctx.sendError(.bad_request, "Missing /read suffix");
    const notif_id = rest[0..slash];
    if (notif_id.len == 0 or notif_id.len > 36) return ctx.sendError(.bad_request, "Invalid notification ID");

    // Verify ownership
    {
        var stmt = database.prepare(
            "SELECT user_id FROM notifications WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, notif_id.ptr, @intCast(notif_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Notification not found");
        }
        const owner_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "DB error");
        const owner_s = std.mem.span(owner_ptr);
        if (!std.mem.eql(u8, owner_s, auth_user_id)) {
            return ctx.sendError(.forbidden, "Access denied");
        }
    }

    // Update
    {
        var stmt = database.prepare(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, notif_id.ptr, @intCast(notif_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }

    try ctx.json(.ok, "{\"ok\":true}");
}

// ═══════════════════════════════════════════
//  PUT /api/users/{id}/notifications/read-all
// ═══════════════════════════════════════════

fn handleMarkAllRead(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    const path_user_id = extractUserIdFromPath(ctx.path) orelse
        return ctx.sendError(.bad_request, "Missing user ID");

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    var stmt = database.prepare(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");

    try ctx.json(.ok, "{\"ok\":true}");
}
