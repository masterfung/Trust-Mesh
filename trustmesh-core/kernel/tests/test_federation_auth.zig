// test_federation_auth.zig — Tests for federation auth signing + replay protection.

const std = @import("std");
const testing = std.testing;
const podos = @import("podos");
const fed_auth = podos.federation_auth;
const crypto = podos.crypto;

// ── Helpers ──

fn makeTestKeypair() struct { seed: [32]u8, did: [128]u8, did_len: usize } {
    const kp = crypto.ed25519Keygen();
    var did_buf: [128]u8 = undefined;
    const did_len = crypto.publicKeyToDid(&kp.public_key, &did_buf);
    return .{ .seed = kp.seed, .did = did_buf, .did_len = did_len };
}

// ── Sign + Verify roundtrip ──

test "federation_auth: sign and verify roundtrip" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();
    const body = "{\"question\":\"hello\"}";

    const headers = try fed_auth.signRequest(body, &kp.seed, "POST", "/api/pod/query", testing.allocator);

    const status = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        body,
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.valid, status);
}

// ── Wrong DID → invalid ──

test "federation_auth: wrong DID rejects signature" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp1 = makeTestKeypair();
    const kp2 = makeTestKeypair();
    const body = "{\"test\":true}";

    const headers = try fed_auth.signRequest(body, &kp1.seed, "POST", "/test", testing.allocator);

    // Verify with kp2's DID — should fail
    const status = try fed_auth.verifyRequest(
        kp2.did[0..kp2.did_len],
        body,
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.invalid, status);
}

// ── Tampered body → invalid ──

test "federation_auth: tampered body rejects" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();
    const body = "{\"original\":true}";

    const headers = try fed_auth.signRequest(body, &kp.seed, "POST", "/test", testing.allocator);

    const status = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        "{\"tampered\":true}",
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.invalid, status);
}

// ── Nonce replay → invalid ──

test "federation_auth: nonce replay rejected" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();
    const body = "test body";

    const headers = try fed_auth.signRequest(body, &kp.seed, "POST", "/test", testing.allocator);

    // First verify succeeds
    const status1 = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        body,
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.valid, status1);

    // Same nonce replayed → rejected
    const status2 = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        body,
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.invalid, status2);
}

// ── Missing headers → missing (not invalid) ──

test "federation_auth: missing headers returns missing" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();

    const status = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        "body",
        null,
        null,
        null,
        null,
        null,
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.missing, status);
}

// ── Partial headers → invalid ──

test "federation_auth: partial headers returns invalid" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();

    // Has timestamp but missing nonce and signature
    const status = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        "body",
        "1234567890",
        null,
        null,
        null,
        null,
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.invalid, status);
}

// ── Empty body roundtrip ──

test "federation_auth: empty body sign and verify" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();

    const headers = try fed_auth.signRequest("", &kp.seed, "GET", "/api/pod", testing.allocator);

    const status = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        "",
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.valid, status);
}

// ── Nonce reset clears cache ──

test "federation_auth: nonce reset allows replay" {
    fed_auth.initNonceCache(testing.allocator);
    defer fed_auth.deinitNonceCache();

    const kp = makeTestKeypair();
    const body = "reset test";

    const headers = try fed_auth.signRequest(body, &kp.seed, "POST", "/test", testing.allocator);

    // First verify succeeds
    const status1 = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        body,
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.valid, status1);

    // Reset nonce cache
    fed_auth.resetNonceCache();

    // Same nonce should now be accepted again
    const status2 = try fed_auth.verifyRequest(
        kp.did[0..kp.did_len],
        body,
        headers.getTimestamp(),
        headers.getNonce(),
        headers.getSignature(),
        headers.getMethod(),
        headers.getPath(),
        testing.allocator,
    );
    try testing.expectEqual(fed_auth.VerifyStatus.valid, status2);
}

// ── Sign produces valid header fields ──

test "federation_auth: sign produces non-empty header fields" {
    const kp = makeTestKeypair();
    const body = "{\"data\":1}";

    const headers = try fed_auth.signRequest(body, &kp.seed, "POST", "/api/pod/query", testing.allocator);

    try testing.expect(headers.getTimestamp().len > 0);
    try testing.expect(headers.getNonce().len >= 8);
    try testing.expect(headers.getSignature().len > 0);
    try testing.expectEqualStrings("POST", headers.getMethod());
    try testing.expectEqualStrings("/api/pod/query", headers.getPath());
}

// ── SSRF validation ──

test "federation: SSRF blocks private IPs" {
    const fed = podos.federation;

    // Public URLs should pass
    try testing.expect(fed.validatePeerUrl("https://example.com/api/pod"));
    try testing.expect(fed.validatePeerUrl("http://my-pod.trustmesh.io:8001"));

    // Private IPs should be blocked
    try testing.expect(!fed.validatePeerUrl("http://127.0.0.1:8000"));
    try testing.expect(!fed.validatePeerUrl("http://10.0.0.1/api"));
    try testing.expect(!fed.validatePeerUrl("http://172.16.0.1:9000"));
    try testing.expect(!fed.validatePeerUrl("http://192.168.1.1:8000"));
    try testing.expect(!fed.validatePeerUrl("http://localhost:8000"));
    try testing.expect(!fed.validatePeerUrl("http://0.0.0.0"));
    try testing.expect(!fed.validatePeerUrl("http://169.254.169.254/metadata")); // AWS metadata

    // Non-HTTP schemes should be blocked
    try testing.expect(!fed.validatePeerUrl("ftp://example.com/file"));
    try testing.expect(!fed.validatePeerUrl("file:///etc/passwd"));
    try testing.expect(!fed.validatePeerUrl("gopher://evil.com"));

    // Internal hostnames blocked
    try testing.expect(!fed.validatePeerUrl("http://metadata/latest"));
    try testing.expect(!fed.validatePeerUrl("http://internal.service/api"));
}

// ── JSON escape ──

test "json: escapeJsonString handles special chars" {
    const json_mod = podos.json;
    var buf: [256]u8 = undefined;

    // Normal string passes through
    const len1 = try json_mod.escapeJsonString("hello world", &buf);
    try testing.expectEqualStrings("hello world", buf[0..len1]);

    // Quotes are escaped
    const len2 = try json_mod.escapeJsonString("say \"hi\"", &buf);
    try testing.expectEqualStrings("say \\\"hi\\\"", buf[0..len2]);

    // Backslashes are escaped
    const len3 = try json_mod.escapeJsonString("path\\to\\file", &buf);
    try testing.expectEqualStrings("path\\\\to\\\\file", buf[0..len3]);

    // Newlines are escaped
    const len4 = try json_mod.escapeJsonString("line1\nline2", &buf);
    try testing.expectEqualStrings("line1\\nline2", buf[0..len4]);

    // Control chars are escaped as \u00XX
    const len5 = try json_mod.escapeJsonString("null\x00byte", &buf);
    try testing.expectEqualStrings("null\\u0000byte", buf[0..len5]);
}
