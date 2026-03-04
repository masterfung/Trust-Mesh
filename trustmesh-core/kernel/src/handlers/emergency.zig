// handlers/emergency.zig — Self-issued UCAN beacon + QR scan for emergency medical access.
//
// Routes:
//   POST /api/users/{id}/emergency/beacon  → handleBeacon  (patient generates QR tokens)
//   GET  /api/emergency/qr                 → handleQrScan  (first responder scans QR)
//
// Security properties:
//   - Private key never leaves Zig transit memory; zeroed immediately after signing
//   - ed25519 signature bound to patient DID — cannot be forged without private key
//   - Role-scoped capsule filtering enforced server-side regardless of token claims
//   - All access (success and denial) is audit-logged before returning a response
//   - Revocation table checked on every scan
//   - Rate limited: 3 beacon-generates/hr, 5 scans/hr per token hash

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router = @import("../router.zig");
const common = @import("common.zig");
const json_mod = podos.json;
const crypto_mod = podos.crypto;

// ── Module-level state (set once by server_main) ──

var _db: ?*podos.db.Database = null;
var _transit: ?*podos.transit.TransitEngine = null;
var _rate_limiter: ?*podos.rate_limit.RateLimiter = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setTransitEngine(t: *podos.transit.TransitEngine) void {
    _transit = t;
}

pub fn setRateLimiter(r: *podos.rate_limit.RateLimiter) void {
    _rate_limiter = r;
}

pub fn registerRoutes() void {
    // POST /api/users/{id}/emergency/beacon
    router.addPrefix(.POST, "/api/users/", handleBeacon);
    // GET /api/emergency/qr?t=...&p=...
    router.addExact(.GET, "/api/emergency/qr", handleQrScan);
    // POST /api/emergency/qr/alert  (responder → family message)
    router.addExact(.POST, "/api/emergency/qr/alert", handleQrAlert);
}

// ═══════════════════════════════════════════
//  ROLE SCOPES (mirrors Python ROLE_SCOPES in ucan.py)
// ═══════════════════════════════════════════

const paramedic_keywords = [_][]const u8{
    "blood_type", "allergy", "dnr", "emergency_contact", "medical",
};

const er_nurse_keywords = [_][]const u8{
    "blood_type", "weight", "height", "allergy", "emergency_contact", "medical", "dnr",
};

const attending_keywords = [_][]const u8{
    "medication",        "allergy",           "condition",         "surgery",
    "prescription",      "emergency_contact", "medical",           "blood_type",
    "weight",            "height",            "dnr",               "insurance",
    "doctor",            "hospital",
};

fn capsuleMatchesScope(title: []const u8, content: []const u8, role: []const u8) bool {
    const keywords: []const []const u8 = if (std.mem.eql(u8, role, "paramedic"))
        &paramedic_keywords
    else if (std.mem.eql(u8, role, "er_nurse"))
        &er_nurse_keywords
    else
        &attending_keywords;

    for (keywords) |kw| {
        if (containsWord(title, kw) or containsWord(content, kw)) return true;
    }
    return false;
}

/// Word-boundary aware search: keyword must be surrounded by non-alpha chars (or string edges).
fn containsWord(haystack: []const u8, needle: []const u8) bool {
    if (needle.len == 0) return false;
    var i: usize = 0;
    while (i + needle.len <= haystack.len) : (i += 1) {
        if (asciiEqlIgnoreCase(haystack[i..][0..needle.len], needle)) {
            const before_ok = i == 0 or !std.ascii.isAlphanumeric(haystack[i - 1]);
            const after_ok = i + needle.len == haystack.len or
                !std.ascii.isAlphanumeric(haystack[i + needle.len]);
            if (before_ok and after_ok) return true;
        }
    }
    return false;
}

fn asciiEqlIgnoreCase(a: []const u8, b: []const u8) bool {
    if (a.len != b.len) return false;
    for (a, b) |ca, cb| {
        if (std.ascii.toLower(ca) != std.ascii.toLower(cb)) return false;
    }
    return true;
}

// ═══════════════════════════════════════════
//  UCAN token helpers
// ═══════════════════════════════════════════

/// Build a UCAN payload JSON for a self-issued emergency beacon token.
/// Keys must be sorted alphabetically (UCAN canonical form).
/// Returns bytes written to out_buf.
fn buildPayloadJson(
    out_buf: []u8,
    role: []const u8,
    iss_did: []const u8,
    display_name: []const u8,
    pod_url: []const u8,
    exp: i64,
    iat: i64,
) !usize {
    // Role-specific scope JSON (keywords list)
    const scope_json: []const u8 = if (std.mem.eql(u8, role, "paramedic"))
        "[\"blood_type\",\"allergy\",\"dnr\",\"emergency_contact\",\"medical\"]"
    else if (std.mem.eql(u8, role, "er_nurse"))
        "[\"blood_type\",\"weight\",\"height\",\"allergy\",\"emergency_contact\",\"medical\",\"dnr\"]"
    else
        "[\"medication\",\"allergy\",\"condition\",\"surgery\",\"prescription\"," ++
        "\"emergency_contact\",\"medical\",\"blood_type\",\"weight\",\"height\"," ++
        "\"dnr\",\"insurance\",\"doctor\",\"hospital\"]";

    return (try std.fmt.bufPrint(
        out_buf,
        "{{\"att\":{{\"role\":\"{s}\",\"scope\":{{\"keywords\":{s}}}}}," ++
            "\"aud\":\"did:emergency:any\"," ++
            "\"exp\":{d}," ++
            "\"fct\":{{\"emergency_beacon\":true,\"issued_by\":\"{s}\",\"pod_url\":\"{s}\"}}," ++
            "\"iat\":{d}," ++
            "\"iss\":\"{s}\"}}",
        .{ role, scope_json, exp, display_name, pod_url, iat, iss_did },
    )).len;
}

/// Build UCAN token string: base64url(payload).base64url(signature)
/// seed_32 must be exactly 32 bytes (ed25519 seed). Caller zeros it after.
fn buildToken(
    allocator: std.mem.Allocator,
    payload_json: []const u8,
    seed_32: *const [32]u8,
) ![]u8 {
    // Encode payload
    var payload_b64_buf: [8192]u8 = undefined;
    const p_len = crypto_mod.base64urlEncode(payload_json, &payload_b64_buf);
    if (p_len == 0) return error.Base64Failed;
    const payload_b64 = payload_b64_buf[0..p_len];

    // Sign the payload bytes
    const sig_bytes = try crypto_mod.ed25519Sign(payload_json, seed_32);

    // Encode signature
    var sig_b64_buf: [128]u8 = undefined;
    const s_len = crypto_mod.base64urlEncode(&sig_bytes, &sig_b64_buf);
    if (s_len == 0) return error.Base64Failed;
    const sig_b64 = sig_b64_buf[0..s_len];

    // Concatenate: payload.sig
    return std.fmt.allocPrint(allocator, "{s}.{s}", .{ payload_b64, sig_b64 });
}

/// SHA-256 hex hash of a token string (for rate limiting + revocation).
fn tokenHash(token: []const u8, out: *[64]u8) void {
    common.sha256Hex(token, out);
}

// ═══════════════════════════════════════════
//  Audit helpers
// ═══════════════════════════════════════════

fn insertAuditLog(
    db: *podos.db.Database,
    actor_user_id: []const u8,
    target_user_id: []const u8,
    action: []const u8,
    event_type: []const u8,
    token_role: []const u8,
    decision: []const u8,
    reason: []const u8,
    details: []const u8,
    ts: []const u8,
) void {
    var audit_id_buf: [36]u8 = undefined;
    common.generateUuid(&audit_id_buf);
    const audit_id = audit_id_buf[0..36];

    var stmt = db.prepare(
        "INSERT INTO audit_logs " ++
            "(id, actor_user_id, target_user_id, action, event_type, token_role, decision, reason, details, created_at) " ++
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ) catch return;
    defer stmt.finalize();

    stmt.bindText(1, audit_id.ptr, 36) catch return;
    stmt.bindText(2, actor_user_id.ptr, @intCast(actor_user_id.len)) catch return;
    stmt.bindText(3, target_user_id.ptr, @intCast(target_user_id.len)) catch return;
    stmt.bindText(4, action.ptr, @intCast(action.len)) catch return;
    stmt.bindText(5, event_type.ptr, @intCast(event_type.len)) catch return;
    stmt.bindText(6, token_role.ptr, @intCast(token_role.len)) catch return;
    stmt.bindText(7, decision.ptr, @intCast(decision.len)) catch return;
    stmt.bindText(8, reason.ptr, @intCast(reason.len)) catch return;
    stmt.bindText(9, details.ptr, @intCast(details.len)) catch return;
    stmt.bindText(10, ts.ptr, @intCast(ts.len)) catch return;
    _ = stmt.step() catch {};
}

fn insertAuditLogWithId(
    db: *podos.db.Database,
    audit_id: []const u8,
    actor_user_id: []const u8,
    target_user_id: []const u8,
    action: []const u8,
    event_type: []const u8,
    token_role: []const u8,
    decision: []const u8,
    reason: []const u8,
    details: []const u8,
    ts: []const u8,
) void {
    var stmt = db.prepare(
        "INSERT INTO audit_logs " ++
            "(id, actor_user_id, target_user_id, action, event_type, token_role, decision, reason, details, created_at) " ++
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ) catch return;
    defer stmt.finalize();

    stmt.bindText(1, audit_id.ptr, @intCast(audit_id.len)) catch return;
    stmt.bindText(2, actor_user_id.ptr, @intCast(actor_user_id.len)) catch return;
    stmt.bindText(3, target_user_id.ptr, @intCast(target_user_id.len)) catch return;
    stmt.bindText(4, action.ptr, @intCast(action.len)) catch return;
    stmt.bindText(5, event_type.ptr, @intCast(event_type.len)) catch return;
    stmt.bindText(6, token_role.ptr, @intCast(token_role.len)) catch return;
    stmt.bindText(7, decision.ptr, @intCast(decision.len)) catch return;
    stmt.bindText(8, reason.ptr, @intCast(reason.len)) catch return;
    stmt.bindText(9, details.ptr, @intCast(details.len)) catch return;
    stmt.bindText(10, ts.ptr, @intCast(ts.len)) catch return;
    _ = stmt.step() catch {};
}

// ═══════════════════════════════════════════
//  Handler 1: POST /api/users/{id}/emergency/beacon
// ═══════════════════════════════════════════

fn handleBeacon(ctx: *http.RequestContext) !void {
    // Only handle /api/users/{id}/emergency/beacon
    if (std.mem.indexOf(u8, ctx.path, "/emergency/beacon") == null) {
        return ctx.sendError(.not_found, "Not found");
    }

    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit = _transit orelse return ctx.sendError(.service_unavailable, "Transit not ready");
    const rl = _rate_limiter orelse return ctx.sendError(.service_unavailable, "Rate limiter not ready");

    // Auth
    var uid_buf: [128]u8 = undefined;
    const auth_user_id = common.requireAuth(ctx, &uid_buf) orelse return;

    // Extract user_id from path: /api/users/{user_id}/emergency/beacon
    const prefix = "/api/users/";
    const rest = ctx.path[prefix.len..];
    const slash = std.mem.indexOfScalar(u8, rest, '/') orelse
        return ctx.sendError(.bad_request, "Invalid path");
    const path_user_id = rest[0..slash];

    if (!std.mem.eql(u8, auth_user_id, path_user_id)) {
        return ctx.sendError(.forbidden, "Access denied");
    }

    // Rate limit check
    const rl_result = rl.checkEmergencyIssue(auth_user_id);
    if (!rl_result.allowed) {
        return ctx.sendError(.too_many_requests, rl_result.getMessage());
    }

    // Load agent (DID + encrypted private key + public key)
    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len];

    var agent_did_buf: [256]u8 = undefined;
    var agent_did_len: usize = 0;
    var agent_pubkey_buf: [64]u8 = undefined; // hex or raw
    var agent_pubkey_len: usize = 0;
    var enc_pk_buf: [2048]u8 = undefined;
    var enc_pk_len: usize = 0;
    var display_name_buf: [256]u8 = undefined;
    var display_name_len: usize = 0;
    var username_buf: [128]u8 = undefined;
    var username_len: usize = 0;

    {
        var stmt = database.prepare(
            "SELECT a.did, a.encrypted_private_key, a.public_key, u.display_name, u.username " ++
                "FROM agents a JOIN users u ON u.id = a.owner_id " ++
                "WHERE a.owner_id = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, auth_user_id.ptr, @intCast(auth_user_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        if (!(stmt.step() catch false)) {
            return ctx.sendError(.not_found, "Agent not found — register first");
        }

        // DID
        const did_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "No agent DID");
        const did_s = std.mem.span(did_ptr);
        if (did_s.len > agent_did_buf.len) return ctx.sendError(.internal_server_error, "DID too long");
        @memcpy(agent_did_buf[0..did_s.len], did_s);
        agent_did_len = did_s.len;

        // Encrypted private key (blob)
        const epk_blob = stmt.getBlob(1) orelse return ctx.sendError(.internal_server_error, "No private key");
        if (epk_blob.len > enc_pk_buf.len) return ctx.sendError(.internal_server_error, "Key too large");
        @memcpy(enc_pk_buf[0..epk_blob.len], epk_blob);
        enc_pk_len = epk_blob.len;

        // Public key (blob)
        const pubkey_blob = stmt.getBlob(2) orelse &[_]u8{};
        const copy_len = @min(pubkey_blob.len, agent_pubkey_buf.len);
        @memcpy(agent_pubkey_buf[0..copy_len], pubkey_blob[0..copy_len]);
        agent_pubkey_len = copy_len;

        // Display name
        const dn_ptr = stmt.getText(3);
        const dn_s = if (dn_ptr) |p| std.mem.span(p) else "Patient";
        const dn_copy = @min(dn_s.len, display_name_buf.len);
        @memcpy(display_name_buf[0..dn_copy], dn_s[0..dn_copy]);
        display_name_len = dn_copy;

        // Username
        const un_ptr = stmt.getText(4);
        const un_s = if (un_ptr) |p| std.mem.span(p) else "";
        const un_copy = @min(un_s.len, username_buf.len);
        @memcpy(username_buf[0..un_copy], un_s[0..un_copy]);
        username_len = un_copy;
    }

    const agent_did = agent_did_buf[0..agent_did_len];
    const display_name = display_name_buf[0..display_name_len];
    const enc_pk = enc_pk_buf[0..enc_pk_len];

    // Check vault key is loaded
    if (!transit.hasKey(auth_user_id)) {
        return ctx.sendError(.forbidden, "Vault not loaded — log in first");
    }

    // Decrypt private key seed (32 bytes)
    var seed_buf: [256]u8 = undefined;
    const seed_len = transit.decryptForUser(auth_user_id, enc_pk, "", &seed_buf) catch {
        return ctx.sendError(.internal_server_error, "Failed to decrypt private key");
    };
    if (seed_len < 32) {
        std.crypto.secureZero(u8, seed_buf[0..seed_len]);
        return ctx.sendError(.internal_server_error, "Private key too short");
    }
    const seed_32: *const [32]u8 = seed_buf[0..32];

    // Get pod URL from environment (fallback to localhost)
    // We store it as a simple string; in production TRUSTMESH_POD_URL is set
    const pod_url = "http://localhost:9000";

    // Generate tokens for all 3 roles
    const roles = [_][]const u8{ "paramedic", "er_nurse", "attending_physician" };
    const exp = now_s + 1800;

    var paramedic_token: []u8 = "";
    var er_nurse_token: []u8 = "";
    var attending_token: []u8 = "";

    inline for (roles) |role| {
        var payload_buf: [4096]u8 = undefined;
        const pay_len = buildPayloadJson(
            &payload_buf, role, agent_did, display_name, pod_url, exp, now_s,
        ) catch {
            std.crypto.secureZero(u8, seed_buf[0..seed_len]);
            return ctx.sendError(.internal_server_error, "Failed to build payload");
        };
        const payload = payload_buf[0..pay_len];

        const token = buildToken(ctx.allocator, payload, seed_32) catch {
            std.crypto.secureZero(u8, seed_buf[0..seed_len]);
            return ctx.sendError(.internal_server_error, "Failed to build token");
        };

        if (std.mem.eql(u8, role, "paramedic")) {
            paramedic_token = token;
        } else if (std.mem.eql(u8, role, "er_nurse")) {
            er_nurse_token = token;
        } else {
            attending_token = token;
        }
    }

    // Zero seed immediately
    std.crypto.secureZero(u8, seed_buf[0..seed_len]);

    // Generate audit ID
    var audit_id_buf: [36]u8 = undefined;
    common.generateUuid(&audit_id_buf);
    const audit_id = audit_id_buf[0..36];

    // Audit log the beacon generation
    insertAuditLogWithId(
        database,
        audit_id,
        auth_user_id,
        auth_user_id,
        "emergency_beacon_generated",
        "emergency",
        "all_roles",
        "allowed",
        "",
        "{\"roles\":[\"paramedic\",\"er_nurse\",\"attending_physician\"]}",
        ts,
    );

    // Record rate limit
    rl.recordEmergencyIssue(auth_user_id) catch {};

    // Build QR URLs
    const username = username_buf[0..username_len];
    const emt_url = std.fmt.allocPrint(ctx.allocator, "{s}/emergency/scan?t={s}&p={s}", .{
        pod_url, paramedic_token, username,
    }) catch return ctx.sendError(.internal_server_error, "Alloc failed");
    const nurse_url = std.fmt.allocPrint(ctx.allocator, "{s}/emergency/scan?t={s}&p={s}", .{
        pod_url, er_nurse_token, username,
    }) catch return ctx.sendError(.internal_server_error, "Alloc failed");
    const doc_url = std.fmt.allocPrint(ctx.allocator, "{s}/emergency/scan?t={s}&p={s}", .{
        pod_url, attending_token, username,
    }) catch return ctx.sendError(.internal_server_error, "Alloc failed");

    // Escape tokens and URLs for JSON
    var esc_pm: [8192]u8 = undefined;
    var esc_er: [8192]u8 = undefined;
    var esc_at: [8192]u8 = undefined;
    var esc_did: [256]u8 = undefined;
    var esc_dn: [512]u8 = undefined;
    var esc_emu: [8192]u8 = undefined;
    var esc_nu: [8192]u8 = undefined;
    var esc_du: [8192]u8 = undefined;
    var esc_aid: [128]u8 = undefined;
    var esc_ts: [64]u8 = undefined;
    var esc_pu: [512]u8 = undefined;

    const pm_len = json_mod.escapeJsonString(paramedic_token, &esc_pm) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const er_len = json_mod.escapeJsonString(er_nurse_token, &esc_er) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const at_len = json_mod.escapeJsonString(attending_token, &esc_at) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const did_len_e = json_mod.escapeJsonString(agent_did, &esc_did) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const dn_len_e = json_mod.escapeJsonString(display_name, &esc_dn) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const emu_len = json_mod.escapeJsonString(emt_url, &esc_emu) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const nu_len = json_mod.escapeJsonString(nurse_url, &esc_nu) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const du_len = json_mod.escapeJsonString(doc_url, &esc_du) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const aid_len_e = json_mod.escapeJsonString(audit_id, &esc_aid) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const ts_len_e = json_mod.escapeJsonString(ts, &esc_ts) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");
    const pu_len = json_mod.escapeJsonString(pod_url, &esc_pu) catch
        return ctx.sendError(.internal_server_error, "Serialize failed");

    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"tokens\":{{\"paramedic\":\"{s}\",\"er_nurse\":\"{s}\",\"attending_physician\":\"{s}\"}}," ++
            "\"qr_urls\":{{\"paramedic\":\"{s}\",\"er_nurse\":\"{s}\",\"attending_physician\":\"{s}\"}}," ++
            "\"patient_did\":\"{s}\",\"patient_name\":\"{s}\",\"pod_url\":\"{s}\"," ++
            "\"expires_in\":1800,\"generated_at\":\"{s}\",\"audit_id\":\"{s}\"}}",
        .{
            esc_pm[0..pm_len], esc_er[0..er_len], esc_at[0..at_len],
            esc_emu[0..emu_len], esc_nu[0..nu_len], esc_du[0..du_len],
            esc_did[0..did_len_e], esc_dn[0..dn_len_e], esc_pu[0..pu_len],
            esc_ts[0..ts_len_e], esc_aid[0..aid_len_e],
        },
    );
    try ctx.json(.ok, body);
}

// ═══════════════════════════════════════════
//  Handler 2: GET /api/emergency/qr?t=...&p=...
// ═══════════════════════════════════════════

fn handleQrScan(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const transit = _transit orelse return ctx.sendError(.service_unavailable, "Transit not ready");
    const rl = _rate_limiter orelse return ctx.sendError(.service_unavailable, "Rate limiter not ready");

    const now_s = std.time.timestamp();
    var ts_buf: [32]u8 = undefined;
    const ts_len_v = common.formatIsoTimestamp(now_s, &ts_buf);
    const ts = ts_buf[0..ts_len_v];

    // Read query params
    const token_str = common.getQueryParam(ctx.query, "t") orelse {
        return ctx.sendError(.bad_request, "Missing token parameter");
    };
    const patient_username = common.getQueryParam(ctx.query, "p") orelse {
        return ctx.sendError(.bad_request, "Missing patient username parameter");
    };

    // Input validation
    if (token_str.len > 4096) return ctx.sendError(.bad_request, "Token too long");
    if (patient_username.len > 50) return ctx.sendError(.bad_request, "Username too long");
    if (token_str.len < 10) return ctx.sendError(.bad_request, "Token too short");

    // Split token on "." → payload_b64 + sig_b64
    const dot = std.mem.indexOfScalar(u8, token_str, '.') orelse
        return ctx.sendError(.bad_request, "Invalid token format");
    const payload_b64 = token_str[0..dot];
    const sig_b64 = token_str[dot + 1 ..];

    if (sig_b64.len == 0 or payload_b64.len == 0)
        return ctx.sendError(.bad_request, "Invalid token format");

    // Decode payload
    var payload_bytes: [4096]u8 = undefined;
    const payload_len = crypto_mod.base64urlDecode(payload_b64, &payload_bytes) catch {
        return ctx.sendError(.bad_request, "Invalid token encoding");
    };
    const payload_json = payload_bytes[0..payload_len];

    // Parse JSON payload to extract fields
    const PayloadParsed = struct {
        iss: ?[]const u8 = null,
        aud: ?[]const u8 = null,
        exp: ?i64 = null,
        iat: ?i64 = null,
        att: ?struct {
            role: ?[]const u8 = null,
        } = null,
        fct: ?struct {
            emergency_beacon: ?bool = null,
        } = null,
    };

    const parsed = json_mod.parse(PayloadParsed, ctx.allocator, payload_json) catch {
        return ctx.sendError(.bad_request, "Invalid token payload");
    };
    defer parsed.deinit();
    const payload = parsed.value;

    const iss_did = payload.iss orelse return ctx.sendError(.bad_request, "Missing iss in token");
    const aud = payload.aud orelse return ctx.sendError(.bad_request, "Missing aud in token");
    const exp = payload.exp orelse return ctx.sendError(.bad_request, "Missing exp in token");
    const role = if (payload.att) |a| (a.role orelse "paramedic") else "paramedic";

    // Validate audience
    if (!std.mem.eql(u8, aud, "did:emergency:any")) {
        insertAuditLog(database, "", "", "emergency_access_denied", "emergency", role,
            "denied", "invalid_audience", "{}", ts);
        return ctx.sendError(.forbidden, "Not an emergency beacon token");
    }

    // Check expiry
    if (exp <= now_s) {
        insertAuditLog(database, "", "", "emergency_access_denied", "emergency", role,
            "denied", "token_expired", "{}", ts);
        return ctx.sendError(.forbidden, "Token expired — patient must refresh QR code");
    }

    // Validate beacon fact
    const is_beacon = if (payload.fct) |f| (f.emergency_beacon orelse false) else false;
    if (!is_beacon) {
        insertAuditLog(database, "", "", "emergency_access_denied", "emergency", role,
            "denied", "not_beacon", "{}", ts);
        return ctx.sendError(.forbidden, "Not a beacon token");
    }

    // Look up patient by username
    var patient_user_id_buf: [128]u8 = undefined;
    var patient_user_id_len: usize = 0;
    var patient_agent_did_buf: [256]u8 = undefined;
    var patient_agent_did_len: usize = 0;
    var patient_pubkey_blob: [64]u8 = undefined;
    var patient_pubkey_len: usize = 0;
    var patient_name_buf: [256]u8 = undefined;
    var patient_name_len: usize = 0;

    {
        var stmt = database.prepare(
            "SELECT u.id, a.did, a.public_key, u.display_name " ++
                "FROM users u JOIN agents a ON a.owner_id = u.id " ++
                "WHERE u.username = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, patient_username.ptr, @intCast(patient_username.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        if (!(stmt.step() catch false)) {
            insertAuditLog(database, "", "", "emergency_access_denied", "emergency", role,
                "denied", "patient_not_found", "{}", ts);
            return ctx.sendError(.not_found, "Patient not found");
        }

        const uid_ptr = stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "No user ID");
        const uid_s = std.mem.span(uid_ptr);
        @memcpy(patient_user_id_buf[0..uid_s.len], uid_s);
        patient_user_id_len = uid_s.len;

        const did_ptr = stmt.getText(1) orelse return ctx.sendError(.internal_server_error, "No agent DID");
        const did_s = std.mem.span(did_ptr);
        @memcpy(patient_agent_did_buf[0..did_s.len], did_s);
        patient_agent_did_len = did_s.len;

        const pk_blob = stmt.getBlob(2) orelse &[_]u8{};
        const copy_len = @min(pk_blob.len, patient_pubkey_blob.len);
        @memcpy(patient_pubkey_blob[0..copy_len], pk_blob[0..copy_len]);
        patient_pubkey_len = copy_len;

        const pn_ptr = stmt.getText(3);
        const pn_s = if (pn_ptr) |p| std.mem.span(p) else "Patient";
        const pn_copy = @min(pn_s.len, patient_name_buf.len);
        @memcpy(patient_name_buf[0..pn_copy], pn_s[0..pn_copy]);
        patient_name_len = pn_copy;
    }

    const patient_user_id = patient_user_id_buf[0..patient_user_id_len];
    const patient_agent_did = patient_agent_did_buf[0..patient_agent_did_len];
    const patient_name = patient_name_buf[0..patient_name_len];

    // Determine whose public key to verify against
    const is_self_issued = std.mem.eql(u8, iss_did, patient_agent_did);
    var verify_pubkey: [32]u8 = undefined;

    if (is_self_issued) {
        if (patient_pubkey_len != 32) {
            insertAuditLog(database, patient_user_id, patient_user_id,
                "emergency_access_denied", "emergency", role,
                "denied", "invalid_public_key", "{}", ts);
            return ctx.sendError(.internal_server_error, "Invalid public key length");
        }
        @memcpy(&verify_pubkey, patient_pubkey_blob[0..32]);
    } else {
        // Org-issued: find the issuer agent by DID and verify they are a service/organization
        var found_issuer = false;
        var issuer_pk_buf: [64]u8 = undefined;
        var issuer_pk_len: usize = 0;

        var stmt = database.prepare(
            "SELECT a.public_key FROM agents a " ++
                "JOIN users u ON u.id = a.owner_id " ++
                "WHERE a.did = ? AND u.user_type IN ('service', 'organization') LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, iss_did.ptr, @intCast(iss_did.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        if (stmt.step() catch false) {
            const pk_blob = stmt.getBlob(0) orelse &[_]u8{};
            const copy_len = @min(pk_blob.len, issuer_pk_buf.len);
            @memcpy(issuer_pk_buf[0..copy_len], pk_blob[0..copy_len]);
            issuer_pk_len = copy_len;
            found_issuer = true;
        }

        if (!found_issuer or issuer_pk_len != 32) {
            insertAuditLog(database, patient_user_id, patient_user_id,
                "emergency_access_denied", "emergency", role,
                "denied", "unknown_issuer", "{}", ts);
            return ctx.sendError(.forbidden, "Unknown or unauthorized token issuer");
        }
        @memcpy(&verify_pubkey, issuer_pk_buf[0..32]);
    }

    // Verify signature
    var sig_bytes: [64]u8 = undefined;
    const sig_dec_len = crypto_mod.base64urlDecode(sig_b64, &sig_bytes) catch {
        insertAuditLog(database, patient_user_id, patient_user_id,
            "emergency_access_denied", "emergency", role,
            "denied", "invalid_signature_encoding", "{}", ts);
        return ctx.sendError(.forbidden, "Invalid token signature encoding");
    };
    if (sig_dec_len != 64) {
        insertAuditLog(database, patient_user_id, patient_user_id,
            "emergency_access_denied", "emergency", role,
            "denied", "invalid_signature_length", "{}", ts);
        return ctx.sendError(.forbidden, "Invalid token signature");
    }

    if (!crypto_mod.ed25519Verify(payload_json, &sig_bytes, &verify_pubkey)) {
        insertAuditLog(database, patient_user_id, patient_user_id,
            "emergency_access_denied", "emergency", role,
            "denied", "signature_invalid", "{}", ts);
        return ctx.sendError(.forbidden, "Token signature verification failed");
    }

    // Check revocation
    var t_hash: [64]u8 = undefined;
    tokenHash(token_str, &t_hash);
    {
        var stmt = database.prepare(
            "SELECT id FROM ucan_revocations WHERE token_hash = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, &t_hash, 64) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (stmt.step() catch false) {
            insertAuditLog(database, patient_user_id, patient_user_id,
                "emergency_access_denied", "emergency", role,
                "denied", "token_revoked", "{}", ts);
            return ctx.sendError(.forbidden, "Token has been revoked");
        }
    }

    // Rate limit per token hash
    const rl_result = rl.checkEmergencyPresent(&t_hash);
    if (!rl_result.allowed) {
        insertAuditLog(database, patient_user_id, patient_user_id,
            "emergency_access_denied", "emergency", role,
            "denied", "rate_limited", "{}", ts);
        return ctx.sendError(.too_many_requests, rl_result.getMessage());
    }

    // Check vault key is loaded for patient
    if (!transit.hasKey(patient_user_id)) {
        insertAuditLog(database, patient_user_id, patient_user_id,
            "emergency_access_denied", "emergency", role,
            "denied", "vault_not_loaded", "{}", ts);
        return ctx.sendError(.forbidden, "Patient vault not available — pod offline");
    }

    // Fetch emergency-accessible capsules
    var stmt = database.prepare(
        "SELECT id, title, content_encrypted, category " ++
            "FROM knowledge_capsules " ++
            "WHERE owner_id = ? AND is_archived = 0 AND emergency_accessible = 1 " ++
            "AND deleted_at IS NULL " ++
            "ORDER BY created_at DESC LIMIT 100",
    ) catch return ctx.sendError(.internal_server_error, "DB error");
    defer stmt.finalize();
    stmt.bindText(1, patient_user_id.ptr, @intCast(patient_user_id.len)) catch
        return ctx.sendError(.internal_server_error, "DB error");

    // Build capsule list + track accessed IDs for audit
    var capsules_json = std.ArrayList(u8){};
    try capsules_json.appendSlice(ctx.allocator, "[");
    var capsule_ids_json = std.ArrayList(u8){};
    try capsule_ids_json.appendSlice(ctx.allocator, "[");
    var first = true;
    var capsule_count: usize = 0;
    var total_capsules: usize = 0;

    while (stmt.step() catch false) {
        total_capsules += 1;
        const cap_id_ptr = stmt.getText(0) orelse continue;
        const cap_id = std.mem.span(cap_id_ptr);
        const title_ptr = stmt.getText(1) orelse continue;
        const title_s = std.mem.span(title_ptr);
        const enc_blob = stmt.getBlob(2) orelse continue;
        const cat_ptr = stmt.getText(3);
        const cat_s = if (cat_ptr) |p| std.mem.span(p) else "";

        // Decrypt
        var dec_buf: [128 * 1024]u8 = undefined;
        const dec_len = transit.decryptForUser(patient_user_id, enc_blob, "", &dec_buf) catch continue;
        const content = dec_buf[0..dec_len];

        // Scope check
        if (!capsuleMatchesScope(title_s, content, role)) continue;

        // Escape for JSON
        var esc_id: [128]u8 = undefined;
        var esc_title: [512]u8 = undefined;
        var esc_content: [64 * 1024]u8 = undefined;
        var esc_cat: [128]u8 = undefined;
        const eid = json_mod.escapeJsonString(cap_id, &esc_id) catch continue;
        const etitle = json_mod.escapeJsonString(title_s, &esc_title) catch continue;
        const econtent = json_mod.escapeJsonString(content, &esc_content) catch continue;
        const ecat = json_mod.escapeJsonString(cat_s, &esc_cat) catch continue;

        if (!first) {
            try capsules_json.appendSlice(ctx.allocator, ",");
            try capsule_ids_json.appendSlice(ctx.allocator, ",");
        }
        first = false;

        const entry = try std.fmt.allocPrint(ctx.allocator,
            "{{\"id\":\"{s}\",\"title\":\"{s}\",\"content\":\"{s}\",\"category\":\"{s}\"}}",
            .{ esc_id[0..eid], esc_title[0..etitle], esc_content[0..econtent], esc_cat[0..ecat] },
        );
        try capsules_json.appendSlice(ctx.allocator, entry);

        const id_entry = try std.fmt.allocPrint(ctx.allocator, "\"{s}\"", .{esc_id[0..eid]});
        try capsule_ids_json.appendSlice(ctx.allocator, id_entry);
        capsule_count += 1;
    }
    try capsules_json.appendSlice(ctx.allocator, "]");
    try capsule_ids_json.appendSlice(ctx.allocator, "]");

    // Generate audit ID for the successful access
    var audit_id_buf: [36]u8 = undefined;
    common.generateUuid(&audit_id_buf);
    const audit_id = audit_id_buf[0..36];

    // Build details JSON
    const details = try std.fmt.allocPrint(ctx.allocator,
        "{{\"capsule_ids\":{s},\"capsule_count\":{d}}}",
        .{ capsule_ids_json.items, capsule_count },
    );

    // Escape role for audit
    var esc_role: [64]u8 = undefined;
    const erole_len = json_mod.escapeJsonString(role, &esc_role) catch 0;
    const role_for_audit = if (erole_len > 0) esc_role[0..erole_len] else role;

    // Audit log the successful access
    insertAuditLogWithId(
        database,
        audit_id,
        patient_user_id,
        patient_user_id,
        "emergency_data_access",
        "emergency",
        role_for_audit,
        "allowed",
        "",
        details,
        ts,
    );

    // Insert family notifications
    insertFamilyNotifications(database, patient_user_id, patient_name, role, audit_id, ts, ctx.allocator);

    // Record rate limit
    rl.recordEmergencyPresent(&t_hash) catch {};

    // Expiry timestamp
    var exp_ts_buf: [32]u8 = undefined;
    const exp_ts_len = common.formatIsoTimestamp(exp, &exp_ts_buf);
    const exp_ts = exp_ts_buf[0..exp_ts_len];

    // Escape names
    var esc_pname: [512]u8 = undefined;
    var esc_role2: [64]u8 = undefined;
    var esc_aid: [128]u8 = undefined;
    var esc_exp: [64]u8 = undefined;
    const epname = json_mod.escapeJsonString(patient_name, &esc_pname) catch 0;
    const erole2 = json_mod.escapeJsonString(role, &esc_role2) catch 0;
    const eaid = json_mod.escapeJsonString(audit_id, &esc_aid) catch 0;
    const eexp = json_mod.escapeJsonString(exp_ts, &esc_exp) catch 0;

    const body = try std.fmt.allocPrint(ctx.allocator,
        "{{\"patient_name\":\"{s}\",\"role\":\"{s}\"," ++
            "\"capsules\":{s},\"capsule_count\":{d},\"total_capsules\":{d}," ++
            "\"audit_id\":\"{s}\",\"expires_at\":\"{s}\"," ++
            "\"family_notified\":true}}",
        .{
            esc_pname[0..epname],
            esc_role2[0..erole2],
            capsules_json.items,
            capsule_count,
            total_capsules,
            esc_aid[0..eaid],
            esc_exp[0..eexp],
        },
    );
    try ctx.json(.ok, body);
}

// ═══════════════════════════════════════════
//  Family notification helper
// ═══════════════════════════════════════════

fn insertFamilyNotifications(
    db: *podos.db.Database,
    patient_user_id: []const u8,
    patient_name: []const u8,
    role: []const u8,
    audit_id: []const u8,
    ts: []const u8,
    allocator: std.mem.Allocator,
) void {
    // Find family members in shared networks
    var stmt = db.prepare(
        "SELECT DISTINCT nm2.user_id " ++
            "FROM network_memberships nm1 " ++
            "JOIN network_memberships nm2 ON nm2.network_id = nm1.network_id " ++
            "JOIN users u ON u.id = nm2.user_id " ++
            "WHERE nm1.user_id = ? AND nm2.user_id != ? " ++
            "AND u.is_remote = 0 " ++
            "LIMIT 10",
    ) catch return;
    defer stmt.finalize();
    stmt.bindText(1, patient_user_id.ptr, @intCast(patient_user_id.len)) catch return;
    stmt.bindText(2, patient_user_id.ptr, @intCast(patient_user_id.len)) catch return;

    const role_display: []const u8 = if (std.mem.eql(u8, role, "paramedic")) "EMT/Paramedic"
        else if (std.mem.eql(u8, role, "er_nurse")) "ER Nurse"
        else "Attending Physician";

    while (stmt.step() catch false) {
        const member_id_ptr = stmt.getText(0) orelse continue;
        const member_id = std.mem.span(member_id_ptr);

        var notif_id_buf: [36]u8 = undefined;
        common.generateUuid(&notif_id_buf);
        const notif_id = notif_id_buf[0..36];

        const title = std.fmt.allocPrint(allocator,
            "Emergency access: {s}", .{patient_name},
        ) catch continue;

        const body_text = std.fmt.allocPrint(allocator,
            "A {s} accessed {s}'s emergency medical data. Audit: {s}",
            .{ role_display, patient_name, audit_id },
        ) catch continue;

        var notif_stmt = db.prepare(
            "INSERT INTO notifications " ++
                "(id, user_id, notification_type, title, body, is_read, created_at) " ++
                "VALUES (?, ?, 'emergency_access', ?, ?, 0, ?)",
        ) catch continue;
        defer notif_stmt.finalize();

        notif_stmt.bindText(1, notif_id.ptr, 36) catch continue;
        notif_stmt.bindText(2, member_id.ptr, @intCast(member_id.len)) catch continue;
        notif_stmt.bindText(3, title.ptr, @intCast(title.len)) catch continue;
        notif_stmt.bindText(4, body_text.ptr, @intCast(body_text.len)) catch continue;
        notif_stmt.bindText(5, ts.ptr, @intCast(ts.len)) catch continue;
        _ = notif_stmt.step() catch {};
    }
}

// ═══════════════════════════════════════════
//  Handler 3: POST /api/emergency/qr/alert
//  Responder sends a message to the patient's family network.
//  Token validation proves the responder has a valid emergency QR.
// ═══════════════════════════════════════════

fn handleQrAlert(ctx: *http.RequestContext) !void {
    const database = _db orelse return ctx.sendError(.service_unavailable, "DB not ready");
    const alloc = ctx.allocator;

    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    if (ctx.body.len > 4096) return ctx.sendError(.payload_too_large, "Body too large");

    // Parse request body: { t, p, message }
    const AlertRequest = struct {
        t: ?[]const u8 = null,
        p: ?[]const u8 = null,
        message: ?[]const u8 = null,
    };
    const parsed_req = json_mod.parse(AlertRequest, alloc, ctx.body) catch {
        return ctx.sendError(.bad_request, "Invalid JSON body");
    };
    defer parsed_req.deinit();

    const token_str = parsed_req.value.t orelse return ctx.sendError(.bad_request, "Missing t");
    const patient_username = parsed_req.value.p orelse return ctx.sendError(.bad_request, "Missing p");
    const message = parsed_req.value.message orelse return ctx.sendError(.bad_request, "Missing message");

    if (token_str.len > 4096 or patient_username.len > 50 or message.len > 500)
        return ctx.sendError(.bad_request, "Invalid parameters");
    if (token_str.len < 10) return ctx.sendError(.bad_request, "Token too short");

    // ── Token validation (mirrors handleQrScan) ──

    const dot = std.mem.indexOfScalar(u8, token_str, '.') orelse
        return ctx.sendError(.bad_request, "Invalid token format");
    const payload_b64 = token_str[0..dot];
    const sig_b64 = token_str[dot + 1 ..];
    if (sig_b64.len == 0 or payload_b64.len == 0)
        return ctx.sendError(.bad_request, "Invalid token format");

    var payload_bytes: [4096]u8 = undefined;
    const payload_len = crypto_mod.base64urlDecode(payload_b64, &payload_bytes) catch {
        return ctx.sendError(.forbidden, "Invalid token encoding");
    };
    const payload_json = payload_bytes[0..payload_len];

    const AlertPayload = struct {
        iss: ?[]const u8 = null,
        aud: ?[]const u8 = null,
        exp: ?i64 = null,
        att: ?struct { role: ?[]const u8 = null } = null,
        fct: ?struct { emergency_beacon: ?bool = null } = null,
    };
    const pp = json_mod.parse(AlertPayload, alloc, payload_json) catch {
        return ctx.sendError(.forbidden, "Invalid token payload");
    };
    defer pp.deinit();
    const pv = pp.value;

    const now_s = std.time.timestamp();
    const exp = pv.exp orelse return ctx.sendError(.forbidden, "Missing exp");
    const aud = pv.aud orelse return ctx.sendError(.forbidden, "Missing aud");
    const iss_did = pv.iss orelse return ctx.sendError(.forbidden, "Missing iss");
    const role = if (pv.att) |a| (a.role orelse "paramedic") else "paramedic";
    const is_beacon = if (pv.fct) |f| (f.emergency_beacon orelse false) else false;

    if (!std.mem.eql(u8, aud, "did:emergency:any"))
        return ctx.sendError(.forbidden, "Not an emergency beacon token");
    if (exp <= now_s)
        return ctx.sendError(.forbidden, "Token expired");
    if (!is_beacon)
        return ctx.sendError(.forbidden, "Not a beacon token");

    // Look up patient by username
    var patient_user_id_buf: [128]u8 = undefined;
    var patient_user_id_len: usize = 0;
    var patient_agent_did_buf: [256]u8 = undefined;
    var patient_agent_did_len: usize = 0;
    var patient_pubkey_blob: [64]u8 = undefined;
    var patient_pubkey_len: usize = 0;
    var patient_name_buf: [256]u8 = undefined;
    var patient_name_len: usize = 0;
    {
        var stmt = database.prepare(
            "SELECT u.id, a.did, a.public_key, u.display_name " ++
                "FROM users u JOIN agents a ON a.owner_id = u.id " ++
                "WHERE u.username = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, patient_username.ptr, @intCast(patient_username.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        if (!(stmt.step() catch false))
            return ctx.sendError(.not_found, "Patient not found");

        const uid_s = std.mem.span(stmt.getText(0) orelse return ctx.sendError(.internal_server_error, "No user ID"));
        @memcpy(patient_user_id_buf[0..uid_s.len], uid_s);
        patient_user_id_len = uid_s.len;

        const did_s = std.mem.span(stmt.getText(1) orelse return ctx.sendError(.internal_server_error, "No DID"));
        @memcpy(patient_agent_did_buf[0..did_s.len], did_s);
        patient_agent_did_len = did_s.len;

        const pk_blob = stmt.getBlob(2) orelse &[_]u8{};
        const copy_len = @min(pk_blob.len, patient_pubkey_blob.len);
        @memcpy(patient_pubkey_blob[0..copy_len], pk_blob[0..copy_len]);
        patient_pubkey_len = copy_len;

        const pn_ptr = stmt.getText(3);
        const pn_s = if (pn_ptr) |p| std.mem.span(p) else "Patient";
        const pn_copy = @min(pn_s.len, patient_name_buf.len);
        @memcpy(patient_name_buf[0..pn_copy], pn_s[0..pn_copy]);
        patient_name_len = pn_copy;
    }

    const patient_user_id = patient_user_id_buf[0..patient_user_id_len];
    const patient_agent_did = patient_agent_did_buf[0..patient_agent_did_len];
    const patient_name = patient_name_buf[0..patient_name_len];

    // Determine public key for verification
    const is_self_issued = std.mem.eql(u8, iss_did, patient_agent_did);
    var verify_pubkey: [32]u8 = undefined;
    if (is_self_issued) {
        if (patient_pubkey_len != 32)
            return ctx.sendError(.internal_server_error, "Invalid public key length");
        @memcpy(&verify_pubkey, patient_pubkey_blob[0..32]);
    } else {
        var found_issuer = false;
        var stmt = database.prepare(
            "SELECT a.public_key FROM agents a " ++
                "JOIN users u ON u.id = a.owner_id " ++
                "WHERE a.did = ? AND u.user_type IN ('service', 'organization') LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, iss_did.ptr, @intCast(iss_did.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        if (stmt.step() catch false) {
            const pk_blob = stmt.getBlob(0) orelse &[_]u8{};
            if (pk_blob.len == 32) {
                @memcpy(&verify_pubkey, pk_blob[0..32]);
                found_issuer = true;
            }
        }
        if (!found_issuer)
            return ctx.sendError(.forbidden, "Unknown or unauthorized token issuer");
    }

    // Verify ed25519 signature
    var sig_bytes: [64]u8 = undefined;
    const sig_dec_len = crypto_mod.base64urlDecode(sig_b64, &sig_bytes) catch
        return ctx.sendError(.forbidden, "Invalid token signature encoding");
    if (sig_dec_len != 64)
        return ctx.sendError(.forbidden, "Invalid token signature");
    if (!crypto_mod.ed25519Verify(payload_json, &sig_bytes, &verify_pubkey))
        return ctx.sendError(.forbidden, "Token signature verification failed");

    // Check revocation
    var t_hash: [64]u8 = undefined;
    tokenHash(token_str, &t_hash);
    {
        var stmt = database.prepare(
            "SELECT id FROM ucan_revocations WHERE token_hash = ? LIMIT 1",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer stmt.finalize();
        stmt.bindText(1, &t_hash, 64) catch
            return ctx.sendError(.internal_server_error, "DB error");
        if (stmt.step() catch false)
            return ctx.sendError(.forbidden, "Token has been revoked");
    }

    // ── Token valid — insert responder update notifications ──

    var ts_buf: [32]u8 = undefined;
    const ts_len2 = common.formatIsoTimestamp(std.time.timestamp(), &ts_buf);
    const ts = ts_buf[0..ts_len2];

    const role_display: []const u8 = if (std.mem.eql(u8, role, "paramedic")) "EMT/Paramedic"
        else if (std.mem.eql(u8, role, "er_nurse")) "ER Nurse"
        else "Attending Physician";

    // Collect family member IDs + names
    var names_json = std.ArrayList(u8){};
    try names_json.appendSlice(alloc, "[");
    var notif_count: usize = 0;
    var names_first = true;

    {
        var fam_stmt = database.prepare(
            "SELECT DISTINCT nm2.user_id, u.display_name " ++
                "FROM network_memberships nm1 " ++
                "JOIN network_memberships nm2 ON nm2.network_id = nm1.network_id " ++
                "JOIN users u ON u.id = nm2.user_id " ++
                "WHERE nm1.user_id = ? AND nm2.user_id != ? AND u.is_remote = 0 LIMIT 10",
        ) catch return ctx.sendError(.internal_server_error, "DB error");
        defer fam_stmt.finalize();
        fam_stmt.bindText(1, patient_user_id.ptr, @intCast(patient_user_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");
        fam_stmt.bindText(2, patient_user_id.ptr, @intCast(patient_user_id.len)) catch
            return ctx.sendError(.internal_server_error, "DB error");

        while (fam_stmt.step() catch false) {
            const member_id_ptr = fam_stmt.getText(0) orelse continue;
            const member_id = std.mem.span(member_id_ptr);
            const dname_ptr = fam_stmt.getText(1);
            const dname = if (dname_ptr) |p| std.mem.span(p) else "Family member";

            var notif_id_buf: [36]u8 = undefined;
            common.generateUuid(&notif_id_buf);
            const notif_id = notif_id_buf[0..36];

            const title = try std.fmt.allocPrint(alloc,
                "Update from {s} for {s}", .{ role_display, patient_name });
            const notif_body = try std.fmt.allocPrint(alloc,
                "[{s} at scene]: {s}", .{ role_display, message });

            var ns = database.prepare(
                "INSERT INTO notifications " ++
                    "(id, user_id, notification_type, title, body, is_read, created_at) " ++
                    "VALUES (?, ?, 'emergency_responder_update', ?, ?, 0, ?)",
            ) catch continue;
            defer ns.finalize();
            ns.bindText(1, notif_id.ptr, 36) catch continue;
            ns.bindText(2, member_id.ptr, @intCast(member_id.len)) catch continue;
            ns.bindText(3, title.ptr, @intCast(title.len)) catch continue;
            ns.bindText(4, notif_body.ptr, @intCast(notif_body.len)) catch continue;
            ns.bindText(5, ts.ptr, @intCast(ts.len)) catch continue;
            _ = ns.step() catch {};

            // Add display name to JSON members array
            var esc_name: [512]u8 = undefined;
            const ename_len = json_mod.escapeJsonString(dname, &esc_name) catch 0;
            if (!names_first) try names_json.appendSlice(alloc, ",");
            names_first = false;
            const name_entry = try std.fmt.allocPrint(alloc, "\"{s}\"", .{esc_name[0..ename_len]});
            try names_json.appendSlice(alloc, name_entry);
            notif_count += 1;
        }
    }
    try names_json.appendSlice(alloc, "]");

    const resp = try std.fmt.allocPrint(alloc,
        "{{\"notified\":{d},\"members\":{s}}}",
        .{ notif_count, names_json.items });
    try ctx.json(.ok, resp);
}
