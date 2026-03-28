// handlers/pin.zig — Native Zig handler for PIN status check.
//
// PIN set/verify stay in Python (need pin_tokens dict + Argon2 hash compare).
// Only the read-only status check is migrated for dashboard load performance.
//
// Routes:
//   GET /api/users/{id}/pin/status → handlePinStatus

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");

var _db: ?*podos.db.Database = null;
var _rate_limiter: ?*podos.rate_limit.RateLimiter = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setRateLimiter(rl: *podos.rate_limit.RateLimiter) void {
    _rate_limiter = rl;
}

pub fn registerRoutes() void {
    router.addPrefix(.GET, "/api/users/", handleGetPinStatus);
}

fn handleGetPinStatus(ctx: *http.RequestContext) !void {
    // Only handle /api/users/{id}/pin/status
    if (std.mem.indexOf(u8, ctx.path, "/pin/status") == null) {
        return http.proxyFromHandler(ctx);
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

    var stmt = database.prepare(
        "SELECT pin_hash FROM users WHERE id = ?",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    if (!(stmt.step() catch false)) {
        return ctx.sendError(.not_found, "User not found");
    }

    const pin_hash_ptr = stmt.getText(0);
    const has_pin = pin_hash_ptr != null;

    const body = if (has_pin) "{\"has_pin\":true}" else "{\"has_pin\":false}";
    try ctx.json(.ok, body);
}
