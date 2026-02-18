// federation.zig — Outbound HTTP client + ghost user DB ops for cross-pod federation.
//
// Provides C ABI exports that replace httpx calls in Python federation.py:
//   podos_peer_ping          — GET /api/pod from remote pod
//   podos_peer_connect       — ping + upsert PeerPod row in DB
//   podos_peer_query         — POST /api/pod/query (signed)
//   podos_ghost_get_or_create — idempotent ghost user lookup / insert
//   podos_ghost_cleanup_for_pod — remove ghosts for a disconnected pod
//
// HTTP calls use std.http.Client (synchronous). Callers manage concurrency.

const std = @import("std");
const db_mod = @import("db.zig");
const fed_auth = @import("federation_auth.zig");
const json_mod = @import("json.zig");
const Allocator = std.mem.Allocator;

// ═══════════════════════════════════════════
//  CONSTANTS
// ═══════════════════════════════════════════

pub const FEDERATION_TIMEOUT_MS: u64 = 15_000;
pub const MAX_RESPONSE_SIZE: usize = 512 * 1024; // 512 KiB for JSON responses

// ═══════════════════════════════════════════
//  SSRF PROTECTION
// ═══════════════════════════════════════════

/// SEC-01: Validate that a peer URL is safe for outbound requests.
/// Blocks:
///   - Private/loopback IPs (127.x, 10.x, 172.16-31.x, 192.168.x, ::1, fd00::/8)
///   - Non-HTTP(S) schemes
///   - Hostnames that look like internal services
pub fn validatePeerUrl(url: []const u8) bool {
    // Must be HTTP or HTTPS
    const no_scheme: []const u8 = if (std.mem.startsWith(u8, url, "https://"))
        url[8..]
    else if (std.mem.startsWith(u8, url, "http://"))
        url[7..]
    else
        return false; // non-HTTP scheme blocked

    // Extract hostname (before port or path)
    var hostname = no_scheme;
    if (std.mem.indexOfScalar(u8, hostname, '/')) |slash| {
        hostname = hostname[0..slash];
    }
    if (std.mem.indexOfScalar(u8, hostname, ':')) |colon| {
        hostname = hostname[0..colon];
    }

    if (hostname.len == 0) return false;

    // Block localhost variants
    if (std.mem.eql(u8, hostname, "localhost")) return false;
    if (std.mem.eql(u8, hostname, "[::]")) return false;
    if (std.mem.eql(u8, hostname, "[::1]")) return false;

    // Try to parse as IPv4 and check private ranges
    if (parseSimpleIpv4(hostname)) |octets| {
        // 127.0.0.0/8 (loopback)
        if (octets[0] == 127) return false;
        // 10.0.0.0/8
        if (octets[0] == 10) return false;
        // 172.16.0.0/12
        if (octets[0] == 172 and octets[1] >= 16 and octets[1] <= 31) return false;
        // 192.168.0.0/16
        if (octets[0] == 192 and octets[1] == 168) return false;
        // 0.0.0.0/8
        if (octets[0] == 0) return false;
        // 169.254.0.0/16 (link-local)
        if (octets[0] == 169 and octets[1] == 254) return false;
    }

    // Block common internal hostnames
    if (std.mem.startsWith(u8, hostname, "internal.")) return false;
    if (std.mem.startsWith(u8, hostname, "metadata.")) return false;
    if (std.mem.eql(u8, hostname, "metadata")) return false;

    return true;
}

fn parseSimpleIpv4(s: []const u8) ?[4]u8 {
    var octets: [4]u8 = undefined;
    var idx: usize = 0;
    var start: usize = 0;
    for (s, 0..) |ch, i| {
        if (ch == '.') {
            if (idx >= 3) return null;
            octets[idx] = std.fmt.parseInt(u8, s[start..i], 10) catch return null;
            idx += 1;
            start = i + 1;
        }
    }
    if (idx != 3) return null;
    octets[3] = std.fmt.parseInt(u8, s[start..], 10) catch return null;
    return octets;
}

// ═══════════════════════════════════════════
//  HTTP HELPERS
// ═══════════════════════════════════════════

const HttpError = error{
    NetworkError,
    BadStatus,
    ResponseTooLarge,
    ParseFailed,
    SsrfBlocked,
};

/// Do a GET request to `url`. Returns allocated response body on HTTP 200.
/// Caller frees the returned slice.
fn httpGet(url: []const u8, allocator: Allocator) HttpError![]u8 {
    // SEC-01: Block requests to private/internal IPs
    if (!validatePeerUrl(url)) return HttpError.SsrfBlocked;

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();

    const uri = std.Uri.parse(url) catch return HttpError.NetworkError;

    var req = client.request(.GET, uri, .{
        .redirect_behavior = .unhandled,
    }) catch return HttpError.NetworkError;
    defer req.deinit();

    req.sendBodiless() catch return HttpError.NetworkError;

    var redirect_buf: [8192]u8 = undefined;
    var response = req.receiveHead(&redirect_buf) catch return HttpError.NetworkError;

    if (response.head.status != .ok) return HttpError.BadStatus;

    var transfer_buf: [64]u8 = undefined;
    var reader = response.reader(&transfer_buf);
    return reader.allocRemaining(allocator, .limited(MAX_RESPONSE_SIZE)) catch HttpError.NetworkError;
}

/// Do a POST request with JSON body. Optionally attach signed federation headers.
/// Returns allocated response body slice on HTTP 200/201. Caller frees.
fn httpPost(
    url: []const u8,
    body_json: []const u8,
    extra_headers: []const std.http.Header,
    allocator: Allocator,
) HttpError![]u8 {
    // SEC-01: Block requests to private/internal IPs
    if (!validatePeerUrl(url)) return HttpError.SsrfBlocked;

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();

    const uri = std.Uri.parse(url) catch return HttpError.NetworkError;

    const ct_header = std.http.Header{ .name = "content-type", .value = "application/json" };
    var all_headers: std.ArrayList(std.http.Header) = .{};
    defer all_headers.deinit(allocator);
    all_headers.append(allocator, ct_header) catch return HttpError.NetworkError;
    for (extra_headers) |h| all_headers.append(allocator, h) catch return HttpError.NetworkError;

    var req = client.request(.POST, uri, .{
        .extra_headers = all_headers.items,
        .redirect_behavior = .unhandled,
    }) catch return HttpError.NetworkError;
    defer req.deinit();

    // Send body
    req.transfer_encoding = .{ .content_length = body_json.len };
    var bw = req.sendBodyUnflushed(&.{}) catch return HttpError.NetworkError;
    bw.writer.writeAll(body_json) catch return HttpError.NetworkError;
    bw.end() catch return HttpError.NetworkError;
    (req.connection orelse return HttpError.NetworkError).flush() catch return HttpError.NetworkError;

    // Receive response
    var redirect_buf: [8192]u8 = undefined;
    var response = req.receiveHead(&redirect_buf) catch return HttpError.NetworkError;

    const status_int: u10 = @intFromEnum(response.head.status);
    if (status_int < 200 or status_int >= 300) return HttpError.BadStatus;

    var transfer_buf: [64]u8 = undefined;
    var reader = response.reader(&transfer_buf);
    return reader.allocRemaining(allocator, .limited(MAX_RESPONSE_SIZE)) catch HttpError.NetworkError;
}

// ═══════════════════════════════════════════
//  PEER PING
// ═══════════════════════════════════════════

/// Ping a peer pod and return its info as a JSON string.
/// Returns null if unreachable.
pub fn pingPeer(peer_url: []const u8, allocator: Allocator) ?[]u8 {
    const url = std.fmt.allocPrint(allocator, "{s}/api/pod", .{std.mem.trimRight(u8, peer_url, "/")}) catch return null;
    defer allocator.free(url);

    const body = httpGet(url, allocator) catch return null;
    return body; // caller frees
}

// ═══════════════════════════════════════════
//  DB HELPERS FOR PEER PODS
// ═══════════════════════════════════════════

const PeerPodRow = struct {
    id: i64,
    name: []const u8,
    url: []const u8,
    status: []const u8,
    agent_count: i64,
};

fn upsertPeerPod(
    database: *db_mod.Database,
    pod_name: []const u8,
    pod_url: []const u8,
    agent_count: i64,
    allocator: Allocator,
) !void {
    _ = allocator;
    const c = db_mod.c;
    const now_ts = std.time.timestamp();

    // Check existing
    {
        const sql = "SELECT id FROM pods WHERE url = ? LIMIT 1";
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, pod_url.ptr, @intCast(pod_url.len));
        if (c.sqlite3_step(stmt.handle) == c.SQLITE_ROW) {
            const id = c.sqlite3_column_int64(stmt.handle, 0);
            // Update existing
            const usql = "UPDATE pods SET name=?, agent_count=?, status='active', last_seen_at=? WHERE id=?";
            var ustmt = try database.prepare(usql);
            defer ustmt.finalize();
            try ustmt.bindText(1, pod_name.ptr, @intCast(pod_name.len));
            try ustmt.bindInt64(2, agent_count);
            try ustmt.bindInt64(3, now_ts);
            try ustmt.bindInt64(4, id);
            _ = c.sqlite3_step(ustmt.handle);
            return;
        }
    }

    // Insert new
    const isql = "INSERT INTO pods (name, url, agent_count, status, last_seen_at) VALUES (?,?,?,'active',?) ON CONFLICT(url) DO UPDATE SET name=excluded.name, agent_count=excluded.agent_count, status='active', last_seen_at=excluded.last_seen_at";
    var istmt = try database.prepare(isql);
    defer istmt.finalize();
    try istmt.bindText(1, pod_name.ptr, @intCast(pod_name.len));
    try istmt.bindText(2, pod_url.ptr, @intCast(pod_url.len));
    try istmt.bindInt64(3, agent_count);
    try istmt.bindInt64(4, now_ts);
    _ = c.sqlite3_step(istmt.handle);
}

// ═══════════════════════════════════════════
//  GHOST USER OPERATIONS
// ═══════════════════════════════════════════

/// Idempotent: get existing ghost user by remote_did, or create one.
/// Returns 0 on success, -1 on error.
/// out_user_id: caller-provided buffer for the user UUID string.
pub fn getOrCreateGhostUser(
    database: *db_mod.Database,
    remote_username: []const u8,
    remote_did: []const u8,
    remote_pod_url: []const u8,
    out_user_id: []u8,
    allocator: Allocator,
) !usize {
    _ = allocator;
    const c = db_mod.c;

    // Look up by remote_did
    {
        const sql = "SELECT id FROM users WHERE remote_did = ? LIMIT 1";
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, remote_did.ptr, @intCast(remote_did.len));
        if (c.sqlite3_step(stmt.handle) == c.SQLITE_ROW) {
            const id_ptr = c.sqlite3_column_text(stmt.handle, 0);
            const id_len: usize = @intCast(c.sqlite3_column_bytes(stmt.handle, 0));
            if (id_len > out_user_id.len) return error.BufferTooSmall;
            @memcpy(out_user_id[0..id_len], id_ptr[0..id_len]);
            return id_len;
        }
    }

    // Generate a UUID for the new ghost user
    var uuid_bytes: [16]u8 = undefined;
    std.crypto.random.bytes(&uuid_bytes);
    var uuid_str: [36]u8 = undefined;
    formatUuid(&uuid_bytes, &uuid_str);

    // Build ghost username: "remote:username@hostname"
    var ghost_username_buf: [256]u8 = undefined;
    const hostname = extractHostname(remote_pod_url);
    const ghost_username = std.fmt.bufPrint(&ghost_username_buf, "remote:{s}@{s}", .{
        remote_username, hostname,
    }) catch return error.BufferTooSmall;

    // Insert ghost user
    const sql = "INSERT INTO users (id, username, display_name, user_type, is_remote, remote_did, remote_pod_url, is_demo, is_discoverable, created_at) VALUES (?,?,?,?,1,?,?,0,0,?) ON CONFLICT(username) DO NOTHING";
    var stmt = try database.prepare(sql);
    defer stmt.finalize();

    const now_ts = std.time.timestamp();
    try stmt.bindText(1, &uuid_str, 36);
    try stmt.bindText(2, ghost_username.ptr, @intCast(ghost_username.len));
    try stmt.bindText(3, remote_username.ptr, @intCast(remote_username.len));
    try stmt.bindText(4, "person", 6);
    try stmt.bindText(5, remote_did.ptr, @intCast(remote_did.len));
    try stmt.bindText(6, remote_pod_url.ptr, @intCast(remote_pod_url.len));
    try stmt.bindInt64(7, now_ts);

    const step_rc = c.sqlite3_step(stmt.handle);
    _ = step_rc;

    // Return the ID we used (or the existing one if conflict)
    const lookup_sql = "SELECT id FROM users WHERE remote_did = ? LIMIT 1";
    var ls = try database.prepare(lookup_sql);
    defer ls.finalize();
    try ls.bindText(1, remote_did.ptr, @intCast(remote_did.len));
    if (c.sqlite3_step(ls.handle) == c.SQLITE_ROW) {
        const id_ptr = c.sqlite3_column_text(ls.handle, 0);
        const id_len: usize = @intCast(c.sqlite3_column_bytes(ls.handle, 0));
        if (id_len > out_user_id.len) return error.BufferTooSmall;
        @memcpy(out_user_id[0..id_len], id_ptr[0..id_len]);
        return id_len;
    }

    return error.InsertFailed;
}

/// Remove all ghost users associated with a pod URL.
/// Also removes their connections and network memberships.
/// Returns count of removed ghosts, or -1 on error.
pub fn cleanupGhostsForPod(database: *db_mod.Database, pod_url: []const u8) !i64 {
    const c = db_mod.c;

    // Count ghosts first
    var count: i64 = 0;
    {
        const sql = "SELECT COUNT(*) FROM users WHERE is_remote=1 AND remote_pod_url=?";
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, pod_url.ptr, @intCast(pod_url.len));
        if (c.sqlite3_step(stmt.handle) == c.SQLITE_ROW) {
            count = c.sqlite3_column_int64(stmt.handle, 0);
        }
    }
    if (count == 0) return 0;

    // Delete connections first
    try database.exec("BEGIN");
    errdefer _ = database.exec("ROLLBACK") catch {};

    {
        const sql = "DELETE FROM connections WHERE user_id IN (SELECT id FROM users WHERE is_remote=1 AND remote_pod_url=?) OR connected_user_id IN (SELECT id FROM users WHERE is_remote=1 AND remote_pod_url=?)";
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, pod_url.ptr, @intCast(pod_url.len));
        try stmt.bindText(2, pod_url.ptr, @intCast(pod_url.len));
        _ = c.sqlite3_step(stmt.handle);
    }

    // Delete network memberships
    {
        const sql = "DELETE FROM network_memberships WHERE user_id IN (SELECT id FROM users WHERE is_remote=1 AND remote_pod_url=?)";
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, pod_url.ptr, @intCast(pod_url.len));
        _ = c.sqlite3_step(stmt.handle);
    }

    // Delete users
    {
        const sql = "DELETE FROM users WHERE is_remote=1 AND remote_pod_url=?";
        var stmt = try database.prepare(sql);
        defer stmt.finalize();
        try stmt.bindText(1, pod_url.ptr, @intCast(pod_url.len));
        _ = c.sqlite3_step(stmt.handle);
    }

    try database.exec("COMMIT");
    return count;
}

// ═══════════════════════════════════════════
//  REMOTE QUERY
// ═══════════════════════════════════════════

pub fn sendRemoteQuery(
    peer_url: []const u8,
    from_did: []const u8,
    to_username: []const u8,
    question: []const u8,
    private_key_seed: ?*const [32]u8,
    allocator: Allocator,
) ?[]u8 {
    const url = std.fmt.allocPrint(allocator, "{s}/api/pod/query", .{
        std.mem.trimRight(u8, peer_url, "/"),
    }) catch return null;
    defer allocator.free(url);

    // Build JSON payload with proper escaping of user-controlled fields
    var esc_did_buf: [256]u8 = undefined;
    var esc_user_buf: [256]u8 = undefined;
    var esc_q_buf: [4096]u8 = undefined;
    const esc_did_len = json_mod.escapeJsonString(from_did, &esc_did_buf) catch return null;
    const esc_user_len = json_mod.escapeJsonString(to_username, &esc_user_buf) catch return null;
    const esc_q_len = json_mod.escapeJsonString(question, &esc_q_buf) catch return null;

    const payload = std.fmt.allocPrint(allocator,
        "{{\"from_did\":\"{s}\",\"to_username\":\"{s}\",\"question\":\"{s}\"}}",
        .{ esc_did_buf[0..esc_did_len], esc_user_buf[0..esc_user_len], esc_q_buf[0..esc_q_len] }) catch return null;
    defer allocator.free(payload);

    // Build auth headers if private key provided
    var headers_buf: std.ArrayList(std.http.Header) = .{};
    defer headers_buf.deinit(allocator);

    var ts_val_buf: [32]u8 = undefined;
    var nonce_val_buf: [64]u8 = undefined;
    var sig_val_buf: [128]u8 = undefined;
    var method_val_buf: [16]u8 = undefined;
    var path_val_buf: [512]u8 = undefined;

    if (private_key_seed) |seed| {
        const signed = fed_auth.signRequest(
            payload,
            seed,
            "POST",
            "/api/pod/query",
            allocator,
        ) catch null;

        if (signed) |sh| {
            const ts_s = sh.getTimestamp();
            @memcpy(ts_val_buf[0..ts_s.len], ts_s);
            headers_buf.append(allocator, .{ .name = "X-TrustMesh-Timestamp", .value = ts_val_buf[0..ts_s.len] }) catch {};

            const n_s = sh.getNonce();
            @memcpy(nonce_val_buf[0..n_s.len], n_s);
            headers_buf.append(allocator, .{ .name = "X-TrustMesh-Nonce", .value = nonce_val_buf[0..n_s.len] }) catch {};

            const sig_s = sh.getSignature();
            @memcpy(sig_val_buf[0..sig_s.len], sig_s);
            headers_buf.append(allocator, .{ .name = "X-TrustMesh-Signature", .value = sig_val_buf[0..sig_s.len] }) catch {};
            headers_buf.append(allocator, .{ .name = "X-TrustMesh-Signature-Alg", .value = "ed25519" }) catch {};

            const m_s = sh.getMethod();
            @memcpy(method_val_buf[0..m_s.len], m_s);
            headers_buf.append(allocator, .{ .name = "X-TrustMesh-Method", .value = method_val_buf[0..m_s.len] }) catch {};

            const p_s = sh.getPath();
            @memcpy(path_val_buf[0..p_s.len], p_s);
            headers_buf.append(allocator, .{ .name = "X-TrustMesh-Path", .value = path_val_buf[0..p_s.len] }) catch {};
        }
    }

    return httpPost(url, payload, headers_buf.items, allocator) catch null;
}

// ═══════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════

fn formatUuid(bytes: *const [16]u8, out: *[36]u8) void {
    const hex = "0123456789abcdef";
    var pos: usize = 0;
    for (bytes, 0..) |b, i| {
        if (i == 4 or i == 6 or i == 8 or i == 10) {
            out[pos] = '-';
            pos += 1;
        }
        out[pos] = hex[b >> 4];
        out[pos + 1] = hex[b & 0xf];
        pos += 2;
    }
}

fn extractHostname(url: []const u8) []const u8 {
    const no_scheme = if (std.mem.startsWith(u8, url, "https://")) url[8..]
    else if (std.mem.startsWith(u8, url, "http://")) url[7..]
    else url;
    // Strip path
    if (std.mem.indexOfScalar(u8, no_scheme, '/')) |slash| {
        return no_scheme[0..slash];
    }
    return no_scheme;
}

// ═══════════════════════════════════════════
//  C ABI EXPORTS
// ═══════════════════════════════════════════

const ffi_alloc = std.heap.page_allocator;

/// Ping a peer pod. Writes JSON response to out_json.
/// Returns bytes written, or -1 if unreachable.
export fn podos_peer_ping(
    peer_url_ptr: [*]const u8,
    peer_url_len: usize,
    out_json: [*]u8,
    out_cap: usize,
    out_len: *usize,
) callconv(.c) i32 {
    const peer_url = peer_url_ptr[0..peer_url_len];
    const body = pingPeer(peer_url, ffi_alloc) orelse return -1;
    defer ffi_alloc.free(body);

    const copy_len = @min(body.len, out_cap);
    @memcpy(out_json[0..copy_len], body[0..copy_len]);
    out_len.* = copy_len;
    return @intCast(copy_len);
}

/// Ping peer and upsert PeerPod row in DB.
/// db_handle: pointer returned by podos_db_open.
/// Returns 0 on success, -1 on error.
export fn podos_peer_connect(
    db_handle: ?*anyopaque,
    peer_url_ptr: [*]const u8,
    peer_url_len: usize,
) callconv(.c) i32 {
    const database: *db_mod.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const peer_url = peer_url_ptr[0..peer_url_len];

    var arena = std.heap.ArenaAllocator.init(ffi_alloc);
    defer arena.deinit();
    const alloc = arena.allocator();

    // Ping
    const pod_json = pingPeer(peer_url, alloc) orelse {
        // Mark as unreachable in DB
        const sql = "UPDATE pods SET status='unreachable' WHERE url=?";
        var stmt = database.prepare(sql) catch return -1;
        defer stmt.finalize();
        stmt.bindText(1, peer_url.ptr, @intCast(peer_url.len)) catch {};
        const c = db_mod.c;
        _ = c.sqlite3_step(stmt.handle);
        return -1;
    };
    defer alloc.free(pod_json);

    // Parse pod name and agent count
    const PodInfo = struct {
        pod_name: ?[]const u8 = null,
        agent_count: ?i64 = null,
    };
    const parsed = std.json.parseFromSlice(PodInfo, alloc, pod_json, .{ .ignore_unknown_fields = true }) catch
        return -1;
    defer parsed.deinit();

    const pod_name = parsed.value.pod_name orelse "Unknown Pod";
    const agent_count = parsed.value.agent_count orelse 0;

    upsertPeerPod(database, pod_name, peer_url, agent_count, alloc) catch return -1;
    return 0;
}

/// Send a signed query to a peer pod. Writes JSON response to out_json.
/// private_key: 32-byte Ed25519 seed (NULL to send unsigned).
/// Returns bytes written, or -1 on error.
export fn podos_peer_query(
    peer_url_ptr: [*]const u8,
    peer_url_len: usize,
    from_did_ptr: [*]const u8,
    from_did_len: usize,
    to_username_ptr: [*]const u8,
    to_username_len: usize,
    question_ptr: [*]const u8,
    question_len: usize,
    private_key: ?[*]const u8, // 32 bytes or NULL
    out_json: [*]u8,
    out_cap: usize,
    out_len: *usize,
) callconv(.c) i32 {
    const peer_url = peer_url_ptr[0..peer_url_len];
    const from_did = from_did_ptr[0..from_did_len];
    const to_username = to_username_ptr[0..to_username_len];
    const question = question_ptr[0..question_len];

    var arena = std.heap.ArenaAllocator.init(ffi_alloc);
    defer arena.deinit();
    const alloc = arena.allocator();

    const seed: ?*const [32]u8 = if (private_key) |pk| @ptrCast(pk) else null;

    const response = sendRemoteQuery(peer_url, from_did, to_username, question, seed, alloc) orelse return -1;
    defer alloc.free(response);

    const copy_len = @min(response.len, out_cap);
    @memcpy(out_json[0..copy_len], response[0..copy_len]);
    out_len.* = copy_len;
    return @intCast(copy_len);
}

/// Get or create a ghost user. Writes user_id (UUID string) to out_user_id.
/// Returns user_id length, or -1 on error.
export fn podos_ghost_get_or_create(
    db_handle: ?*anyopaque,
    username_ptr: [*]const u8,
    username_len: usize,
    did_ptr: [*]const u8,
    did_len: usize,
    pod_url_ptr: [*]const u8,
    pod_url_len: usize,
    out_user_id: [*]u8,
    out_cap: usize,
) callconv(.c) i32 {
    const database: *db_mod.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const username = username_ptr[0..username_len];
    const did = did_ptr[0..did_len];
    const pod_url = pod_url_ptr[0..pod_url_len];

    var arena = std.heap.ArenaAllocator.init(ffi_alloc);
    defer arena.deinit();
    const alloc = arena.allocator();

    const id_len = getOrCreateGhostUser(database, username, did, pod_url, out_user_id[0..out_cap], alloc) catch return -1;
    return @intCast(id_len);
}

/// Remove all ghost users for a pod. Returns count removed, or -1 on error.
export fn podos_ghost_cleanup_for_pod(
    db_handle: ?*anyopaque,
    pod_url_ptr: [*]const u8,
    pod_url_len: usize,
) callconv(.c) i32 {
    const database: *db_mod.Database = @ptrCast(@alignCast(db_handle orelse return -1));
    const pod_url = pod_url_ptr[0..pod_url_len];

    const count = cleanupGhostsForPod(database, pod_url) catch return -1;
    return @intCast(count);
}
