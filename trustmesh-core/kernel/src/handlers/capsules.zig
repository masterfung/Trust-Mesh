// handlers/capsules.zig — Native Zig handlers for capsule CRUD (vault hot path).
//
// Uses transit encrypt/decrypt, FTS5 upsert/delete, audit logging, version tracking.
//
// Routes:
//   GET    /api/users/{id}/capsules → handleListCapsules
//   POST   /api/users/{id}/capsules → handleCreateCapsule
//   PUT    /api/capsules/{id}       → handleUpdateCapsule
//   DELETE /api/capsules/{id}       → handleDeleteCapsule

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;

const Sha256 = std.crypto.hash.sha2.Sha256;

var _db: ?*podos.db.Database = null;
var _transit_engine: ?*podos.transit.TransitEngine = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setTransitEngine(engine: *podos.transit.TransitEngine) void {
    _transit_engine = engine;
}

pub fn registerRoutes() void {
    // Capsule routes — exact and prefix
    router.addPrefix(.GET, "/api/users/", handleGetCapsules);
    router.addPrefix(.POST, "/api/users/", handlePostCapsules);
    router.addPrefix(.PUT, "/api/capsules/", handleUpdateCapsule);
    router.addPrefix(.DELETE, "/api/capsules/", handleDeleteCapsule);
}

// ═══════════════════════════════════════════
//  ROUTE DISPATCH
// ═══════════════════════════════════════════

fn handleGetCapsules(ctx: *http.RequestContext) !void {
    if (std.mem.indexOf(u8, ctx.path, "/capsules")) |_| {
        return handleListCapsules(ctx);
    }
    // Not a capsule GET route — forward to Python proxy
    return http.proxyFromHandler(ctx);
}

fn handlePostCapsules(ctx: *http.RequestContext) !void {
    if (std.mem.indexOf(u8, ctx.path, "/capsules")) |_| {
        return handleCreateCapsule(ctx);
    }
    // Not a capsule POST route — forward to Python proxy
    return http.proxyFromHandler(ctx);
}

// ═══════════════════════════════════════════
//  GET /api/users/{id}/capsules
// ═══════════════════════════════════════════

fn handleListCapsules(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

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

    // Query params
    const category_filter = common.getQueryParam(ctx.query, "category");
    const include_archived_str = common.getQueryParam(ctx.query, "include_archived");
    const include_archived = if (include_archived_str) |s| std.mem.eql(u8, s, "true") else false;

    const sql = if (category_filter != null)
        (if (include_archived)
            "SELECT id, title, content_encrypted, capsule_type, visibility, category, is_archived, created_at, updated_at, expires_at, auto_archive_days, emergency_accessible, can_reshare, context, freshness, authority_weight, content_hash, supersedes_id FROM knowledge_capsules WHERE owner_id = ? AND deleted_at IS NULL AND category = ? ORDER BY created_at DESC LIMIT 200"
        else
            "SELECT id, title, content_encrypted, capsule_type, visibility, category, is_archived, created_at, updated_at, expires_at, auto_archive_days, emergency_accessible, can_reshare, context, freshness, authority_weight, content_hash, supersedes_id FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0 AND deleted_at IS NULL AND category = ? ORDER BY created_at DESC LIMIT 200")
    else (if (include_archived)
        "SELECT id, title, content_encrypted, capsule_type, visibility, category, is_archived, created_at, updated_at, expires_at, auto_archive_days, emergency_accessible, can_reshare, context, freshness, authority_weight, content_hash, supersedes_id FROM knowledge_capsules WHERE owner_id = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 200"
    else
        "SELECT id, title, content_encrypted, capsule_type, visibility, category, is_archived, created_at, updated_at, expires_at, auto_archive_days, emergency_accessible, can_reshare, context, freshness, authority_weight, content_hash, supersedes_id FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0 AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 200");

    var stmt = database.prepare(@ptrCast(sql)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    if (category_filter) |cat| {
        stmt.bindText(2, cat.ptr, @intCast(cat.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
    }

    var result = std.ArrayList(u8){};
    try result.appendSlice(ctx.allocator, "[");

    var first = true;
    while (stmt.step() catch false) {
        if (!first) try result.appendSlice(ctx.allocator, ",");
        first = false;

        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        const title_ptr = stmt.getText(1) orelse continue;
        const title_s = std.mem.span(title_ptr);
        const enc_blob = stmt.getBlob(2) orelse continue;
        const ctype_ptr = stmt.getText(3) orelse continue;
        const ctype_s = std.mem.span(ctype_ptr);
        const vis_ptr = stmt.getText(4) orelse continue;
        const vis_s = std.mem.span(vis_ptr);
        const cat_ptr = stmt.getText(5);
        const cat_s = if (cat_ptr) |p| std.mem.span(p) else "";
        const is_archived = stmt.getInt(6) != 0;
        const created_ptr = stmt.getText(7);
        const created_s = if (created_ptr) |p| std.mem.span(p) else "";
        const updated_ptr = stmt.getText(8);
        const updated_s = if (updated_ptr) |p| std.mem.span(p) else "";
        const expires_ptr = stmt.getText(9);
        const expires_s = if (expires_ptr) |p| std.mem.span(p) else "";
        const emerg = stmt.getInt(11) != 0;
        const reshare = stmt.getInt(12) != 0;
        const context_ptr = stmt.getText(13);
        const context_s = if (context_ptr) |p| std.mem.span(p) else "personal";
        const freshness_ptr = stmt.getText(14);
        const freshness_s = if (freshness_ptr) |p| std.mem.span(p) else "permanent";

        // Decrypt content
        var dec_buf: [256 * 1024]u8 = undefined;
        const dec_len = transit_eng.decryptForUser(auth_user_id, enc_blob, "", &dec_buf) catch continue;
        const content = dec_buf[0..dec_len];

        // Escape all strings
        var esc_id: [128]u8 = undefined;
        var esc_title: [512]u8 = undefined;
        var esc_content: [128 * 1024]u8 = undefined;
        var esc_ctype: [64]u8 = undefined;
        var esc_vis: [64]u8 = undefined;
        var esc_cat: [128]u8 = undefined;
        var esc_ctx: [64]u8 = undefined;
        var esc_fresh: [64]u8 = undefined;
        const eid = json_mod.escapeJsonString(id_s, &esc_id) catch continue;
        const etitle = json_mod.escapeJsonString(title_s, &esc_title) catch continue;
        const econtent = json_mod.escapeJsonString(content, &esc_content) catch continue;
        const ectype = json_mod.escapeJsonString(ctype_s, &esc_ctype) catch continue;
        const evis = json_mod.escapeJsonString(vis_s, &esc_vis) catch continue;
        const ecat = json_mod.escapeJsonString(cat_s, &esc_cat) catch continue;
        const ectx = json_mod.escapeJsonString(context_s, &esc_ctx) catch continue;
        const efresh = json_mod.escapeJsonString(freshness_s, &esc_fresh) catch continue;

        const expires_json = if (expires_s.len > 0)
            std.fmt.allocPrint(ctx.allocator, "\"{s}\"", .{expires_s}) catch "null"
        else
            @as([]const u8, "null");

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"owner_id\":\"{s}\",\"title\":\"{s}\",\"content\":\"{s}\"," ++
                "\"capsule_type\":\"{s}\",\"visibility\":\"{s}\",\"category\":\"{s}\"," ++
                "\"is_archived\":{s},\"emergency_accessible\":{s},\"can_reshare\":{s}," ++
                "\"context\":\"{s}\",\"freshness\":\"{s}\",\"expires_at\":{s}," ++
                "\"created_at\":\"{s}\",\"updated_at\":\"{s}\"}}",
            .{
                esc_id[0..eid], auth_user_id, esc_title[0..etitle], esc_content[0..econtent],
                esc_ctype[0..ectype], esc_vis[0..evis], esc_cat[0..ecat],
                if (is_archived) "true" else "false",
                if (emerg) "true" else "false",
                if (reshare) "true" else "false",
                esc_ctx[0..ectx], esc_fresh[0..efresh], expires_json,
                created_s, updated_s,
            },
        ) catch continue;
        try result.appendSlice(ctx.allocator, entry);
    }

    try result.appendSlice(ctx.allocator, "]");
    try ctx.json(.ok, result.items);
}

// ═══════════════════════════════════════════
//  POST /api/users/{id}/capsules
// ═══════════════════════════════════════════

const CreateRequest = struct {
    title: ?[]const u8 = null,
    content: ?[]const u8 = null,
    capsule_type: ?[]const u8 = null,
    visibility: ?[]const u8 = null,
    category: ?[]const u8 = null,
    context: ?[]const u8 = null,
    emergency_accessible: ?bool = null,
    can_reshare: ?bool = null,
    freshness: ?[]const u8 = null,
};

fn handleCreateCapsule(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract user_id from path
    const path_prefix = "/api/users/";
    const path_rest = ctx.path[path_prefix.len..];
    const path_slash = std.mem.indexOfScalar(u8, path_rest, '/') orelse
        return ctx.sendError(.bad_request, "Invalid path");
    const path_user_id = path_rest[0..path_slash];

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    if (ctx.body.len > 50 * 1024) return ctx.sendError(.payload_too_large, "Body too large");

    const parsed = json_mod.parse(CreateRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const title = req.title orelse return ctx.sendError(.bad_request, "title required");
    const content = req.content orelse return ctx.sendError(.bad_request, "content required");
    const capsule_type = req.capsule_type orelse "note";
    const visibility = req.visibility orelse "private";
    const category = req.category orelse "";
    const context_val = req.context orelse "personal";
    const freshness = req.freshness orelse "permanent";
    const emerg = req.emergency_accessible orelse false;
    const reshare = req.can_reshare orelse false;

    // Generate capsule ID
    var capsule_id_buf: [36]u8 = undefined;
    common.generateUuid(&capsule_id_buf);
    const capsule_id = capsule_id_buf[0..36];

    // Encrypt content
    var enc_buf: [256 * 1024]u8 = undefined;
    const enc_len = transit_eng.encryptForUser(auth_user_id, content, "", &enc_buf) catch
        return ctx.sendError(.internal_server_error, "Encryption failed");

    // Content hash
    var hash_hex: [64]u8 = undefined;
    common.sha256Hex(content, &hash_hex);

    // Timestamp
    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // INSERT
    {
        var stmt = database.prepare(
            "INSERT INTO knowledge_capsules " ++
                "(id, owner_id, capsule_type, title, content_encrypted, content_hash, " ++
                "visibility, emergency_accessible, can_reshare, category, " ++
                "embedding_collection, context, freshness, last_verified_at, " ++
                "is_archived, authority_weight, created_at, updated_at) " ++
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'default', ?, ?, ?, 0, 1.0, ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, capsule_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, auth_user_id.ptr, @intCast(auth_user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, capsule_type.ptr, @intCast(capsule_type.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, title.ptr, @intCast(title.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindBlob(5, &enc_buf, @intCast(enc_len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(6, &hash_hex, 64) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(7, visibility.ptr, @intCast(visibility.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindInt(8, if (emerg) 1 else 0) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindInt(9, if (reshare) 1 else 0) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(10, category.ptr, @intCast(category.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(11, context_val.ptr, @intCast(context_val.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(12, freshness.ptr, @intCast(freshness.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(13, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(14, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(15, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Insert failed");
    }

    // FTS5 index
    podos.fts.upsertCapsule(
        database,
        capsule_id.ptr, 36,
        title.ptr, @intCast(title.len),
        content.ptr, @intCast(content.len),
        category.ptr, @intCast(category.len),
    ) catch {};

    var esc_id: [128]u8 = undefined;
    const eid_len = json_mod.escapeJsonString(capsule_id, &esc_id) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"id\":\"{s}\",\"owner_id\":\"{s}\",\"title\":\"{s}\",\"capsule_type\":\"{s}\",\"visibility\":\"{s}\",\"category\":\"{s}\",\"created_at\":\"{s}\"}}",
        .{ esc_id[0..eid_len], auth_user_id, title, capsule_type, visibility, category, ts },
    );
    try ctx.json(.created, body);
}

// ═══════════════════════════════════════════
//  PUT /api/capsules/{id}
// ═══════════════════════════════════════════

const UpdateRequest = struct {
    title: ?[]const u8 = null,
    content: ?[]const u8 = null,
    visibility: ?[]const u8 = null,
    category: ?[]const u8 = null,
    is_archived: ?bool = null,
};

fn handleUpdateCapsule(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    const cap_id = common.extractPathParam(ctx.path, "/api/capsules/") orelse
        return ctx.sendError(.bad_request, "Missing capsule ID");

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    if (ctx.body.len > 50 * 1024) return ctx.sendError(.payload_too_large, "Body too large");

    // Verify ownership
    {
        var stmt = database.prepare(
            "SELECT owner_id FROM knowledge_capsules WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, cap_id.ptr, @intCast(cap_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Capsule not found");
        }
        const owner_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "DB error");
        if (!std.mem.eql(u8, std.mem.span(owner_ptr), auth_user_id)) {
            return ctx.sendError(.forbidden, "Access denied");
        }
    }

    const parsed = json_mod.parse(UpdateRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    // Timestamp
    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // Update fields that were provided
    if (req.content) |content| {
        var enc_buf: [256 * 1024]u8 = undefined;
        const enc_len = transit_eng.encryptForUser(auth_user_id, content, "", &enc_buf) catch
            return ctx.sendError(.internal_server_error, "Encryption failed");
        var hash_hex: [64]u8 = undefined;
        common.sha256Hex(content, &hash_hex);
        var stmt = database.prepare(
            "UPDATE knowledge_capsules SET content_encrypted = ?, content_hash = ?, updated_at = ? WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindBlob(1, &enc_buf, @intCast(enc_len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, &hash_hex, 64) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");

        // Update FTS5
        const title_for_fts = req.title orelse ""; // FTS needs title too
        podos.fts.upsertCapsule(
            database,
            cap_id.ptr, @intCast(cap_id.len),
            title_for_fts.ptr, @intCast(title_for_fts.len),
            content.ptr, @intCast(content.len),
            if (req.category) |c| c.ptr else "", @intCast(if (req.category) |c| c.len else 0),
        ) catch {};
    }
    if (req.title) |new_title| {
        var stmt = database.prepare(
            "UPDATE knowledge_capsules SET title = ?, updated_at = ? WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, new_title.ptr, @intCast(new_title.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }
    if (req.visibility) |vis| {
        var stmt = database.prepare(
            "UPDATE knowledge_capsules SET visibility = ?, updated_at = ? WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, vis.ptr, @intCast(vis.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }
    if (req.category) |cat| {
        var stmt = database.prepare(
            "UPDATE knowledge_capsules SET category = ?, updated_at = ? WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, cat.ptr, @intCast(cat.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }
    if (req.is_archived) |archived| {
        var stmt = database.prepare(
            "UPDATE knowledge_capsules SET is_archived = ?, updated_at = ? WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindInt(1, if (archived) 1 else 0) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Update failed");
    }

    try ctx.json(.ok, "{\"ok\":true}");
}

// ═══════════════════════════════════════════
//  DELETE /api/capsules/{id}
// ═══════════════════════════════════════════

fn handleDeleteCapsule(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    const cap_id = common.extractPathParam(ctx.path, "/api/capsules/") orelse
        return ctx.sendError(.bad_request, "Missing capsule ID");

    // Verify ownership
    {
        var stmt = database.prepare(
            "SELECT owner_id FROM knowledge_capsules WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, cap_id.ptr, @intCast(cap_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Capsule not found");
        }
        const owner_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "DB error");
        if (!std.mem.eql(u8, std.mem.span(owner_ptr), auth_user_id)) {
            return ctx.sendError(.forbidden, "Access denied");
        }
    }

    // Soft delete: set is_archived = 1
    {
        var stmt = database.prepare(
            "UPDATE knowledge_capsules SET is_archived = 1 WHERE id = ?",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, cap_id.ptr, @intCast(cap_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Delete failed");
    }

    // Remove from FTS5 index
    podos.fts.deleteCapsule(database, cap_id.ptr, @intCast(cap_id.len)) catch {};

    try ctx.json(.ok, "{\"status\":\"archived\"}");
}
