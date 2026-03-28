// handlers/channels.zig — ZeroClaw/NullClaw channel bridge.
//
// Authenticates Bearer tm_<token> channel tokens, runs pre-flight sensitivity
// detection, rate-limits, then proxies to Python for the LLM call.
// Python never sees the raw token — only the injected X-Channel-Owner-Id header.
//
// Routes:
//   POST /api/channels/message   → handleChannelMessage
//   POST /api/channels/webhook   → handleChannelWebhook  (ZeroClaw wire format)

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");
const router_mod = @import("../router.zig");
const common = @import("common.zig");
const channel_tokens = @import("channel_tokens.zig");
const sensitivity = podos.sensitivity;

// ── Module-level state ──
var _db: ?*podos.db.Database = null;
var _rate_limiter: ?*podos.rate_limit.RateLimiter = null;

pub fn setDatabase(d: *podos.db.Database) void {
    _db = d;
}

pub fn setRateLimiter(rl: *podos.rate_limit.RateLimiter) void {
    _rate_limiter = rl;
}

pub fn registerRoutes() void {
    router_mod.addExact(.POST, "/api/channels/message", handleChannelMessage);
    router_mod.addExact(.POST, "/api/channels/webhook", handleChannelWebhook);
}

// ═══════════════════════════════════════════
//  BEARER TOKEN EXTRACTION
// ═══════════════════════════════════════════

/// Extract raw token from "Authorization: Bearer tm_..." header.
/// Returns null if header is missing or has wrong format.
fn extractBearerToken(ctx: *const http.RequestContext) ?[]const u8 {
    const auth_header = ctx.getHeader("authorization") orelse return null;
    const bearer_prefix = "Bearer ";
    if (!std.mem.startsWith(u8, auth_header, bearer_prefix)) return null;
    const token = auth_header[bearer_prefix.len..];
    if (token.len < 4 or !std.mem.startsWith(u8, token, "tm_")) return null;
    return token;
}

// ═══════════════════════════════════════════
//  SHARED CHANNEL AUTH + PREFLIGHT
// ═══════════════════════════════════════════

const ChannelContext = struct {
    owner_id: []const u8,
    sensitivity_str: []const u8,  // "sensitive" or "standard"
    rel_type: []const u8,
};

/// Authenticate Bearer token, run pre-flight sensitivity, rate limit.
/// On failure, sends error response and returns null.
fn authenticateChannel(
    ctx: *http.RequestContext,
    message_text: []const u8,
    owner_buf: *channel_tokens.ValidateResult,
) ?ChannelContext {
    const database = _db orelse {
        ctx.sendError(.service_unavailable, "DB not ready") catch {};
        return null;
    };

    // 1. Extract token
    const raw_token = extractBearerToken(ctx) orelse {
        ctx.sendError(.unauthorized, "Missing or invalid Bearer token") catch {};
        return null;
    };

    // 2. Hash + validate
    var hash_buf: [64]u8 = undefined;
    common.sha256Hex(raw_token, &hash_buf);
    const token_hash = hash_buf[0..64];

    channel_tokens.validateToken(database, token_hash, owner_buf) catch {
        ctx.sendError(.unauthorized, "Invalid or revoked channel token") catch {};
        return null;
    };

    const owner_id = owner_buf.getOwnerId();
    const rel_type = owner_buf.getRelationshipType();

    // 3. Pre-flight sensitivity
    const is_sensitive = sensitivity.preflightSensitivity(message_text, if (rel_type.len > 0) rel_type else null);
    const sensitivity_str: []const u8 = if (is_sensitive) "sensitive" else "standard";

    // 4. Rate limit (use owner querying themselves → private trust)
    if (_rate_limiter) |rl| {
        const check = rl.checkQuery(owner_id, owner_id, false); // private = not public
        if (!check.allowed) {
            ctx.sendError(.too_many_requests, check.getMessage()) catch {};
            return null;
        }
    }

    return ChannelContext{
        .owner_id = owner_id,
        .sensitivity_str = sensitivity_str,
        .rel_type = rel_type,
    };
}

// ═══════════════════════════════════════════
//  HANDLER: POST /api/channels/message
// ═══════════════════════════════════════════

fn handleChannelMessage(ctx: *http.RequestContext) !void {
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    if (ctx.body.len > 128 * 1024) return ctx.sendError(.payload_too_large, "Body too large");

    // Extract message text for sensitivity (lightweight: find "message" key)
    const message_text = extractJsonField(ctx.body, "message");

    var owner_buf: channel_tokens.ValidateResult = undefined;
    const chan_ctx = authenticateChannel(ctx, message_text, &owner_buf) orelse return;

    // Proxy to Python with injected context headers
    const extra_headers = [_]std.http.Header{
        .{ .name = "x-channel-owner-id", .value = chan_ctx.owner_id },
        .{ .name = "x-preflight-sensitivity", .value = chan_ctx.sensitivity_str },
        .{ .name = "x-channel-relationship-type", .value = chan_ctx.rel_type },
    };
    try http.proxyFromHandlerWithHeaders(ctx, &extra_headers);
}

// ═══════════════════════════════════════════
//  HANDLER: POST /api/channels/webhook
// ═══════════════════════════════════════════

fn handleChannelWebhook(ctx: *http.RequestContext) !void {
    if (ctx.body.len == 0) return ctx.sendError(.bad_request, "Request body required");
    if (ctx.body.len > 128 * 1024) return ctx.sendError(.payload_too_large, "Body too large");

    // ZeroClaw wire format: {"message":"..."} — same extraction
    const message_text = extractJsonField(ctx.body, "message");

    var owner_buf: channel_tokens.ValidateResult = undefined;
    const chan_ctx = authenticateChannel(ctx, message_text, &owner_buf) orelse return;

    const extra_headers = [_]std.http.Header{
        .{ .name = "x-channel-owner-id", .value = chan_ctx.owner_id },
        .{ .name = "x-preflight-sensitivity", .value = chan_ctx.sensitivity_str },
        .{ .name = "x-channel-relationship-type", .value = chan_ctx.rel_type },
    };
    try http.proxyFromHandlerWithHeaders(ctx, &extra_headers);
}

// ═══════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════

/// Lightweight JSON field extractor — finds the value of a string key.
/// Returns empty slice if not found. No allocation, no full parse.
fn extractJsonField(json: []const u8, key: []const u8) []const u8 {
    // Build search needle: `"key":"`
    var needle_buf: [128]u8 = undefined;
    if (key.len + 5 > needle_buf.len) return "";
    needle_buf[0] = '"';
    @memcpy(needle_buf[1..][0..key.len], key);
    needle_buf[1 + key.len] = '"';
    needle_buf[1 + key.len + 1] = ':';
    needle_buf[1 + key.len + 2] = '"';
    const needle = needle_buf[0..1 + key.len + 3];

    const start_idx = std.mem.indexOf(u8, json, needle) orelse return "";
    const val_start = start_idx + needle.len;
    if (val_start >= json.len) return "";

    // Find closing quote (simple: ignore escaped quotes for this lightweight check)
    var pos = val_start;
    while (pos < json.len and json[pos] != '"') : (pos += 1) {}

    return json[val_start..pos];
}
