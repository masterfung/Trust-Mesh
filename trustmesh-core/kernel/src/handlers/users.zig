// handlers/users.zig — Native Zig handlers for user reads + connectivity mutation.
//
// Routes:
//   GET   /api/users                    → handleListUsers (discoverable users)
//   PATCH /api/users/{id}/connectivity  → handlePatchConnectivity

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;

var _db: ?*podos.db.Database = null;
var _session_store: ?*podos.session.SessionStore = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

pub fn registerRoutes() void {
    router.addExact(.GET, "/api/users", handleListUsers);
    router.addPrefix(.PATCH, "/api/users/", handlePatchUser);
}

// ═══════════════════════════════════════════
//  GET /api/users (list discoverable)
// ═══════════════════════════════════════════

fn handleListUsers(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    // No auth required for listing discoverable users
    var stmt = database.prepare(
        "SELECT u.id, u.username, u.display_name, u.bio, u.user_type, u.is_discoverable, u.profile_data, " ++
            "a.id, a.name, a.personality, a.did " ++
            "FROM users u LEFT JOIN agents a ON a.owner_id = u.id " ++
            "WHERE u.is_discoverable = 1 AND u.is_remote = 0 " ++
            "ORDER BY u.display_name",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first = true;
    while (stmt.step() catch false) {
        if (!first) try result.appendSlice(ctx.allocator, ",");
        first = false;

        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        const username_ptr = stmt.getText(1);
        const username_s = if (username_ptr) |p| std.mem.span(p) else "";
        const display_ptr = stmt.getText(2) orelse continue;
        const display_s = std.mem.span(display_ptr);
        const bio_ptr = stmt.getText(3);
        const bio_s = if (bio_ptr) |p| std.mem.span(p) else "";
        const utype_ptr = stmt.getText(4) orelse continue;
        const utype_s = std.mem.span(utype_ptr);
        const profile_ptr = stmt.getText(6);
        const profile_s = if (profile_ptr) |p| std.mem.span(p) else "null";
        // Agent fields
        const agent_id_ptr = stmt.getText(7);
        const agent_name_ptr = stmt.getText(8);
        const agent_did_ptr = stmt.getText(10);

        var esc_id: [128]u8 = undefined;
        var esc_username: [128]u8 = undefined;
        var esc_display: [256]u8 = undefined;
        var esc_bio: [2048]u8 = undefined;
        var esc_utype: [64]u8 = undefined;
        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const euser = json_mod.escapeJsonString(username_s, &esc_username) catch continue;
        const edisp = json_mod.escapeJsonString(display_s, &esc_display) catch continue;
        const ebio = json_mod.escapeJsonString(bio_s, &esc_bio) catch continue;
        const eutype = json_mod.escapeJsonString(utype_s, &esc_utype) catch continue;

        // Build agent snippet if exists
        var agent_json: []const u8 = "null";
        if (agent_id_ptr) |aid_p| {
            const aid_s = std.mem.span(aid_p);
            const aname_s = if (agent_name_ptr) |p| std.mem.span(p) else "";
            const adid_s = if (agent_did_ptr) |p| std.mem.span(p) else "";
            var esc_aid: [128]u8 = undefined;
            var esc_aname: [256]u8 = undefined;
            var esc_adid: [128]u8 = undefined;
            const eaid = json_mod.escapeJsonString(aid_s, &esc_aid) catch continue;
            const eaname = json_mod.escapeJsonString(aname_s, &esc_aname) catch continue;
            const eadid = json_mod.escapeJsonString(adid_s, &esc_adid) catch continue;
            agent_json = std.fmt.allocPrint(ctx.allocator,
                "{{\"id\":\"{s}\",\"name\":\"{s}\",\"did\":\"{s}\"}}",
                .{ esc_aid[0..eaid], esc_aname[0..eaname], esc_adid[0..eadid] },
            ) catch "null";
        }

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"username\":\"{s}\",\"display_name\":\"{s}\",\"bio\":\"{s}\",\"user_type\":\"{s}\",\"is_discoverable\":true,\"profile_data\":{s},\"agent\":{s}}}",
            .{
                esc_id[0..eid],
                esc_username[0..euser],
                esc_display[0..edisp],
                esc_bio[0..ebio],
                esc_utype[0..eutype],
                profile_s,
                agent_json,
            },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}

// ═══════════════════════════════════════════
//  PATCH /api/users/{id}/connectivity
// ═══════════════════════════════════════════

fn handlePatchUser(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    // Only handle /connectivity suffix
    if (!std.mem.endsWith(u8, ctx.path, "/connectivity")) {
        return ctx.sendError(.not_found, "Not found");
    }

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract user_id from path: /api/users/{id}/connectivity
    const prefix = "/api/users/";
    if (!std.mem.startsWith(u8, ctx.path, prefix)) {
        return ctx.sendError(.bad_request, "Invalid path");
    }
    const rest = ctx.path[prefix.len..];
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse return ctx.sendError(.bad_request, "Invalid path");
    const path_user_id = rest[0..slash];

    // Authorization: user can only update their own connectivity mode
    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    // Parse body
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    const ConnectivityUpdate = struct {
        connectivity_mode: ?[]const u8 = null,
    };

    const parsed = json_mod.parse(ConnectivityUpdate, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();

    const mode = parsed.value.connectivity_mode orelse return ctx.sendError(.bad_request, "connectivity_mode required");

    // Validate against allowlist
    const valid = [_][]const u8{ "relay_primary", "direct_with_fallback", "invite_only" };
    var mode_valid = false;
    for (valid) |v| {
        if (std.mem.eql(u8, mode, v)) {
            mode_valid = true;
            break;
        }
    }
    if (!mode_valid) {
        return ctx.sendError(.bad_request, "connectivity_mode must be relay_primary, direct_with_fallback, or invite_only");
    }

    // UPDATE users SET connectivity_mode=? WHERE id=?
    {
        var stmt = database.prepare(
            "UPDATE users SET connectivity_mode=? WHERE id=?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, mode.ptr, @intCast(mode.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, auth_user_id.ptr, @intCast(auth_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }

    var esc_mode: [64]u8 = undefined;
    const emode = json_mod.escapeJsonString(mode, &esc_mode) catch mode.len;
    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"status\":\"ok\",\"connectivity_mode\":\"{s}\"}}",
        .{esc_mode[0..emode]},
    );
    try ctx.json(.ok, body);
}
