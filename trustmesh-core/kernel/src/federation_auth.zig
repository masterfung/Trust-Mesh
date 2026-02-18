// federation_auth.zig — Ed25519 request signing + replay protection for cross-pod federation.
//
// Ports federation_auth.py to Zig. All crypto uses existing crypto.zig primitives.
//
// Signing scheme (Ed25519):
//   Message = "<method>\n<path>\n<ts>\n<nonce>\n" + raw body bytes
//   Headers:
//     X-TrustMesh-Timestamp     unix seconds (integer string)
//     X-TrustMesh-Nonce         base64url(16 random bytes)
//     X-TrustMesh-Signature     base64url(64-byte Ed25519 sig)
//     X-TrustMesh-Signature-Alg "ed25519"
//     X-TrustMesh-Method        HTTP method (if method+path signing)
//     X-TrustMesh-Path          URL path  (if method+path signing)
//
// Replay protection:
//   In-memory nonce cache: (from_did, nonce) → expires_at_epoch_sec.
//   Expired entries pruned on every verify call.

const std = @import("std");
const crypto_mod = @import("crypto.zig");
const Allocator = std.mem.Allocator;

// ═══════════════════════════════════════════
//  CONSTANTS
// ═══════════════════════════════════════════

pub const DEFAULT_SKEW_SECONDS: i64 = 60;
pub const DEFAULT_NONCE_TTL_SECONDS: i64 = 120;
pub const MAX_NONCE_CACHE: usize = 50_000;

// ═══════════════════════════════════════════
//  NONCE CACHE
// ═══════════════════════════════════════════

/// Cache key: (from_did, nonce) interned as "did|nonce" string.
const NonceCacheKey = []const u8;

const NonceCacheEntry = struct {
    key: []const u8, // heap-owned
    expires_at: i64,
};

pub const FederationAuthError = error{
    OutOfMemory,
    SignFailed,
    VerifyFailed,
    MissingHeaders,
    InvalidTimestamp,
    InvalidNonce,
    TimestampOutOfWindow,
    ReplayDetected,
    InvalidSignature,
    InvalidDid,
};

// ─── Global nonce cache ───
var _nonce_cache: std.StringHashMapUnmanaged(i64) = .{};
var _nonce_alloc: ?Allocator = null;
var _nonce_mutex: std.Thread.Mutex = .{};

pub fn initNonceCache(allocator: Allocator) void {
    _nonce_alloc = allocator;
}

pub fn deinitNonceCache() void {
    if (_nonce_alloc) |alloc| {
        var it = _nonce_cache.iterator();
        while (it.next()) |entry| {
            alloc.free(entry.key_ptr.*);
        }
        _nonce_cache.deinit(alloc);
        _nonce_cache = .{};
        _nonce_alloc = null;
    }
}

/// Test helper: clear the nonce cache.
pub fn resetNonceCache() void {
    const alloc = _nonce_alloc orelse return;
    _nonce_mutex.lock();
    defer _nonce_mutex.unlock();
    var it = _nonce_cache.iterator();
    while (it.next()) |entry| {
        alloc.free(entry.key_ptr.*);
    }
    _nonce_cache.deinit(alloc);
    _nonce_cache = .{};
}

fn pruneExpiredNonces(now_epoch: i64) void {
    const alloc = _nonce_alloc orelse return;
    var to_remove = std.ArrayListUnmanaged([]const u8){};
    defer to_remove.deinit(alloc);

    var it = _nonce_cache.iterator();
    while (it.next()) |entry| {
        if (entry.value_ptr.* <= now_epoch) {
            to_remove.append(alloc, entry.key_ptr.*) catch {};
        }
    }
    for (to_remove.items) |k| {
        _ = _nonce_cache.fetchRemove(k);
        alloc.free(k);
    }
}

fn checkAndRecordNonce(from_did: []const u8, nonce: []const u8, now_epoch: i64, ttl: i64) FederationAuthError!void {
    const alloc = _nonce_alloc orelse return; // no cache = no replay protection (permissive)

    _nonce_mutex.lock();
    defer _nonce_mutex.unlock();

    // Opportunistic pruning (every time to keep memory bounded)
    pruneExpiredNonces(now_epoch);

    // Build cache key: "did|nonce"
    const cache_key = std.fmt.allocPrint(alloc, "{s}|{s}", .{ from_did, nonce }) catch return FederationAuthError.OutOfMemory;

    // Check if this nonce already exists
    if (_nonce_cache.getPtr(cache_key)) |exp_ptr| {
        if (exp_ptr.* > now_epoch) {
            alloc.free(cache_key);
            return FederationAuthError.ReplayDetected;
        }
        // Expired entry — update expiry in place, free the new key (existing key stays)
        exp_ptr.* = now_epoch + ttl;
        alloc.free(cache_key);
        return;
    }

    // SEC-07/08: Enforce max capacity — reject if full after pruning
    if (_nonce_cache.count() >= MAX_NONCE_CACHE) {
        // Already pruned above; if still full, reject to prevent OOM
        alloc.free(cache_key);
        return FederationAuthError.OutOfMemory;
    }

    // New nonce — record it
    _nonce_cache.put(alloc, cache_key, now_epoch + ttl) catch {
        alloc.free(cache_key);
        return FederationAuthError.OutOfMemory;
    };
}

// ═══════════════════════════════════════════
//  SIGNING
// ═══════════════════════════════════════════

/// Signed headers returned from signRequest.
pub const SignedHeaders = struct {
    timestamp: [20]u8, // decimal string
    timestamp_len: usize,
    nonce: [32]u8, // base64url string
    nonce_len: usize,
    signature: [88]u8, // base64url(64-byte sig)
    signature_len: usize,
    /// Include method/path headers for new-format signing.
    method: [16]u8,
    method_len: usize,
    path: [512]u8,
    path_len: usize,

    pub fn getTimestamp(self: *const SignedHeaders) []const u8 {
        return self.timestamp[0..self.timestamp_len];
    }
    pub fn getNonce(self: *const SignedHeaders) []const u8 {
        return self.nonce[0..self.nonce_len];
    }
    pub fn getSignature(self: *const SignedHeaders) []const u8 {
        return self.signature[0..self.signature_len];
    }
    pub fn getMethod(self: *const SignedHeaders) []const u8 {
        return self.method[0..self.method_len];
    }
    pub fn getPath(self: *const SignedHeaders) []const u8 {
        return self.path[0..self.path_len];
    }
};

/// Build the canonical message to sign.
/// New format: "<METHOD>\n<path>\n<ts>\n<nonce>\n" + body
/// Legacy format (no method/path): "<ts>\n<nonce>\n" + body
fn buildSignMessage(
    method: []const u8,
    path: []const u8,
    ts: i64,
    nonce_b64: []const u8,
    body: []const u8,
    allocator: Allocator,
) ![]u8 {
    if (method.len > 0 and path.len > 0) {
        return std.fmt.allocPrint(allocator, "{s}\n{s}\n{d}\n{s}\n{s}", .{
            method, path, ts, nonce_b64, body,
        });
    }
    return std.fmt.allocPrint(allocator, "{d}\n{s}\n{s}", .{ ts, nonce_b64, body });
}

/// Sign a federation request.
/// private_key_seed: 32-byte Ed25519 seed.
pub fn signRequest(
    body: []const u8,
    private_key_seed: *const [32]u8,
    method: []const u8,
    path: []const u8,
    allocator: Allocator,
) FederationAuthError!SignedHeaders {
    const ts = std.time.timestamp();

    // Generate 16 random bytes, base64url-encode for nonce
    var nonce_raw: [16]u8 = undefined;
    std.crypto.random.bytes(&nonce_raw);

    var nonce_buf: [32]u8 = undefined;
    const nonce_encoded = std.base64.url_safe_no_pad.Encoder.encode(&nonce_buf, &nonce_raw);

    // Build message
    const msg = buildSignMessage(method, path, ts, nonce_encoded, body, allocator) catch
        return FederationAuthError.SignFailed;
    defer allocator.free(msg);
    defer std.crypto.secureZero(u8, msg);

    // Sign with Ed25519
    const sig_bytes = crypto_mod.ed25519Sign(msg, private_key_seed) catch
        return FederationAuthError.SignFailed;

    // Encode signature as base64url
    var sig_b64_buf: [88]u8 = undefined;
    const sig_encoded = std.base64.url_safe_no_pad.Encoder.encode(&sig_b64_buf, &sig_bytes);

    var out: SignedHeaders = undefined;

    // Timestamp
    const ts_str = std.fmt.bufPrint(&out.timestamp, "{d}", .{ts}) catch return FederationAuthError.SignFailed;
    out.timestamp_len = ts_str.len;

    // Nonce
    @memcpy(out.nonce[0..nonce_encoded.len], nonce_encoded);
    out.nonce_len = nonce_encoded.len;

    // Signature
    @memcpy(out.signature[0..sig_encoded.len], sig_encoded);
    out.signature_len = sig_encoded.len;

    // Method + Path
    if (method.len <= out.method.len) {
        @memcpy(out.method[0..method.len], method);
        out.method_len = method.len;
    } else {
        out.method_len = 0;
    }
    if (path.len <= out.path.len) {
        @memcpy(out.path[0..path.len], path);
        out.path_len = path.len;
    } else {
        out.path_len = 0;
    }

    return out;
}

// ═══════════════════════════════════════════
//  VERIFICATION
// ═══════════════════════════════════════════

pub const VerifyStatus = enum(u8) {
    missing = 0,
    valid = 1,
    invalid = 2,
};

/// Verify a federation request signature + replay protection.
/// Returns:
///   .missing  — no signature headers (backward compatible: treat as public trust)
///   .valid    — signature valid, nonce not replayed
///   .invalid  — any verification failure
pub fn verifyRequest(
    from_did: []const u8,
    body: []const u8,
    ts_str: ?[]const u8,
    nonce: ?[]const u8,
    sig_b64: ?[]const u8,
    method_hdr: ?[]const u8, // X-TrustMesh-Method
    path_hdr: ?[]const u8, // X-TrustMesh-Path
    allocator: Allocator,
) FederationAuthError!VerifyStatus {
    // Backward compat: missing headers = public trust (not invalid)
    if (ts_str == null and nonce == null and sig_b64 == null) return .missing;

    // Partial headers = invalid
    const ts_s = ts_str orelse return .invalid;
    const nonce_s = nonce orelse return .invalid;
    const sig_s = sig_b64 orelse return .invalid;

    // Validate timestamp
    const ts = std.fmt.parseInt(i64, ts_s, 10) catch return .invalid;
    if (ts <= 0) return .invalid;

    // Validate nonce format: [A-Za-z0-9_-]{8,128}
    if (nonce_s.len < 8 or nonce_s.len > 128) return .invalid;
    for (nonce_s) |ch| {
        if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return .invalid;
    }

    // Timestamp window check
    const now_epoch = std.time.timestamp();
    const skew = now_epoch - ts;
    const abs_skew = if (skew < 0) -skew else skew;
    if (abs_skew > DEFAULT_SKEW_SECONDS) return .invalid;

    // Prune + check nonce (before signature verification to avoid timing oracle).
    // We only record after sig verifies to limit cache filling by bad actors.

    // Decode signature (base64url)
    if (sig_s.len > 128) return .invalid;
    var sig_bytes: [64]u8 = undefined;
    const decoded_len = std.base64.url_safe_no_pad.Decoder.calcSizeUpperBound(sig_s.len) catch return .invalid;
    if (decoded_len < 64 or decoded_len > 64) {
        // Try with padding
        const sig_padded = blk: {
            var buf: [128]u8 = undefined;
            const pad = (4 - sig_s.len % 4) % 4;
            @memcpy(buf[0..sig_s.len], sig_s);
            for (0..pad) |i| buf[sig_s.len + i] = '=';
            break :blk buf[0 .. sig_s.len + pad];
        };
        std.base64.url_safe.Decoder.decode(&sig_bytes, sig_padded) catch return .invalid;
    } else {
        std.base64.url_safe_no_pad.Decoder.decode(&sig_bytes, sig_s) catch return .invalid;
    }

    // Resolve public key from DID
    var pub_key: [32]u8 = undefined;
    crypto_mod.didKeyToPublicKey(from_did, &pub_key) catch return .invalid;

    // Build canonical message (try new format first if method+path present)
    const use_method = method_hdr orelse "";
    const use_path = path_hdr orelse "";

    const msg = buildSignMessage(use_method, use_path, ts, nonce_s, body, allocator) catch
        return .invalid;
    defer allocator.free(msg);

    // Verify Ed25519 signature
    const valid = crypto_mod.ed25519Verify(msg, &sig_bytes, &pub_key);
    if (!valid) return .invalid;

    // Now record nonce (after successful verification)
    checkAndRecordNonce(from_did, nonce_s, now_epoch, DEFAULT_NONCE_TTL_SECONDS) catch |err| switch (err) {
        FederationAuthError.ReplayDetected => return .invalid,
        else => return err,
    };

    return .valid;
}

// ═══════════════════════════════════════════
//  C ABI EXPORTS
// ═══════════════════════════════════════════

const ffi_alloc = std.heap.page_allocator;

/// Sign a federation request.
/// Outputs a JSON object with header name/value pairs.
/// Returns 0 on success, negative on error.
export fn podos_federation_sign(
    body_ptr: [*]const u8,
    body_len: usize,
    method_ptr: [*]const u8,
    method_len: usize,
    path_ptr: [*]const u8,
    path_len: usize,
    private_key_ptr: [*]const u8, // 32-byte Ed25519 seed
    out_json: [*]u8,
    out_cap: usize,
    out_len: *usize,
) callconv(.c) i32 {
    const body = body_ptr[0..body_len];
    const method = method_ptr[0..method_len];
    const path = path_ptr[0..path_len];
    const seed: *const [32]u8 = @ptrCast(private_key_ptr);

    const headers = signRequest(body, seed, method, path, ffi_alloc) catch return -1;

    const ts = headers.getTimestamp();
    const nonce = headers.getNonce();
    const sig = headers.getSignature();
    const meth = headers.getMethod();
    const pth = headers.getPath();

    // Serialize as JSON object
    const written = if (meth.len > 0 and pth.len > 0)
        std.fmt.bufPrint(out_json[0..out_cap],
            "{{\"X-TrustMesh-Timestamp\":\"{s}\",\"X-TrustMesh-Nonce\":\"{s}\",\"X-TrustMesh-Signature\":\"{s}\",\"X-TrustMesh-Signature-Alg\":\"ed25519\",\"X-TrustMesh-Method\":\"{s}\",\"X-TrustMesh-Path\":\"{s}\"}}",
            .{ ts, nonce, sig, meth, pth }) catch return -2
    else
        std.fmt.bufPrint(out_json[0..out_cap],
            "{{\"X-TrustMesh-Timestamp\":\"{s}\",\"X-TrustMesh-Nonce\":\"{s}\",\"X-TrustMesh-Signature\":\"{s}\",\"X-TrustMesh-Signature-Alg\":\"ed25519\"}}",
            .{ ts, nonce, sig }) catch return -2;

    out_len.* = written.len;
    return 0;
}

/// Verify a federation request signature.
/// headers_json: JSON object with TrustMesh header fields.
/// Returns: 1=valid, 0=missing (no sig headers), -1=invalid/error
export fn podos_federation_verify(
    from_did_ptr: [*]const u8,
    from_did_len: usize,
    body_ptr: [*]const u8,
    body_len: usize,
    headers_json_ptr: [*]const u8,
    headers_json_len: usize,
) callconv(.c) i32 {
    const from_did = from_did_ptr[0..from_did_len];
    const body = body_ptr[0..body_len];
    const headers_json = headers_json_ptr[0..headers_json_len];

    // Parse headers JSON
    const HeadersMap = struct {
        @"X-TrustMesh-Timestamp": ?[]const u8 = null,
        @"X-TrustMesh-Nonce": ?[]const u8 = null,
        @"X-TrustMesh-Signature": ?[]const u8 = null,
        @"X-TrustMesh-Method": ?[]const u8 = null,
        @"X-TrustMesh-Path": ?[]const u8 = null,
    };

    const parsed = std.json.parseFromSlice(HeadersMap, ffi_alloc, headers_json, .{ .ignore_unknown_fields = true }) catch return -1;
    defer parsed.deinit();
    const h = parsed.value;

    const status = verifyRequest(
        from_did,
        body,
        h.@"X-TrustMesh-Timestamp",
        h.@"X-TrustMesh-Nonce",
        h.@"X-TrustMesh-Signature",
        h.@"X-TrustMesh-Method",
        h.@"X-TrustMesh-Path",
        ffi_alloc,
    ) catch return -1;

    return switch (status) {
        .valid => 1,
        .missing => 0,
        .invalid => -1,
    };
}

/// Reset nonce cache (test helper).
export fn podos_federation_nonce_reset() callconv(.c) void {
    resetNonceCache();
}
