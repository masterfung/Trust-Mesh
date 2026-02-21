// handlers/onboard.zig — Native Zig handler for pod onboarding.
//
// POST /api/onboard/init — Create first user + agent + vault key.
// Used by `trustmesh init` and claw agent runtimes to bootstrap a pod.

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router_mod = @import("../router.zig");
const json_mod = podos.json;

// ── Module-level state set from server_main.zig ──
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
    router_mod.addExact(.POST, "/api/onboard/init", handleInit);
    router_mod.addExact(.GET, "/api/onboard/status", handleStatus);
}

// ── Constants ──
const MAX_LOCAL_USERS: usize = 50;
const MIN_PASSWORD_LEN: usize = 12;

const InitRequest = struct {
    username: ?[]const u8 = null,
    password: ?[]const u8 = null,
    display_name: ?[]const u8 = null,
    user_type: ?[]const u8 = null,
};

// ── Password validation ──
fn validatePassword(pw: []const u8) bool {
    if (pw.len < MIN_PASSWORD_LEN) return false;
    var has_upper = false;
    var has_lower = false;
    var has_digit = false;
    for (pw) |ch| {
        if (ch >= 'A' and ch <= 'Z') has_upper = true;
        if (ch >= 'a' and ch <= 'z') has_lower = true;
        if (ch >= '0' and ch <= '9') has_digit = true;
    }
    return has_upper and has_lower and has_digit;
}

// ── UUID generation ──
fn generateUuid(buf: *[36]u8) void {
    var raw: [16]u8 = undefined;
    std.crypto.random.bytes(&raw);
    // Set version 4 and variant
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

// ── HANDLER: POST /api/onboard/init ──
fn handleInit(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit_eng = _transit_engine orelse return ctx.sendError(.service_unavailable, "Transit not ready");
    const sess_store = _session_store orelse return ctx.sendError(.service_unavailable, "Session store not ready");

    // Localhost-only guard (unless dev mode)
    if (!http.isDevMode()) {
        const ip = http.getClientIp(ctx);
        if (!std.mem.eql(u8, ip, "127.0.0.1") and !std.mem.eql(u8, ip, "unknown")) {
            return ctx.sendError(.forbidden, "Onboarding only allowed from localhost");
        }
    }

    // Parse body
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    const parsed = json_mod.parse(InitRequest, ctx.allocator, ctx.body) catch
        return ctx.sendError(.bad_request, "Invalid JSON");
    defer parsed.deinit();
    const req = parsed.value;

    const username = req.username orelse return ctx.sendError(.bad_request, "username required");
    const password = req.password orelse return ctx.sendError(.bad_request, "password required");
    const display_name = req.display_name orelse username;
    const user_type = req.user_type orelse "person";

    // Validate
    if (username.len < 2 or username.len > 50) return ctx.sendError(.bad_request, "Username must be 2-50 chars");
    if (!validatePassword(password)) return ctx.sendError(.bad_request, "Password must be 12+ chars with upper, lower, and digit");

    // Check per-pod user cap
    {
        var count_stmt = database.prepare("SELECT COUNT(*) FROM users WHERE is_remote = 0") catch
            return ctx.sendError(.internal_server_error, "DB error");
        defer count_stmt.finalize();
        if (count_stmt.step() catch false) {
            const count = count_stmt.getInt(0);
            if (count >= @as(c_int, MAX_LOCAL_USERS)) {
                return ctx.sendError(.conflict, "Pod user limit reached");
            }
        }
    }

    // Check duplicate username
    {
        var dup_stmt = database.prepare("SELECT id FROM users WHERE username = ? LIMIT 1") catch
            return ctx.sendError(.internal_server_error, "DB error");
        defer dup_stmt.finalize();
        dup_stmt.bindText(1, username.ptr, @intCast(username.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (dup_stmt.step() catch false) {
            return ctx.sendError(.conflict, "Username already taken");
        }
    }

    // Generate IDs
    var user_id_buf: [36]u8 = undefined;
    generateUuid(&user_id_buf);
    const user_id = user_id_buf[0..36];

    var agent_id_buf: [36]u8 = undefined;
    generateUuid(&agent_id_buf);
    const agent_id = agent_id_buf[0..36];

    // Generate ed25519 keypair for agent
    const kp = podos.crypto.ed25519Keygen();
    var seed = kp.seed;
    var pub_key = kp.public_key;
    defer std.crypto.secureZero(u8, &seed);

    // Generate DID from public key
    var did_buf: [128]u8 = undefined;
    const did_len = podos.crypto.publicKeyToDid(&pub_key, &did_buf);
    if (did_len <= 0) return ctx.sendError(.internal_server_error, "DID generation failed");
    const did = did_buf[0..@intCast(did_len)];

    // Derive vault key from password via Argon2id
    var salt: [16]u8 = undefined;
    std.crypto.random.bytes(&salt);
    var vault_key: [32]u8 = undefined;
    defer std.crypto.secureZero(u8, &vault_key);
    const argon2 = std.crypto.pwhash.argon2;
    argon2.kdf(std.heap.page_allocator, &vault_key, password, &salt, .{
        .t = 3,
        .m = 65536,
        .p = 4,
    }, .argon2id) catch return ctx.sendError(.internal_server_error, "Key derivation failed");

    // Encrypt vault key with itself for storage (same pattern as seed.py)
    var encrypted_vault_key: [256]u8 = undefined;
    const enc_vk_len = podos.crypto.encrypt(&vault_key, &vault_key, &encrypted_vault_key) catch
        return ctx.sendError(.internal_server_error, "Vault key encryption failed");

    // Encrypt agent private key with vault key
    var encrypted_seed: [256]u8 = undefined;
    const enc_seed_len = podos.crypto.encrypt(&seed, &vault_key, &encrypted_seed) catch
        return ctx.sendError(.internal_server_error, "Private key encryption failed");

    // Store vault key in transit engine
    _ = transit_eng.storeKey(user_id, &vault_key) catch
        return ctx.sendError(.internal_server_error, "Transit store failed");

    // ISO timestamp for created_at
    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    // BEGIN transaction
    database.exec("BEGIN IMMEDIATE") catch return ctx.sendError(.internal_server_error, "DB error");
    errdefer database.exec("ROLLBACK") catch {};

    // INSERT user
    {
        var stmt = database.prepare(
            "INSERT INTO users (id, username, display_name, user_type, vault_key_salt, encrypted_vault_key, is_demo, is_remote, is_discoverable, created_at)" ++
                " VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, user_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, username.ptr, @intCast(username.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(3, display_name.ptr, @intCast(display_name.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(4, user_type.ptr, @intCast(user_type.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindBlob(5, &salt, 16) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindBlob(6, &encrypted_vault_key, @intCast(enc_vk_len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(7, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "User insert failed");
    }

    // INSERT agent
    {
        var stmt = database.prepare(
            "INSERT INTO agents (id, owner_id, name, public_key, encrypted_private_key, did, created_at)" ++
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, agent_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(2, user_id.ptr, 36) catch return ctx.sendError(.internal_server_error, "DB error");
        const agent_name_str = try std.fmt.allocPrint(ctx.allocator, "{s}'s Agent", .{display_name});
        stmt.bindText(3, agent_name_str.ptr, @intCast(agent_name_str.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindBlob(4, &pub_key, 32) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindBlob(5, &encrypted_seed, @intCast(enc_seed_len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(6, did.ptr, @intCast(did.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        stmt.bindText(7, ts.ptr, @intCast(ts.len)) catch return ctx.sendError(.internal_server_error, "DB error");
        _ = stmt.step() catch return ctx.sendError(.internal_server_error, "Agent insert failed");
    }

    // COMMIT
    database.exec("COMMIT") catch return ctx.sendError(.internal_server_error, "Commit failed");

    // Create session
    const Sha256 = std.crypto.hash.sha2.Sha256;
    var fp_buf: [64]u8 = undefined;
    {
        const ua = ctx.getHeader("user-agent") orelse "";
        const ip = http.getClientIp(ctx);
        var h = Sha256.init(.{});
        h.update(ua);
        h.update("|");
        h.update(ip);
        const digest = h.finalResult();
        const hex = "0123456789abcdef";
        for (digest, 0..) |byte, i| {
            fp_buf[i * 2] = hex[byte >> 4];
            fp_buf[i * 2 + 1] = hex[byte & 0x0f];
        }
    }
    const fingerprint = fp_buf[0..64];
    var token_buf: [128]u8 = undefined;
    const token_len = sess_store.createSession(user_id, fingerprint, &token_buf) catch
        return ctx.sendError(.internal_server_error, "Session creation failed");
    const token = token_buf[0..token_len];

    // Build response JSON
    var esc_uid: [128]u8 = undefined;
    var esc_did: [256]u8 = undefined;
    var esc_uname: [128]u8 = undefined;
    const uid_len = json_mod.escapeJsonString(user_id, &esc_uid) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const edid_len = json_mod.escapeJsonString(did, &esc_did) catch return ctx.sendError(.internal_server_error, "Serialize failed");
    const uname_len = json_mod.escapeJsonString(username, &esc_uname) catch return ctx.sendError(.internal_server_error, "Serialize failed");

    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"user_id\":\"{s}\",\"did\":\"{s}\",\"username\":\"{s}\",\"session_token\":\"{s}\"}}",
        .{
            esc_uid[0..uid_len],
            esc_did[0..edid_len],
            esc_uname[0..uname_len],
            token,
        },
    );

    // Set-Cookie header
    const cookie_val = try ctx.buildSetCookieHeader("trustmesh_session", token, .{ .same_site = .lax });

    try ctx.jsonWithHeaders(.ok, body, &.{
        .{ .name = "set-cookie", .value = cookie_val },
    });
}

// ── HANDLER: GET /api/onboard/status ──
fn handleStatus(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");

    // Count local users
    var stmt = database.prepare("SELECT COUNT(*) FROM users WHERE is_remote = 0") catch
        return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    var user_count: c_int = 0;
    if (stmt.step() catch false) {
        user_count = stmt.getInt(0);
    }

    const initialized = user_count > 0;
    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"initialized\":{s},\"user_count\":{d},\"max_users\":{d}}}",
        .{
            if (initialized) "true" else "false",
            user_count,
            @as(usize, MAX_LOCAL_USERS),
        },
    );
    try ctx.json(.ok, body);
}

// ── Helpers ──
fn formatIsoTimestamp(epoch_secs: i64, buf: *[32]u8) usize {
    // Format: "2026-02-20T12:00:00"
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
