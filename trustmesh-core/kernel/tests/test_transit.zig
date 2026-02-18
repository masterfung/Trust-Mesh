// test_transit.zig — Tests for the transit engine (in-memory keyring).

const std = @import("std");
const podos = @import("podos");
const transit = podos.transit;
const crypto = podos.crypto;

test "transit: init and deinit" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();
    try std.testing.expectEqual(@as(usize, 0), engine.ring_count);
}

test "transit: store key returns version 0" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    defer std.crypto.secureZero(u8, &key);
    const version = try engine.storeKey("user-1", &key);
    try std.testing.expectEqual(@as(u32, 0), version);
    try std.testing.expect(engine.hasKey("user-1"));
}

test "transit: encrypt/decrypt roundtrip" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    defer std.crypto.secureZero(u8, &key);
    _ = try engine.storeKey("user-rt", &key);

    const pt = "sensitive medical data";
    const aad = "cap-001|user-rt";

    var ct_buf: [512]u8 = undefined;
    const ct_len = try engine.encryptForUser("user-rt", pt, aad, &ct_buf);

    var out: [512]u8 = undefined;
    const pt_len = try engine.decryptForUser("user-rt", ct_buf[0..ct_len], aad, &out);
    try std.testing.expectEqualStrings(pt, out[0..pt_len]);
}

test "transit: AAD mismatch returns DecryptFailed" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    _ = try engine.storeKey("aad-user", &key);

    var ct: [512]u8 = undefined;
    const ct_len = try engine.encryptForUser("aad-user", "data", "correct", &ct);

    var out: [512]u8 = undefined;
    const result = engine.decryptForUser("aad-user", ct[0..ct_len], "wrong", &out);
    try std.testing.expectError(transit.TransitError.DecryptFailed, result);
}

test "transit: rotate key, old ciphertext still decryptable" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    _ = try engine.storeKey("rotate-user", &key);

    // Encrypt with v0
    var ct: [512]u8 = undefined;
    const ct_len = try engine.encryptForUser("rotate-user", "v0 data", "aad", &ct);

    // Rotate
    const v1 = try engine.rotateKey("rotate-user");
    try std.testing.expectEqual(@as(u32, 1), v1);

    // Encrypt with v1
    var ct2: [512]u8 = undefined;
    const ct2_len = try engine.encryptForUser("rotate-user", "v1 data", "aad", &ct2);

    // Both decrypt correctly
    var out: [512]u8 = undefined;
    const len0 = try engine.decryptForUser("rotate-user", ct[0..ct_len], "aad", &out);
    try std.testing.expectEqualStrings("v0 data", out[0..len0]);

    const len1 = try engine.decryptForUser("rotate-user", ct2[0..ct2_len], "aad", &out);
    try std.testing.expectEqualStrings("v1 data", out[0..len1]);
}

test "transit: remove user zeros keys" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    _ = try engine.storeKey("rm-user", &key);
    try std.testing.expect(engine.hasKey("rm-user"));

    engine.removeUser("rm-user");
    try std.testing.expect(!engine.hasKey("rm-user"));
    try std.testing.expectEqual(@as(usize, 0), engine.ring_count);
}

test "transit: unknown user returns UserNotFound" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var ct: [256]u8 = undefined;
    try std.testing.expectError(
        transit.TransitError.UserNotFound,
        engine.encryptForUser("ghost", "data", "", &ct),
    );
}

test "transit: legacy ciphertext (raw AES-GCM, no version prefix)" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    _ = try engine.storeKey("legacy-user", &key);

    // Encrypt raw (no version prefix, empty AAD) — simulates pre-transit ciphertext
    var raw_ct: [256]u8 = undefined;
    const raw_len = try crypto.encrypt("legacy secret", &key, &raw_ct);

    // Transit engine should decrypt via legacy path
    var out: [256]u8 = undefined;
    const pt_len = try engine.decryptForUser("legacy-user", raw_ct[0..raw_len], "", &out);
    try std.testing.expectEqualStrings("legacy secret", out[0..pt_len]);
}

test "transit: hasKey returns false for missing user" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();
    try std.testing.expect(!engine.hasKey("nobody"));
}

test "transit: multiple users are independent" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key1 = crypto.generateKey();
    var key2 = crypto.generateKey();
    _ = try engine.storeKey("alice", &key1);
    _ = try engine.storeKey("bob", &key2);

    var ct: [256]u8 = undefined;
    const ct_len = try engine.encryptForUser("alice", "alice-only", "aad", &ct);

    // Bob cannot decrypt alice's data
    var out: [256]u8 = undefined;
    try std.testing.expectError(
        transit.TransitError.DecryptFailed,
        engine.decryptForUser("bob", ct[0..ct_len], "aad", &out),
    );
}

test "transit: version prefix in ciphertext" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    _ = try engine.storeKey("vp-user", &key);

    var ct: [512]u8 = undefined;
    const ct_len = try engine.encryptForUser("vp-user", "versioned", "", &ct);

    // Verify the output starts with "v0."
    try std.testing.expect(ct_len > 3);
    try std.testing.expectEqual(@as(u8, 'v'), ct[0]);
    try std.testing.expectEqual(@as(u8, '0'), ct[1]);
    try std.testing.expectEqual(@as(u8, '.'), ct[2]);
}

test "transit: store same user twice adds to same ring" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key1 = crypto.generateKey();
    var key2 = crypto.generateKey();

    const v0 = try engine.storeKey("reuser", &key1);
    try std.testing.expectEqual(@as(u32, 0), v0);
    try std.testing.expectEqual(@as(usize, 1), engine.ring_count);

    const v1 = try engine.storeKey("reuser", &key2);
    try std.testing.expectEqual(@as(u32, 1), v1);
    // Still only 1 ring
    try std.testing.expectEqual(@as(usize, 1), engine.ring_count);
}

test "transit: empty plaintext roundtrip" {
    var engine = transit.TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key = crypto.generateKey();
    _ = try engine.storeKey("empty-user", &key);

    var ct: [256]u8 = undefined;
    const ct_len = try engine.encryptForUser("empty-user", "", "aad", &ct);

    var out: [256]u8 = undefined;
    const pt_len = try engine.decryptForUser("empty-user", ct[0..ct_len], "aad", &out);
    try std.testing.expectEqual(@as(usize, 0), pt_len);
}
