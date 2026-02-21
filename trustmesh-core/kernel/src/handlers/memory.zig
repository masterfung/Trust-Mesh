// handlers/memory.zig — Native Zig HTTP handlers for the Memory API.
//
// Zero-Python data path: HTTP → auth → transit encrypt → SQLite → FTS5.
// Used by ZeroClaw/NullClaw agent runtimes as a Memory trait backend.
//
// Routes:
//   POST   /api/memory/store       → handleStore
//   POST   /api/memory/recall      → handleRecall
//   GET    /api/memory/list        → handleList
//   GET    /api/memory/count       → handleCount
//   GET    /api/memory/health      → handleHealth
//   DELETE /api/memory/            → handleDelete (prefix)
//   GET    /api/memory/            → handleGet (prefix, single capsule by ID)

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router_mod = @import("../router.zig");
const json_mod = podos.json;

const Sha256 = std.crypto.hash.sha2.Sha256;

// ── Module-level state ──
var _db: ?*podos.db.Database = null;
var _session_store: ?*podos.session.SessionStore = null;
var _transit_engine: ?*podos.transit.TransitEngine = null;
var _rate_limiter: ?*podos.rate_limit.RateLimiter = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

pub fn setTransitEngine(engine: *podos.transit.TransitEngine) void {
    _transit_engine = engine;
}

pub fn setRateLimiter(rl: *podos.rate_limit.RateLimiter) void {
    _rate_limiter = rl;
}

pub fn registerRoutes() void {
    router_mod.addExact(.POST, "/api/memory/store", handleStore);
    router_mod.addExact(.POST, "/api/memory/recall", handleRecall);
    router_mod.addExact(.GET, "/api/memory/list", handleList);
    router_mod.addExact(.GET, "/api/memory/count", handleCount);
    router_mod.addExact(.GET, "/api/memory/health", handleHealth);
    // Prefix routes for /api/memory/{id}
    router_mod.addPrefix(.DELETE, "/api/memory/", handleDelete);
    router_mod.addPrefix(.GET, "/api/memory/", handleGetOne);
}

// ── Constants ──
const MAX_STORE_BODY: usize = 50 * 1024; // 50KB
const MAX_RECALL_BODY: usize = 4 * 1024; // 4KB
const MAX_CAPSULES_PER_USER: usize = 10_000;

// ── Auth helper ──
fn requireAuth(ctx: *http.RequestContext, out: []u8) ?[]const u8 {
    const token = ctx.getCookie("trustmesh_session") orelse {
        ctx.sendError(.unauthorized, "Not authenticated") catch {};
        return null;
    };
    const store = _session_store orelse {
        ctx.sendError(.service_unavailable, "Session store not ready") catch {};
        return null;
    };
    var fp_buf: [64]u8 = undefined;
    const fp = buildFingerprint(ctx, &fp_buf);
    // validateSession returns ?[]const u8 (pointer into session internal buffer)
    const uid = store.validateSession(token, fp) orelse {
        ctx.sendError(.unauthorized, "Invalid session") catch {};
        return null;
    };
    if (uid.len > out.len) {
        ctx.sendError(.internal_server_error, "User ID too long") catch {};
        return null;
    }
    @memcpy(out[0..uid.len], uid);
    return out[0..uid.len];
}

fn buildFingerprint(ctx: *const http.RequestContext, buf: *[64]u8) []const u8 {
    const ua = ctx.getHeader("user-agent") orelse "";
    const ip = http.getClientIp(ctx);
    var h = Sha256.init(.{});
    h.update(ua);
    h.update("|");
    h.update(ip);
    const digest = h.finalResult();
    const hex_chars = "0123456789abcdef";
    for (digest, 0..) |byte, i| {
        buf[i * 2] = hex_chars[byte >> 4];
        buf[i * 2 + 1] = hex_chars[byte & 0x0f];
    }
    return buf[0..64];
}

// ── UUID generation ──
fn generateUuid(buf: *[36]u8) void {
    var raw: [16]u8 = undefined;
    std.crypto.random.bytes(&raw);
    raw[6] = (raw[6] & 0x0f) | 0x40;
    raw[8] = (raw[8] & 0x3f) | 0x80;
    const hex = "0123456789abcdef";
    var pos: usize = 0;
    const groups = [_]usize{ 4, 2, 2, 2, 6 };
    var byte_idx: usize = 0;
    for (groups, 0..) |count, g| {
        if (g > 0) {
            buf[pos] = '-';
            pos += 1;
        }
        for (0..count) |_| {
            buf[pos] = hex[raw[byte_idx] >> 4];
            buf[pos + 1] = hex[raw[byte_idx] & 0x0f];
            pos += 2;
            byte_idx += 1;
        }
    }
}

// ═══════════════════════════════════════════
//  HANDLER: POST /api/memory/store
// ═══════════════════════════════════════════

const StoreRequest = struct {
    content: ?[]const u8 = null,
    title: ?[]const u8 = null,
    category: ?[]const u8 = null,
    visibility: ?[]const u8 = null,
};

fn handleStore(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [128]u8 = undefined;
    const user_id = requireAuth(ctx, &uid_buf) orelse return;

    // Body size limit
    if (ctx.body.len > MAX_STORE_BODY) return ctx.sendError(.payload_too_large, "Body too large (50KB max)");
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    // Rate limit
    if (_rate_limiter) |rl| {
        const check = rl.checkMemoryStore(user_id);
        if (!check.allowed) return ctx.sendError(.too_many_requests, check.getMessage());
    }

    // Parse
    const parsed = json_mod.parse(StoreRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const content = req.content orelse return ctx.sendError(.bad_request, "content required");
    const title = req.title orelse "Untitled";
    const category = req.category orelse "general";
    const visibility = req.visibility orelse "private";

    // Per-user capsule cap
    {
        var stmt = database.prepare("SELECT COUNT(*) FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0") catch
            return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, user_id.ptr, @intCast(user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        if (stmt.step() catch false) {
            if (stmt.getInt(0) >= @as(c_int, MAX_CAPSULES_PER_USER)) {
                return ctx.sendError(.conflict, "Capsule limit reached (10,000)");
            }
        }
    }

    // Generate capsule ID
    var capsule_id_buf: [36]u8 = undefined;
    generateUuid(&capsule_id_buf);
    const capsule_id = capsule_id_buf[0..36];

    // Encrypt content (no AAD — matches Python crypto_bridge.encrypt for compat)
    var enc_buf: [256 * 1024]u8 = undefined; // 256KB buffer for encrypted content
    const enc_len = transit_eng.encryptForUser(user_id, content, "", &enc_buf) catch
        return ctx.sendError(.internal_server_error, "Encryption failed");

    // ISO timestamp
    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // Content hash (SHA-256 hex)
    var hash_digest: [32]u8 = undefined;
    Sha256.hash(content, &hash_digest, .{});
    var hash_hex: [64]u8 = undefined;
    const hex_chars2 = "0123456789abcdef";
    for (hash_digest, 0..) |byte, i| {
        hash_hex[i * 2] = hex_chars2[byte >> 4];
        hash_hex[i * 2 + 1] = hex_chars2[byte & 0x0f];
    }

    // INSERT capsule (all NOT NULL columns filled with defaults for Memory API)
    {
        var stmt = database.prepare(
            "INSERT INTO knowledge_capsules " ++
                "(id, owner_id, capsule_type, title, content_encrypted, content_hash, " ++
                "visibility, emergency_accessible, can_reshare, category, " ++
                "embedding_collection, context, freshness, last_verified_at, " ++
                "is_archived, authority_weight, created_at, updated_at) " ++
                "VALUES (?, ?, 'note', ?, ?, ?, ?, 0, 0, ?, 'default', 'personal', 'current', ?, 0, 1.0, ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, capsule_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, user_id.ptr, @intCast(user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, title.ptr, @intCast(title.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindBlob(4, &enc_buf, @intCast(enc_len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(5, &hash_hex, 64) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(6, visibility.ptr, @intCast(visibility.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(7, category.ptr, @intCast(category.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(8, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(9, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(10, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Capsule insert failed");
    }

    // Index in FTS5
    podos.fts.upsertCapsule(
        database,
        capsule_id.ptr, 36,
        title.ptr, @intCast(title.len),
        content.ptr, @intCast(content.len),
        category.ptr, @intCast(category.len),
    ) catch {}; // Non-fatal: search index will be stale but data is safe

    // Record rate limit
    if (_rate_limiter) |rl| {
        rl.recordMemoryStore(user_id) catch {};
    }

    var esc_id: [128]u8 = undefined;
    const eid_len = json_mod.escapeJsonString(capsule_id, &esc_id) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const body = try std.fmt.allocPrint(ctx.allocator, "{{\"id\":\"{s}\",\"status\":\"stored\"}}", .{esc_id[0..eid_len]});
    try ctx.json(.created, body);
}

// ═══════════════════════════════════════════
//  HANDLER: POST /api/memory/recall
// ═══════════════════════════════════════════

const RecallRequest = struct {
    query: ?[]const u8 = null,
    top_k: ?u32 = null,
    category: ?[]const u8 = null,
};

fn handleRecall(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [128]u8 = undefined;
    const user_id = requireAuth(ctx, &uid_buf) orelse return;

    if (ctx.body.len > MAX_RECALL_BODY) return ctx.sendError(.payload_too_large, "Body too large (4KB max)");
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");

    // Rate limit
    if (_rate_limiter) |rl| {
        const check = rl.checkMemoryRecall(user_id);
        if (!check.allowed) return ctx.sendError(.too_many_requests, check.getMessage());
    }

    const parsed = json_mod.parse(RecallRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const query = req.query orelse return ctx.sendError(.bad_request, "query required");
    const top_k = req.top_k orelse 10;

    // Get accessible capsule IDs (own capsules only for memory API)
    var ids_buf: [64 * 1024]u8 = undefined;
    const ids_len = buildAccessibleIds(database, user_id, req.category, &ids_buf) catch
        return ctx.sendError(.internal_server_error, "DB error");

    if (ids_len == 0 or std.mem.eql(u8, ids_buf[0..ids_len], "[]")) {
        try ctx.json(.ok, "{\"results\":[]}");
        return;
    }

    // FTS5 search
    var fts_buf: [128 * 1024]u8 = undefined;
    const fts_len = podos.fts.searchCapsules(
        database,
        query.ptr, @intCast(query.len),
        &ids_buf, @intCast(ids_len),
        top_k,
        &fts_buf, fts_buf.len,
    ) catch {
        // FTS5 errors (e.g., bad query syntax) -> return empty
        try ctx.json(.ok, "{\"results\":[]}");
        return;
    };

    // Decode FTS results and decrypt content
    // fts_buf contains: [{"id":"...","rank":-1.2}, ...]
    // We need to look up each capsule, decrypt, and return content
    var result_json = std.ArrayList(u8){};
    try result_json.appendSlice(ctx.allocator,"{\"results\":[");

    // Parse FTS result IDs and fetch+decrypt each
    var first = true;
    var fts_pos: usize = 0;
    const fts_data = fts_buf[0..fts_len];
    while (fts_pos < fts_data.len) {
        // Find next "id":"
        const id_start_marker = "\"id\":\"";
        const id_start_idx = std.mem.indexOf(u8, fts_data[fts_pos..], id_start_marker) orelse break;
        const abs_start = fts_pos + id_start_idx + id_start_marker.len;
        const id_end_idx = std.mem.indexOfScalar(u8, fts_data[abs_start..], '"') orelse break;
        const cap_id = fts_data[abs_start..][0..id_end_idx];

        // Find rank
        const rank_marker = "\"rank\":";
        var rank_str: []const u8 = "0";
        if (std.mem.indexOf(u8, fts_data[abs_start..], rank_marker)) |ri| {
            const rank_start = abs_start + ri + rank_marker.len;
            const rank_end = std.mem.indexOfAny(u8, fts_data[rank_start..], ",}") orelse (fts_data.len - rank_start);
            rank_str = fts_data[rank_start..][0..rank_end];
        }

        fts_pos = abs_start + id_end_idx + 1;

        // Fetch capsule from DB
        var cap_stmt = database.prepare(
            "SELECT title, content_encrypted, category, visibility FROM knowledge_capsules WHERE id = ? AND owner_id = ? AND is_archived = 0",
        ) catch continue;
        defer cap_stmt.finalize();
        cap_stmt.bindText(1, cap_id.ptr, @intCast(cap_id.len)) catch continue;
        cap_stmt.bindText(2, user_id.ptr, @intCast(user_id.len)) catch continue;

        if (cap_stmt.step() catch false) {
            const title_ptr = cap_stmt.getText(0) orelse continue;
            const title_s = std.mem.span(title_ptr);
            const enc_blob = cap_stmt.getBlob(1) orelse continue;
            const cat_ptr = cap_stmt.getText(2) orelse continue;
            const cat_s = std.mem.span(cat_ptr);

            // Decrypt content (empty AAD — matches Python crypto_bridge for compat)
            var dec_buf: [256 * 1024]u8 = undefined;
            const dec_len = transit_eng.decryptForUser(user_id, enc_blob, "", &dec_buf) catch continue;
            const content = dec_buf[0..dec_len];

            if (!first) try result_json.appendSlice(ctx.allocator,",");
            first = false;

            // Escape all strings for JSON safety
            var esc_title: [512]u8 = undefined;
            var esc_content: [128 * 1024]u8 = undefined;
            var esc_cat: [128]u8 = undefined;
            var esc_cid: [128]u8 = undefined;
            const et_len = json_mod.escapeJsonString(title_s, &esc_title) catch continue;
            const ec_len = json_mod.escapeJsonString(content, &esc_content) catch continue;
            const ecat_len = json_mod.escapeJsonString(cat_s, &esc_cat) catch continue;
            const ecid_len = json_mod.escapeJsonString(cap_id, &esc_cid) catch continue;

            const entry = std.fmt.allocPrint(ctx.allocator,
                "{{\"id\":\"{s}\",\"title\":\"{s}\",\"content\":\"{s}\",\"category\":\"{s}\",\"rank\":{s}}}",
                .{
                    esc_cid[0..ecid_len],
                    esc_title[0..et_len],
                    esc_content[0..ec_len],
                    esc_cat[0..ecat_len],
                    rank_str,
                },
            ) catch continue;
            try result_json.appendSlice(ctx.allocator,entry);
        }
    }

    try result_json.appendSlice(ctx.allocator,"]}");

    // Record rate limit
    if (_rate_limiter) |rl| {
        rl.recordMemoryRecall(user_id) catch {};
    }

    try ctx.json(.ok, result_json.items);
}

// ═══════════════════════════════════════════
//  HANDLER: GET /api/memory/list
// ═══════════════════════════════════════════

fn handleList(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [128]u8 = undefined;
    const user_id = requireAuth(ctx, &uid_buf) orelse return;

    // Parse query params for category filter
    const category_filter = getQueryParam(ctx.query, "category");
    const limit_str = getQueryParam(ctx.query, "limit");
    const limit_val: u32 = if (limit_str) |ls| std.fmt.parseInt(u32, ls, 10) catch 50 else 50;
    const effective_limit = @min(limit_val, 100);

    var result_json = std.ArrayList(u8){};
    try result_json.appendSlice(ctx.allocator,"{\"capsules\":[");

    // Query capsules
    const sql = if (category_filter != null)
        "SELECT id, title, content_encrypted, category, visibility, created_at FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0 AND category = ? ORDER BY created_at DESC LIMIT ?"
    else
        "SELECT id, title, content_encrypted, category, visibility, created_at FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0 ORDER BY created_at DESC LIMIT ?";

    var stmt = database.prepare(@ptrCast(sql)) catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();

    stmt.bindText(1, user_id.ptr, @intCast(user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
    if (category_filter) |cat| {
        stmt.bindText(2, cat.ptr, @intCast(cat.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindInt(3, @intCast(effective_limit)) catch return ctx.sendError(.internal_server_error, "DB error");
    } else {
        stmt.bindInt(2, @intCast(effective_limit)) catch return ctx.sendError(.internal_server_error, "DB error");
    }

    var first = true;
    while (stmt.step() catch false) {
        const id_ptr = stmt.getText(0) orelse continue;
        const cap_id = std.mem.span(id_ptr);
        const title_ptr = stmt.getText(1) orelse continue;
        const title_s = std.mem.span(title_ptr);
        const enc_blob = stmt.getBlob(2) orelse continue;
        const cat_ptr = stmt.getText(3) orelse continue;
        const cat_s = std.mem.span(cat_ptr);
        const vis_ptr = stmt.getText(4) orelse continue;
        const vis_s = std.mem.span(vis_ptr);

        // Decrypt (empty AAD — matches Python crypto_bridge for compat)
        var dec_buf: [256 * 1024]u8 = undefined;
        const dec_len = transit_eng.decryptForUser(user_id, enc_blob, "", &dec_buf) catch continue;
        const content = dec_buf[0..dec_len];

        if (!first) try result_json.appendSlice(ctx.allocator,",");
        first = false;

        var esc_id: [128]u8 = undefined;
        var esc_title: [512]u8 = undefined;
        var esc_content: [128 * 1024]u8 = undefined;
        var esc_cat: [128]u8 = undefined;
        var esc_vis: [64]u8 = undefined;
        const eid = json_mod.escapeJsonString(cap_id, &esc_id) catch continue;
        const etit = json_mod.escapeJsonString(title_s, &esc_title) catch continue;
        const ecnt = json_mod.escapeJsonString(content, &esc_content) catch continue;
        const ecat = json_mod.escapeJsonString(cat_s, &esc_cat) catch continue;
        const evis = json_mod.escapeJsonString(vis_s, &esc_vis) catch continue;

        const entry = std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"title\":\"{s}\",\"content\":\"{s}\",\"category\":\"{s}\",\"visibility\":\"{s}\"}}",
            .{
                esc_id[0..eid],
                esc_title[0..etit],
                esc_content[0..ecnt],
                esc_cat[0..ecat],
                esc_vis[0..evis],
            },
        ) catch continue;
        try result_json.appendSlice(ctx.allocator,entry);
    }

    try result_json.appendSlice(ctx.allocator,"]}");
    try ctx.json(.ok, result_json.items);
}

// ═══════════════════════════════════════════
//  HANDLER: GET /api/memory/{id}
// ═══════════════════════════════════════════

fn handleGetOne(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");

    var uid_buf: [128]u8 = undefined;
    const user_id = requireAuth(ctx, &uid_buf) orelse return;

    // Extract capsule ID from path: /api/memory/{id}
    const prefix = "/api/memory/";
    if (!std.mem.startsWith(u8, ctx.path, prefix) or ctx.path.len <= prefix.len) {
        return ctx.sendError(.bad_request, "Missing capsule ID");
    }
    const cap_id = ctx.path[prefix.len..];
    if (cap_id.len == 0 or cap_id.len > 36) return ctx.sendError(.bad_request, "Invalid capsule ID");

    var stmt = database.prepare(
        "SELECT title, content_encrypted, category, visibility, created_at FROM knowledge_capsules WHERE id = ? AND owner_id = ? AND is_archived = 0",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(2, user_id.ptr, @intCast(user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");

    if (!(stmt.step() catch false)) {
        return ctx.sendError(.not_found, "Capsule not found");
    }

    const title_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "DB error");
    const title_s = std.mem.span(title_ptr);
    const enc_blob = stmt.getBlob(1) orelse return ctx.sendError(.internal_server_error, "DB error");
    const cat_ptr = stmt.getText(2) orelse return ctx.sendError(.internal_server_error, "DB error");
    const cat_s = std.mem.span(cat_ptr);
    const vis_ptr = stmt.getText(3) orelse return ctx.sendError(.internal_server_error, "DB error");
    const vis_s = std.mem.span(vis_ptr);

    // Decrypt (empty AAD — matches Python crypto_bridge for compat)
    var dec_buf: [256 * 1024]u8 = undefined;
    const dec_len = transit_eng.decryptForUser(user_id, enc_blob, "", &dec_buf) catch
        return ctx.sendError(.internal_server_error, "Decryption failed");
    const content = dec_buf[0..dec_len];

    var esc_id: [128]u8 = undefined;
    var esc_title: [512]u8 = undefined;
    var esc_content: [128 * 1024]u8 = undefined;
    var esc_cat: [128]u8 = undefined;
    var esc_vis: [64]u8 = undefined;
    const eid = json_mod.escapeJsonString(cap_id, &esc_id) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const etit = json_mod.escapeJsonString(title_s, &esc_title) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const ecnt = json_mod.escapeJsonString(content, &esc_content) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const ecat = json_mod.escapeJsonString(cat_s, &esc_cat) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const evis = json_mod.escapeJsonString(vis_s, &esc_vis) catch return ctx.sendError(.internal_server_error, "Serialize failed");

    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"id\":\"{s}\",\"title\":\"{s}\",\"content\":\"{s}\",\"category\":\"{s}\",\"visibility\":\"{s}\"}}",
        .{
            esc_id[0..eid],
            esc_title[0..etit],
            esc_content[0..ecnt],
            esc_cat[0..ecat],
            esc_vis[0..evis],
        },
    );
    try ctx.json(.ok, body);
}

// ═══════════════════════════════════════════
//  HANDLER: DELETE /api/memory/{id} (soft-delete / archive)
// ═══════════════════════════════════════════

fn handleDelete(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const user_id = requireAuth(ctx, &uid_buf) orelse return;

    const prefix = "/api/memory/";
    if (!std.mem.startsWith(u8, ctx.path, prefix) or ctx.path.len <= prefix.len) {
        return ctx.sendError(.bad_request, "Missing capsule ID");
    }
    const cap_id = ctx.path[prefix.len..];

    // Soft-delete: set is_archived = 1
    var stmt = database.prepare("UPDATE knowledge_capsules SET is_archived = 1 WHERE id = ? AND owner_id = ?") catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, cap_id.ptr, @intCast(cap_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
    stmt.bindText(2, user_id.ptr, @intCast(user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");
    _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Archive failed");

    // Remove from FTS5 index
    podos.fts.deleteCapsule(database, cap_id.ptr, @intCast(cap_id.len)) catch {};

    try ctx.json(.ok, "{\"status\":\"archived\"}");
}

// ═══════════════════════════════════════════
//  HANDLER: GET /api/memory/count
// ═══════════════════════════════════════════

fn handleCount(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    var uid_buf: [128]u8 = undefined;
    const user_id = requireAuth(ctx, &uid_buf) orelse return;

    var stmt = database.prepare("SELECT COUNT(*) FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0") catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, user_id.ptr, @intCast(user_id.len)) catch return ctx.sendError(.internal_server_error, "DB error");

    var count: c_int = 0;
    if (stmt.step() catch false) {
        count = stmt.getInt(0);
    }

    const body = try std.fmt.allocPrint(ctx.allocator, "{{\"count\":{d}}}", .{count});
    try ctx.json(.ok, body);
}

// ═══════════════════════════════════════════
//  HANDLER: GET /api/memory/health
// ═══════════════════════════════════════════

fn handleHealth(ctx: *http.RequestContext) !void {
    const db_ok = _db != null;
    const transit_ok = _transit_engine != null;
    const session_ok = _session_store != null;

    const healthy = db_ok and transit_ok and session_ok;
    const status_str = if (healthy) "healthy" else "degraded";

    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"status\":\"{s}\",\"db\":{s},\"transit\":{s},\"session\":{s}}}",
        .{
            status_str,
            if (db_ok) "true" else "false",
            if (transit_ok) "true" else "false",
            if (session_ok) "true" else "false",
        },
    );
    try ctx.json(.ok, body);
}

// ═══════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════

/// Build JSON array of accessible capsule IDs for a user (own capsules only).
fn buildAccessibleIds(database: *podos.db.Database, user_id: []const u8, category: ?[]const u8, out: []u8) !usize {
    const sql = if (category != null)
        "SELECT id FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0 AND category = ?"
    else
        "SELECT id FROM knowledge_capsules WHERE owner_id = ? AND is_archived = 0";

    var stmt = try database.prepare(@ptrCast(sql));
    defer stmt.finalize();
    try stmt.bindText(1, user_id.ptr, @intCast(user_id.len));
    if (category) |cat| {
        try stmt.bindText(2, cat.ptr, @intCast(cat.len));
    }

    var pos: usize = 0;
    if (pos >= out.len) return error.BufferTooSmall;
    out[pos] = '[';
    pos += 1;
    var count: usize = 0;

    while (try stmt.step()) {
        const id_ptr = stmt.getText(0) orelse continue;
        const id_s = std.mem.span(id_ptr);
        if (count > 0) {
            if (pos >= out.len) break;
            out[pos] = ',';
            pos += 1;
        }
        if (pos + id_s.len + 2 >= out.len) break;
        out[pos] = '"';
        pos += 1;
        @memcpy(out[pos..][0..id_s.len], id_s);
        pos += id_s.len;
        out[pos] = '"';
        pos += 1;
        count += 1;
    }

    if (pos >= out.len) return error.BufferTooSmall;
    out[pos] = ']';
    pos += 1;
    return pos;
}

/// Extract a query parameter value from a URL query string.
fn getQueryParam(query: []const u8, name: []const u8) ?[]const u8 {
    if (query.len == 0) return null;
    var it = std.mem.splitScalar(u8, query, '&');
    while (it.next()) |pair| {
        const eq = std.mem.indexOfScalar(u8, pair, '=') orelse continue;
        const key = pair[0..eq];
        if (std.mem.eql(u8, key, name)) {
            return pair[eq + 1 ..];
        }
    }
    return null;
}

fn formatIsoTimestamp(epoch_secs: i64, buf: *[32]u8) usize {
    const epoch = std.time.epoch.EpochSeconds{ .secs = @intCast(epoch_secs) };
    const day = epoch.getDaySeconds();
    const yd = epoch.getEpochDay().calculateYearDay();
    const md = yd.calculateMonthDay();
    const y = yd.year;
    const m = md.month.numeric();
    const d = md.day_index + 1;
    const h = day.getHoursIntoDay();
    const min = day.getMinutesIntoHour();
    const s = day.getSecondsIntoMinute();

    return (std.fmt.bufPrint(buf, "{d:0>4}-{d:0>2}-{d:0>2}T{d:0>2}:{d:0>2}:{d:0>2}", .{
        y, m, d, h, min, s,
    }) catch return 0).len;
}
