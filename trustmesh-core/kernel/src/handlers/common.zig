// handlers/common.zig — Shared utilities for all Zig native HTTP handlers.
//
// Extracts duplicated code from auth.zig, credentials.zig, memory.zig, onboard.zig:
//   - requireAuth: session cookie → user_id
//   - buildFingerprint: SHA-256(User-Agent|IP) for session binding
//   - generateUuid: UUID v4 generation
//   - formatIsoTimestamp: epoch seconds → ISO 8601 string
//   - extractPathParam: pull a segment from URL path after a prefix
//   - getQueryParam: extract query parameter by name

const std = @import("std");
const podos = @import("podos");
const http = @import("../http.zig");

const Sha256 = std.crypto.hash.sha2.Sha256;

// ── Module-level state (set once by server_main) ──
var _session_store: ?*podos.session.SessionStore = null;

pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

// ═══════════════════════════════════════════
//  AUTH
// ═══════════════════════════════════════════

/// Validate session cookie and return user_id copied into `out`.
/// On failure, sends an error response and returns null.
pub fn requireAuth(ctx: *http.RequestContext, out: []u8) ?[]const u8 {
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

/// SHA-256 fingerprint of User-Agent + client IP (matches Python _compute_fingerprint).
pub fn buildFingerprint(ctx: *const http.RequestContext, buf: *[64]u8) []const u8 {
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

// ═══════════════════════════════════════════
//  UUID
// ═══════════════════════════════════════════

/// Generate a UUID v4 string (36 chars: 8-4-4-4-12).
pub fn generateUuid(buf: *[36]u8) void {
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
//  TIMESTAMP
// ═══════════════════════════════════════════

/// Format epoch seconds as ISO 8601 (YYYY-MM-DDTHH:MM:SS). Returns byte count written.
pub fn formatIsoTimestamp(epoch_secs: i64, buf: *[32]u8) usize {
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

// ═══════════════════════════════════════════
//  PATH / QUERY HELPERS
// ═══════════════════════════════════════════

/// Extract the segment after `prefix` in a URL path.
/// Returns null if path doesn't start with prefix or has no remaining content.
pub fn extractPathParam(path: []const u8, prefix: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, path, prefix) or path.len <= prefix.len) {
        return null;
    }
    const param = path[prefix.len..];
    // Don't return empty or absurdly long params
    if (param.len == 0 or param.len > 128) return null;
    return param;
}

/// Extract a query parameter value from a URL query string.
pub fn getQueryParam(query: []const u8, name: []const u8) ?[]const u8 {
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

/// SHA-256 hex hash of content. Writes 64 hex characters to `out`.
pub fn sha256Hex(content: []const u8, out: *[64]u8) void {
    var digest: [32]u8 = undefined;
    Sha256.hash(content, &digest, .{});
    const hex_chars = "0123456789abcdef";
    for (digest, 0..) |byte, i| {
        out[i * 2] = hex_chars[byte >> 4];
        out[i * 2 + 1] = hex_chars[byte & 0x0f];
    }
}
