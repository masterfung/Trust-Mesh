// handlers/users.zig — Native Zig handlers for user reads (page load hot path).
//
// Mutations stay in Python (profile update calls registry, needs async HTTP).
//
// Routes:
//   GET /api/users              → handleListUsers (discoverable users)
//   GET /api/users/{id}         → handleGetUser
//   GET /api/users/{id}/agent   → handleGetAgent
//   GET /api/users/{id}/agent/card → handleGetAgentCard

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
    router.addExact(.GET, "/api/users", handleListUsers);
    // Prefix routes for /api/users/{id}, /api/users/{id}/agent, /api/users/{id}/agent/card
    // These are dispatched by the GET prefix handler in notifications/audit/pin
    // but we register specific exact patterns to avoid conflicts
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
