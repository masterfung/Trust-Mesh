// http.zig — Zig HTTP server layer for PodOS.
//
// Architecture:
//   Client → :8000 (this server, std.http.Server)
//              ├── Zig native handlers (auth, etc. as they're migrated)
//              └── Proxy → Python FastAPI on :9000
//
// Uses std.http.Server from Zig 0.15.2 with std.Io.Reader/Writer.

const std = @import("std");
const http = std.http;
const net = std.net;
const podos = @import("podos");
const router = @import("router.zig");

// ═══════════════════════════════════════════
//  SESSION STORE (set by server_main for proxy auth)
// ═══════════════════════════════════════════

var _session_store: ?*podos.session.SessionStore = null;

/// Called by server_main to give the proxy layer access to sessions.
pub fn setSessionStore(store: *podos.session.SessionStore) void {
    _session_store = store;
}

const Sha256 = std.crypto.hash.sha2.Sha256;

/// Compute session fingerprint matching Python's _compute_fingerprint().
fn computeFingerprint(ctx_headers: []const u8, buf: *[64]u8) []const u8 {
    // Extract User-Agent and client IP from raw headers
    var ua: []const u8 = "";
    var it = http.HeaderIterator.init(ctx_headers);
    while (it.next()) |hdr| {
        if (std.ascii.eqlIgnoreCase(hdr.name, "user-agent")) {
            ua = hdr.value;
            break;
        }
    }
    // IP: always "unknown" for now (socket peer not available in proxy path)
    const ip = "unknown";

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

/// Try to validate the session cookie and return the user_id.
fn validateProxySession(head_buf: []const u8) ?[]const u8 {
    const store = _session_store orelse return null;

    // Extract cookie header
    var cookie_val: ?[]const u8 = null;
    var it = http.HeaderIterator.init(head_buf);
    while (it.next()) |hdr| {
        if (std.ascii.eqlIgnoreCase(hdr.name, "cookie")) {
            cookie_val = hdr.value;
            break;
        }
    }
    const cookies = cookie_val orelse return null;

    // Find trustmesh_session cookie
    const token = parseCookieValue(cookies, "trustmesh_session") orelse return null;

    // Compute fingerprint
    var fp_buf: [64]u8 = undefined;
    const fingerprint = computeFingerprint(head_buf, &fp_buf);

    // Validate session
    return store.validateSession(token, fingerprint);
}

// ═══════════════════════════════════════════
//  CONFIG
// ═══════════════════════════════════════════

pub const Config = struct {
    listen_port: u16 = 8000,
    python_port: u16 = 9000,
    python_host: []const u8 = "127.0.0.1",
};

// Allowed CORS origins: localhost ports 3000-3100 + any 8001-8016 (multi-pod)
const CORS_PORT_RANGES = [_][2]u16{ .{ 3000, 3100 }, .{ 8001, 8016 } };

// Security response headers added to every outgoing response.
const SECURITY_HEADERS = [_]http.Header{
    .{ .name = "X-Content-Type-Options", .value = "nosniff" },
    .{ .name = "X-Frame-Options", .value = "DENY" },
    .{ .name = "Strict-Transport-Security", .value = "max-age=31536000; includeSubDomains" },
    .{ .name = "Referrer-Policy", .value = "strict-origin-when-cross-origin" },
    .{ .name = "Permissions-Policy", .value = "geolocation=(), microphone=(), camera=()" },
};

// ═══════════════════════════════════════════
//  REQUEST CONTEXT
// ═══════════════════════════════════════════

/// Passed to every handler. Wraps parsed request data for convenient access.
pub const RequestContext = struct {
    allocator: std.mem.Allocator,
    config: *const Config,

    // Parsed request
    method: http.Method,
    path: []const u8,
    query: []const u8,
    body: []const u8,
    /// Raw head buffer for iterating headers
    head_buffer: []const u8,

    // Response state — handler builds headers, then calls respond()
    _request: *http.Server.Request,
    _responded: bool = false,

    /// Find a header value by name (case-insensitive scan).
    pub fn getHeader(self: *const RequestContext, name: []const u8) ?[]const u8 {
        var it = http.HeaderIterator.init(self.head_buffer);
        while (it.next()) |hdr| {
            if (std.ascii.eqlIgnoreCase(hdr.name, name)) return hdr.value;
        }
        return null;
    }

    /// Extract cookie value by name from the Cookie header.
    pub fn getCookie(self: *const RequestContext, name: []const u8) ?[]const u8 {
        const cookie_header = self.getHeader("cookie") orelse return null;
        return parseCookieValue(cookie_header, name);
    }

    /// Build extra_headers array from security headers + CORS + custom headers.
    fn buildResponseHeaders(
        self: *const RequestContext,
        content_type: []const u8,
        custom: []const http.Header,
    ) ![]const http.Header {
        var headers: std.ArrayList(http.Header) = .{};
        errdefer headers.deinit(self.allocator);

        // Content-Type
        try headers.append(self.allocator, .{ .name = "content-type", .value = content_type });

        // Security headers
        for (&SECURITY_HEADERS) |sh| {
            try headers.append(self.allocator, sh);
        }

        // CORS
        if (self.getHeader("origin")) |origin| {
            if (isAllowedOrigin(origin)) {
                try headers.append(self.allocator, .{ .name = "access-control-allow-origin", .value = origin });
                try headers.append(self.allocator, .{ .name = "access-control-allow-credentials", .value = "true" });
                try headers.append(self.allocator, .{ .name = "access-control-allow-methods", .value = "GET,POST,PUT,DELETE,PATCH,OPTIONS" });
                try headers.append(self.allocator, .{
                    .name = "access-control-allow-headers",
                    .value = "Content-Type,Authorization,X-CSRF-Token,X-Pool-Sync-Secret,X-TrustMesh-Timestamp,X-TrustMesh-Nonce,X-TrustMesh-Signature,X-TrustMesh-Signature-Alg,X-TrustMesh-Method,X-TrustMesh-Path",
                });
                try headers.append(self.allocator, .{ .name = "vary", .value = "Origin" });
            }
        }

        // Custom headers from handler
        for (custom) |ch| try headers.append(self.allocator, ch);

        return try headers.toOwnedSlice(self.allocator);
    }

    /// Send a JSON response.
    pub fn json(self: *RequestContext, status: http.Status, body_bytes: []const u8) !void {
        const hdrs = try self.buildResponseHeaders("application/json", &.{});
        try self._request.respond(body_bytes, .{
            .status = status,
            .extra_headers = hdrs,
        });
        self._responded = true;
    }

    /// Send a JSON response with extra custom headers (e.g., Set-Cookie).
    pub fn jsonWithHeaders(self: *RequestContext, status: http.Status, body_bytes: []const u8, extra: []const http.Header) !void {
        const hdrs = try self.buildResponseHeaders("application/json", extra);
        try self._request.respond(body_bytes, .{
            .status = status,
            .extra_headers = hdrs,
        });
        self._responded = true;
    }

    /// Write a simple JSON error {"error":"msg"} with proper escaping.
    pub fn sendError(self: *RequestContext, status: http.Status, msg: []const u8) !void {
        var esc_buf: [256]u8 = undefined;
        var buf: [512]u8 = undefined;
        const esc_len = escapeJsonStr(msg, &esc_buf);
        const body_bytes = std.fmt.bufPrint(&buf, "{{\"error\":\"{s}\"}}", .{esc_buf[0..esc_len]}) catch "{\"error\":\"internal\"}";
        try self.json(status, body_bytes);
    }

    /// Build a Set-Cookie header value string.
    /// Adds `Secure` flag unless TRUSTMESH_DEV_MODE is set.
    pub fn buildSetCookieHeader(self: *RequestContext, name: []const u8, value: []const u8, opts: CookieOpts) ![]const u8 {
        const secure_suffix = if (isDevMode()) @as([]const u8, "") else "; Secure";
        const same_site_str = if (opts.same_site == .strict) @as([]const u8, "Strict") else "Lax";
        if (opts.max_age) |age| {
            return std.fmt.allocPrint(self.allocator, "{s}={s}; HttpOnly; SameSite={s}; Path=/; Max-Age={d}{s}", .{
                name, value, same_site_str, age, secure_suffix,
            });
        }
        return std.fmt.allocPrint(self.allocator, "{s}={s}; HttpOnly; SameSite={s}; Path=/{s}", .{
            name, value, same_site_str, secure_suffix,
        });
    }
};

pub const CookieOpts = struct {
    http_only: bool = true,
    same_site: enum { lax, strict } = .lax,
    max_age: ?u32 = null,
};

// ═══════════════════════════════════════════
//  COOKIE PARSING
// ═══════════════════════════════════════════

pub fn parseCookieValue(cookie_header: []const u8, name: []const u8) ?[]const u8 {
    var it = std.mem.splitScalar(u8, cookie_header, ';');
    while (it.next()) |raw_pair| {
        const pair = std.mem.trim(u8, raw_pair, " ");
        const eq = std.mem.indexOfScalar(u8, pair, '=') orelse continue;
        const k = pair[0..eq];
        if (std.mem.eql(u8, k, name)) return pair[eq + 1 ..];
    }
    return null;
}

// ═══════════════════════════════════════════
//  ENVIRONMENT HELPERS
// ═══════════════════════════════════════════

/// Check if TRUSTMESH_DEV_MODE env var is set (for disabling Secure cookie flag, etc.)
var _dev_mode_checked: bool = false;
var _dev_mode: bool = false;

pub fn isDevMode() bool {
    if (!_dev_mode_checked) {
        // getEnvVarOwned returns error if not found
        const val = std.process.getEnvVarOwned(std.heap.page_allocator, "TRUSTMESH_DEV_MODE") catch {
            _dev_mode = false;
            _dev_mode_checked = true;
            return false;
        };
        std.heap.page_allocator.free(val);
        _dev_mode = true;
        _dev_mode_checked = true;
    }
    return _dev_mode;
}

/// SEC-05: Get client IP address. Only trusts X-Forwarded-For / X-Real-IP
/// when TRUSTMESH_TRUSTED_PROXY env var is set (indicating a reverse proxy is in use).
var _trusted_proxy_checked: bool = false;
var _trust_proxy_headers: bool = false;

fn checkTrustedProxy() bool {
    if (!_trusted_proxy_checked) {
        const val = std.process.getEnvVarOwned(std.heap.page_allocator, "TRUSTMESH_TRUSTED_PROXY") catch {
            _trust_proxy_headers = false;
            _trusted_proxy_checked = true;
            return false;
        };
        std.heap.page_allocator.free(val);
        _trust_proxy_headers = true;
        _trusted_proxy_checked = true;
    }
    return _trust_proxy_headers;
}

pub fn getClientIp(ctx: *const RequestContext) []const u8 {
    if (checkTrustedProxy()) {
        // Only trust forwarded headers when behind a configured reverse proxy
        if (ctx.getHeader("x-real-ip")) |ip| return ip;
        if (ctx.getHeader("x-forwarded-for")) |xff| {
            // Take the first IP (client IP) from the chain
            if (std.mem.indexOfScalar(u8, xff, ',')) |comma| {
                return std.mem.trim(u8, xff[0..comma], " ");
            }
            return xff;
        }
    }
    return "unknown"; // socket peer address not easily accessible from std.http.Server
}

// ═══════════════════════════════════════════
//  JSON STRING ESCAPE (inline for error messages)
// ═══════════════════════════════════════════

/// Minimal JSON string escaper for error messages. Returns bytes written.
fn escapeJsonStr(input: []const u8, out: []u8) usize {
    var pos: usize = 0;
    for (input) |ch| {
        if (pos + 6 > out.len) break; // conservative
        switch (ch) {
            '"' => {
                out[pos] = '\\';
                out[pos + 1] = '"';
                pos += 2;
            },
            '\\' => {
                out[pos] = '\\';
                out[pos + 1] = '\\';
                pos += 2;
            },
            '\n' => {
                out[pos] = '\\';
                out[pos + 1] = 'n';
                pos += 2;
            },
            '\r' => {
                out[pos] = '\\';
                out[pos + 1] = 'r';
                pos += 2;
            },
            else => {
                if (ch < 0x20) {
                    const hex = "0123456789abcdef";
                    out[pos] = '\\';
                    out[pos + 1] = 'u';
                    out[pos + 2] = '0';
                    out[pos + 3] = '0';
                    out[pos + 4] = hex[ch >> 4];
                    out[pos + 5] = hex[ch & 0x0f];
                    pos += 6;
                } else {
                    out[pos] = ch;
                    pos += 1;
                }
            },
        }
    }
    return pos;
}

// ═══════════════════════════════════════════
//  CORS
// ═══════════════════════════════════════════

fn isAllowedOrigin(origin: []const u8) bool {
    const prefixes = [_][]const u8{
        "http://localhost:",
        "https://localhost:",
        "http://127.0.0.1:",
        "https://127.0.0.1:",
    };
    for (prefixes) |prefix| {
        if (!std.mem.startsWith(u8, origin, prefix)) continue;
        const port_str = origin[prefix.len..];
        const port = std.fmt.parseInt(u16, port_str, 10) catch continue;
        for (CORS_PORT_RANGES) |range| {
            if (port >= range[0] and port <= range[1]) return true;
        }
    }
    return false;
}

// ═══════════════════════════════════════════
//  TARGET PARSING
// ═══════════════════════════════════════════

fn parseTarget(target: []const u8) struct { path: []const u8, query: []const u8 } {
    if (std.mem.indexOfScalar(u8, target, '?')) |qi| {
        return .{ .path = target[0..qi], .query = target[qi + 1 ..] };
    }
    return .{ .path = target, .query = "" };
}

// ═══════════════════════════════════════════
//  PROXY TO PYTHON
// ═══════════════════════════════════════════

fn buildProxyUrl(
    target_path: []const u8,
    query: []const u8,
    config: *const Config,
    allocator: std.mem.Allocator,
) ![]u8 {
    if (query.len > 0)
        return std.fmt.allocPrint(allocator, "http://{s}:{d}{s}?{s}", .{
            config.python_host, config.python_port, target_path, query,
        })
    else
        return std.fmt.allocPrint(allocator, "http://{s}:{d}{s}", .{
            config.python_host, config.python_port, target_path,
        });
}

/// Forward header names we proxy from client to Python.
/// SEC-09: Don't forward Host (set explicitly to 127.0.0.1).
/// Don't forward X-Real-IP / X-Forwarded-For to avoid spoofing the Python backend.
const PROXY_FORWARD_HEADERS = [_][]const u8{
    "content-type",       "accept",              "authorization",
    "cookie",             "x-csrf-token",         "x-pool-sync-secret",
    "x-trustmesh-timestamp", "x-trustmesh-nonce",  "x-trustmesh-signature",
    "x-trustmesh-signature-alg", "x-trustmesh-method", "x-trustmesh-path",
    "user-agent",         "accept-encoding",      "accept-language",
    "cache-control",
};

fn proxyToPython(
    server_request: *http.Server.Request,
    body: []const u8,
    target_path: []const u8,
    query: []const u8,
    origin: ?[]const u8,
    head_buf_copy: []const u8,
    config: *const Config,
    allocator: std.mem.Allocator,
) !void {
    const url_str = try buildProxyUrl(target_path, query, config, allocator);
    defer allocator.free(url_str);
    const uri = try std.Uri.parse(url_str);

    // Collect forwarded headers from the saved head buffer copy
    var fwd_headers: std.ArrayList(http.Header) = .{};
    defer fwd_headers.deinit(allocator);

    var req_it = http.HeaderIterator.init(head_buf_copy);
    while (req_it.next()) |hdr| {
        for (PROXY_FORWARD_HEADERS) |fh| {
            if (std.ascii.eqlIgnoreCase(hdr.name, fh)) {
                try fwd_headers.append(allocator, .{ .name = hdr.name, .value = hdr.value });
                break;
            }
        }
    }

    // ── Zig-verified session → inject X-Verified-User-Id for Python ──
    // This is the core of "Zig owns sessions, Python trusts the header".
    // Python on :9000 is localhost-only, so this header can't be spoofed externally.
    if (validateProxySession(head_buf_copy)) |user_id| {
        const uid_dup = try allocator.dupe(u8, user_id);
        try fwd_headers.append(allocator, .{ .name = "x-verified-user-id", .value = uid_dup });
    }

    // Make proxy request via std.http.Client (0.15.2 API)
    var client = http.Client{ .allocator = allocator };
    defer client.deinit();

    var proxy_req = try client.request(server_request.head.method, uri, .{
        .extra_headers = fwd_headers.items,
        .redirect_behavior = .unhandled,
    });
    defer proxy_req.deinit();

    // Send body or bodiless
    if (body.len > 0) {
        proxy_req.transfer_encoding = .{ .content_length = body.len };
        var bw = try proxy_req.sendBodyUnflushed(&.{});
        try bw.writer.writeAll(body);
        try bw.end();
        try proxy_req.connection.?.flush();
    } else {
        try proxy_req.sendBodiless();
    }

    // Receive response head
    var redirect_buf: [8192]u8 = undefined;
    var response = try proxy_req.receiveHead(&redirect_buf);

    // Build response headers
    var resp_headers: std.ArrayList(http.Header) = .{};
    defer resp_headers.deinit(allocator);

    // Forward response headers from Python (skip hop-by-hop + SEC-09: strip internal headers)
    // IMPORTANT: Also skip content-length — Zig's respond() adds it automatically from the body
    // length. Forwarding Python's content-length creates duplicate headers which Chrome rejects
    // with ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_LENGTH.
    // Skip security headers that Zig adds in SECURITY_HEADERS to avoid duplicates.
    var resp_it = response.head.iterateHeaders();
    while (resp_it.next()) |hdr| {
        if (std.ascii.eqlIgnoreCase(hdr.name, "transfer-encoding")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "content-length")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "connection")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "server")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "x-powered-by")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "x-process-time")) continue;
        // Skip security headers that Zig adds itself (prevents duplicates)
        if (std.ascii.eqlIgnoreCase(hdr.name, "x-content-type-options")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "x-frame-options")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "strict-transport-security")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "referrer-policy")) continue;
        if (std.ascii.eqlIgnoreCase(hdr.name, "permissions-policy")) continue;
        // Dupe header strings into arena since response reader invalidates them
        const name_dup = try allocator.dupe(u8, hdr.name);
        const val_dup = try allocator.dupe(u8, hdr.value);
        try resp_headers.append(allocator, .{ .name = name_dup, .value = val_dup });
    }

    // Read response body (invalidates response head strings).
    // Use allocRemaining (reads until end-of-stream); readAlloc tries to fill exactly N bytes.
    var transfer_buf: [64]u8 = undefined;
    var resp_reader = response.reader(&transfer_buf);
    const response_body = try resp_reader.allocRemaining(allocator, .limited(64 * 1024 * 1024));
    defer allocator.free(response_body);

    // Add security headers
    for (&SECURITY_HEADERS) |sh| {
        try resp_headers.append(allocator, sh);
    }

    // Add CORS headers
    if (origin) |o| {
        if (isAllowedOrigin(o)) {
            try resp_headers.append(allocator, .{ .name = "access-control-allow-origin", .value = o });
            try resp_headers.append(allocator, .{ .name = "access-control-allow-credentials", .value = "true" });
            try resp_headers.append(allocator, .{ .name = "vary", .value = "Origin" });
        }
    }

    // Send response to client
    try server_request.respond(response_body, .{
        .status = response.head.status,
        .extra_headers = resp_headers.items,
    });
}

// ═══════════════════════════════════════════
//  CONNECTION HANDLER (public for server_main)
// ═══════════════════════════════════════════

pub fn handleConnection(conn: net.Server.Connection, config: *const Config) void {
    defer conn.stream.close();

    // Create arena for this connection's lifetime
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();

    // Allocate I/O buffers
    const read_buf = allocator.alloc(u8, 65536) catch return;
    const write_buf = allocator.alloc(u8, 65536) catch return;

    // Create std.net.Stream.Reader and Writer
    var stream_reader = net.Stream.Reader.init(conn.stream, read_buf);
    var stream_writer = net.Stream.Writer.init(conn.stream, write_buf);

    // Create HTTP server over this connection
    var server = http.Server.init(stream_reader.interface(), &stream_writer.interface);

    // Handle requests on this connection (HTTP keep-alive)
    while (true) {
        var req = server.receiveHead() catch break;

        const target = parseTarget(req.head.target);
        const method = req.head.method;
        const has_body = method.requestHasBody();
        const has_expect = req.head.expect != null;

        // Copy path/query into arena since readerExpectNone invalidates head strings
        const path = allocator.dupe(u8, target.path) catch break;
        const query = allocator.dupe(u8, target.query) catch break;

        // Extract origin BEFORE reading body (head strings get invalidated)
        var origin: ?[]const u8 = null;
        {
            var it = http.HeaderIterator.init(req.head_buffer);
            while (it.next()) |hdr| {
                if (std.ascii.eqlIgnoreCase(hdr.name, "origin")) {
                    origin = allocator.dupe(u8, hdr.value) catch null;
                    break;
                }
            }
        }

        // Copy head_buffer before body read invalidates it
        const head_buf_copy = allocator.dupe(u8, req.head_buffer) catch break;

        // Read request body — this invalidates head string pointers.
        // IMPORTANT: For POST/PUT/DELETE, we MUST read/discard the body before respond()
        // can be called, otherwise the HTTP server's discardBody() asserts.
        var body: []const u8 = "";
        if (has_body) {
            var body_reader_buf: [65536]u8 = undefined;
            if (has_expect) {
                req.head.expect = null;
            }
            if (req.head.content_length) |cl| {
                if (cl > 0 and cl < 8 * 1024 * 1024) {
                    const reader = req.readerExpectNone(&body_reader_buf);
                    body = reader.readAlloc(allocator, @intCast(cl)) catch break;
                }
                // cl == 0: body stays empty, but content_length is set so respond() is happy
            } else if (req.head.transfer_encoding != .none) {
                // Chunked transfer: read until end
                const reader = req.readerExpectNone(&body_reader_buf);
                body = reader.readAlloc(allocator, 8 * 1024 * 1024) catch break;
            } else {
                // POST/PUT with no Content-Length and no Transfer-Encoding:
                // Set content_length = 0 so the server doesn't assert in discardBody().
                req.head.content_length = 0;
            }
        }

        // CORS preflight
        if (method == .OPTIONS) {
            var cors_hdrs: std.ArrayList(http.Header) = .{};
            for (&SECURITY_HEADERS) |sh| cors_hdrs.append(allocator, sh) catch {};
            if (origin) |o| {
                if (isAllowedOrigin(o)) {
                    cors_hdrs.append(allocator, .{ .name = "access-control-allow-origin", .value = o }) catch {};
                    cors_hdrs.append(allocator, .{ .name = "access-control-allow-credentials", .value = "true" }) catch {};
                    cors_hdrs.append(allocator, .{ .name = "access-control-allow-methods", .value = "GET,POST,PUT,DELETE,PATCH,OPTIONS" }) catch {};
                    cors_hdrs.append(allocator, .{
                        .name = "access-control-allow-headers",
                        .value = "Content-Type,Authorization,X-CSRF-Token,X-Pool-Sync-Secret,X-TrustMesh-Timestamp,X-TrustMesh-Nonce,X-TrustMesh-Signature,X-TrustMesh-Signature-Alg,X-TrustMesh-Method,X-TrustMesh-Path",
                    }) catch {};
                    cors_hdrs.append(allocator, .{ .name = "vary", .value = "Origin" }) catch {};
                }
            }
            req.respond("", .{
                .status = .no_content,
                .extra_headers = cors_hdrs.items,
            }) catch break;
            continue;
        }

        // Check for native handler
        if (router.findHandler(method, path)) |handler| {
            var ctx = RequestContext{
                .allocator = allocator,
                .config = config,
                .method = method,
                .path = path,
                .query = query,
                .body = body,
                .head_buffer = head_buf_copy,
                ._request = &req,
            };
            handler(&ctx) catch |err| {
                if (!ctx._responded) {
                    // SEC-06: Log detailed error server-side, return generic message to client
                    std.log.warn("Handler error for {s}: {}", .{ path, err });
                    ctx.sendError(.internal_server_error, "Internal server error") catch break;
                }
            };
            continue;
        }

        // Proxy to Python
        proxyToPython(&req, body, path, query, origin, head_buf_copy, config, allocator) catch |err| {
            std.log.warn("Proxy error for {s}: {}", .{ path, err });
            req.respond("{\"error\":\"proxy_error\"}", .{
                .status = .bad_gateway,
                .extra_headers = &SECURITY_HEADERS,
            }) catch break;
        };
    }
}

// ═══════════════════════════════════════════
//  SERVER LIFECYCLE
// ═══════════════════════════════════════════

pub const Server = struct {
    config: Config,
    _stop: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),

    pub fn init(config: Config) Server {
        return .{ .config = config };
    }

    pub fn stop(self: *Server) void {
        self._stop.store(true, .release);
    }
};
