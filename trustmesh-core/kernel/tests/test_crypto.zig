// test_crypto.zig — Tests for crypto primitives.

const std = @import("std");
const testing = std.testing;
const podos = @import("podos");
const crypto = podos.crypto;

// ── AES-256-GCM ──

test "crypto: encrypt/decrypt roundtrip" {
    const key = crypto.generateKey();
    const plaintext = "Hello, TrustMesh!";
    var ciphertext: [256]u8 = undefined;
    const ct_len = try crypto.encrypt(plaintext, &key, &ciphertext);

    // Ciphertext should be nonce(12) + plaintext(17) + tag(16) = 45
    try testing.expectEqual(@as(usize, 45), ct_len);

    var decrypted: [256]u8 = undefined;
    const pt_len = try crypto.decrypt(ciphertext[0..ct_len], &key, &decrypted);
    try testing.expectEqual(@as(usize, 17), pt_len);
    try testing.expectEqualStrings(plaintext, decrypted[0..pt_len]);
}

test "crypto: wrong key fails decrypt" {
    const key1 = crypto.generateKey();
    const key2 = crypto.generateKey();
    const plaintext = "Secret data";
    var ciphertext: [256]u8 = undefined;
    const ct_len = try crypto.encrypt(plaintext, &key1, &ciphertext);

    var decrypted: [256]u8 = undefined;
    const result = crypto.decrypt(ciphertext[0..ct_len], &key2, &decrypted);
    try testing.expectError(crypto.CryptoError.DecryptFailed, result);
}

test "crypto: empty plaintext roundtrip" {
    const key = crypto.generateKey();
    var ciphertext: [256]u8 = undefined;
    const ct_len = try crypto.encrypt("", &key, &ciphertext);
    // Empty: nonce(12) + tag(16) = 28
    try testing.expectEqual(@as(usize, 28), ct_len);

    var decrypted: [256]u8 = undefined;
    const pt_len = try crypto.decrypt(ciphertext[0..ct_len], &key, &decrypted);
    try testing.expectEqual(@as(usize, 0), pt_len);
}

test "crypto: deterministic encrypt with nonce" {
    const key = [_]u8{0x42} ** 32;
    const nonce = [_]u8{0x01} ** 12;
    const plaintext = "test";

    var ct1: [256]u8 = undefined;
    var ct2: [256]u8 = undefined;
    const len1 = try crypto.encryptWithNonce(plaintext, &key, nonce, &ct1);
    const len2 = try crypto.encryptWithNonce(plaintext, &key, nonce, &ct2);

    try testing.expectEqual(len1, len2);
    try testing.expectEqualSlices(u8, ct1[0..len1], ct2[0..len2]);
}

// ── SHA-256 ──

test "crypto: sha256 known vector" {
    // SHA-256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    var hex: [64]u8 = undefined;
    crypto.sha256Hex("hello", &hex);
    try testing.expectEqualStrings(
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        &hex,
    );
}

test "crypto: sha256 empty string" {
    var hex: [64]u8 = undefined;
    crypto.sha256Hex("", &hex);
    try testing.expectEqualStrings(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        &hex,
    );
}

// ── Ed25519 ──

test "crypto: ed25519 keygen produces valid keys" {
    const kp = crypto.ed25519Keygen();
    // Seed and public key should be 32 bytes each (non-zero)
    try testing.expect(!std.mem.eql(u8, &kp.seed, &([_]u8{0} ** 32)));
    try testing.expect(!std.mem.eql(u8, &kp.public_key, &([_]u8{0} ** 32)));
}

test "crypto: ed25519 sign and verify" {
    const kp = crypto.ed25519Keygen();
    const msg = "Trust is the foundation.";
    const sig = try crypto.ed25519Sign(msg, &kp.seed);
    try testing.expect(crypto.ed25519Verify(msg, &sig, &kp.public_key));
}

test "crypto: ed25519 wrong key fails verify" {
    const kp1 = crypto.ed25519Keygen();
    const kp2 = crypto.ed25519Keygen();
    const msg = "This message is signed by kp1";
    const sig = try crypto.ed25519Sign(msg, &kp1.seed);
    try testing.expect(!crypto.ed25519Verify(msg, &sig, &kp2.public_key));
}

test "crypto: ed25519 tampered message fails verify" {
    const kp = crypto.ed25519Keygen();
    const msg = "Original message";
    const sig = try crypto.ed25519Sign(msg, &kp.seed);
    try testing.expect(!crypto.ed25519Verify("Tampered message", &sig, &kp.public_key));
}

test "crypto: ed25519 deterministic from same seed" {
    // Generate a keypair, extract seed, then sign with seed — should produce valid sigs
    const kp = crypto.ed25519Keygen();
    const msg = "deterministic test";

    // Sign twice with same seed → same signature
    const sig1 = try crypto.ed25519Sign(msg, &kp.seed);
    const sig2 = try crypto.ed25519Sign(msg, &kp.seed);
    try testing.expectEqualSlices(u8, &sig1, &sig2);

    // Both signatures should verify against the public key
    try testing.expect(crypto.ed25519Verify(msg, &sig1, &kp.public_key));
}

// ── Base58btc ──

test "crypto: base58btc encode/decode roundtrip" {
    const data = [_]u8{ 0xed, 0x01, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47 };
    var encoded: [128]u8 = undefined;
    const enc_len = crypto.base58btcEncode(&data, &encoded);
    try testing.expect(enc_len > 0);

    var decoded: [128]u8 = undefined;
    const dec_len = try crypto.base58btcDecode(encoded[0..enc_len], &decoded);
    try testing.expectEqual(data.len, dec_len);
    try testing.expectEqualSlices(u8, &data, decoded[0..dec_len]);
}

test "crypto: base58btc leading zeros" {
    // Leading zero bytes map to '1' characters
    const data = [_]u8{ 0, 0, 0, 1 };
    var encoded: [128]u8 = undefined;
    const enc_len = crypto.base58btcEncode(&data, &encoded);
    // Should start with "111" (three leading zeros) followed by "2" (value 1)
    try testing.expectEqualStrings("1112", encoded[0..enc_len]);

    var decoded: [128]u8 = undefined;
    const dec_len = try crypto.base58btcDecode(encoded[0..enc_len], &decoded);
    try testing.expectEqual(@as(usize, 4), dec_len);
    try testing.expectEqualSlices(u8, &data, decoded[0..dec_len]);
}

test "crypto: base58btc single byte" {
    const data = [_]u8{0x00};
    var encoded: [128]u8 = undefined;
    const enc_len = crypto.base58btcEncode(&data, &encoded);
    try testing.expectEqualStrings("1", encoded[0..enc_len]);
}

// ── DID:KEY ──

test "crypto: did roundtrip" {
    const kp = crypto.ed25519Keygen();
    var did: [128]u8 = undefined;
    const did_len = crypto.publicKeyToDid(&kp.public_key, &did);
    try testing.expect(did_len > 0);
    try testing.expect(std.mem.startsWith(u8, did[0..did_len], "did:key:z"));

    var recovered: [32]u8 = undefined;
    try crypto.didKeyToPublicKey(did[0..did_len], &recovered);
    try testing.expectEqualSlices(u8, &kp.public_key, &recovered);
}

test "crypto: invalid did format" {
    var key: [32]u8 = undefined;
    try testing.expectError(crypto.CryptoError.InvalidDid, crypto.didKeyToPublicKey("not-a-did", &key));
    try testing.expectError(crypto.CryptoError.InvalidDid, crypto.didKeyToPublicKey("did:key:abc", &key));
}

// ── Base64url ──

test "crypto: base64url roundtrip" {
    const data = "Hello, World!";
    var encoded: [128]u8 = undefined;
    const enc_len = crypto.base64urlEncode(data, &encoded);
    try testing.expect(enc_len > 0);

    var decoded: [128]u8 = undefined;
    const dec_len = try crypto.base64urlDecode(encoded[0..enc_len], &decoded);
    try testing.expectEqualStrings(data, decoded[0..dec_len]);
}

test "crypto: base64url empty" {
    var encoded: [128]u8 = undefined;
    const enc_len = crypto.base64urlEncode("", &encoded);
    try testing.expectEqual(@as(usize, 0), enc_len);
}

// ── Argon2id ──
// Note: Argon2 tests use production params, so they're slow (~1s each).
// Only include essential cross-validation tests.

test "crypto: argon2 vault key deterministic" {
    const password = "TrustMesh-demo-2026";
    var salt: [16]u8 = [_]u8{ 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10 };
    var key1: [32]u8 = undefined;
    var key2: [32]u8 = undefined;
    var out_salt1: [16]u8 = undefined;
    var out_salt2: [16]u8 = undefined;

    try crypto.deriveVaultKey(std.heap.page_allocator, password, &salt, &key1, &out_salt1);
    try crypto.deriveVaultKey(std.heap.page_allocator, password, &salt, &key2, &out_salt2);

    // Same password + salt → same key
    try testing.expectEqualSlices(u8, &key1, &key2);
    try testing.expectEqualSlices(u8, &out_salt1, &out_salt2);
    // Key should not be all zeros
    try testing.expect(!std.mem.eql(u8, &key1, &([_]u8{0} ** 32)));
}

test "crypto: argon2 pin hash and verify" {
    var hash_buf: [128]u8 = undefined;
    const hash_len = try crypto.hashPin(std.heap.page_allocator, "1234", &hash_buf);
    const pin_hash = hash_buf[0..hash_len];

    // Should be "hex(16)$hex(32)" = 32 + 1 + 64 = 97 chars
    try testing.expectEqual(@as(usize, 97), hash_len);
    try testing.expect(pin_hash[32] == '$');

    // Correct PIN verifies
    try testing.expect(crypto.verifyPin(std.heap.page_allocator, "1234", pin_hash));

    // Wrong PIN fails
    try testing.expect(!crypto.verifyPin(std.heap.page_allocator, "5678", pin_hash));
}

// ── Additional edge case tests ──

test "crypto: large plaintext encrypt/decrypt" {
    const key = crypto.generateKey();
    // 4KB plaintext
    var plaintext: [4096]u8 = undefined;
    for (&plaintext, 0..) |*b, i| b.* = @truncate(i);

    var ciphertext: [4096 + 28]u8 = undefined;
    const ct_len = try crypto.encrypt(&plaintext, &key, &ciphertext);
    try testing.expectEqual(@as(usize, 4096 + 28), ct_len);

    var decrypted: [4096]u8 = undefined;
    const pt_len = try crypto.decrypt(ciphertext[0..ct_len], &key, &decrypted);
    try testing.expectEqual(@as(usize, 4096), pt_len);
    try testing.expectEqualSlices(u8, &plaintext, decrypted[0..pt_len]);
}

test "crypto: truncated ciphertext fails decrypt" {
    const key = crypto.generateKey();
    // Too short — less than nonce + tag
    const short = [_]u8{1} ** 20;
    var out: [256]u8 = undefined;
    try testing.expectError(crypto.CryptoError.InvalidData, crypto.decrypt(&short, &key, &out));
}

test "crypto: tampered ciphertext fails decrypt" {
    const key = crypto.generateKey();
    var ct: [256]u8 = undefined;
    const ct_len = try crypto.encrypt("sensitive", &key, &ct);

    // Flip a byte in the ciphertext body
    ct[15] ^= 0xFF;
    var out: [256]u8 = undefined;
    try testing.expectError(crypto.CryptoError.DecryptFailed, crypto.decrypt(ct[0..ct_len], &key, &out));
}

test "crypto: each encrypt produces different ciphertext" {
    const key = crypto.generateKey();
    var ct1: [256]u8 = undefined;
    var ct2: [256]u8 = undefined;
    const len1 = try crypto.encrypt("same", &key, &ct1);
    const len2 = try crypto.encrypt("same", &key, &ct2);
    try testing.expectEqual(len1, len2);
    // Different random nonces → different ciphertexts
    try testing.expect(!std.mem.eql(u8, ct1[0..len1], ct2[0..len2]));
}

test "crypto: generateKey produces unique keys" {
    const k1 = crypto.generateKey();
    const k2 = crypto.generateKey();
    try testing.expect(!std.mem.eql(u8, &k1, &k2));
}

test "crypto: sha256 unicode" {
    var hex: [64]u8 = undefined;
    // Known: SHA-256 of UTF-8 bytes for the lock emoji
    crypto.sha256Hex("\xF0\x9F\x94\x90", &hex);
    try testing.expectEqual(@as(usize, 64), hex.len);
    // Just verify it's valid hex and non-zero
    try testing.expect(!std.mem.eql(u8, &hex, &([_]u8{'0'} ** 64)));
}

test "crypto: ed25519 sign empty message" {
    const kp = crypto.ed25519Keygen();
    const sig = try crypto.ed25519Sign("", &kp.seed);
    try testing.expect(crypto.ed25519Verify("", &sig, &kp.public_key));
}

test "crypto: ed25519 sign large message" {
    const kp = crypto.ed25519Keygen();
    const msg = [_]u8{0xAB} ** 8192;
    const sig = try crypto.ed25519Sign(&msg, &kp.seed);
    try testing.expect(crypto.ed25519Verify(&msg, &sig, &kp.public_key));
}

test "crypto: base64url known vector" {
    var encoded: [128]u8 = undefined;
    // "Hello" → "SGVsbG8"
    const enc_len = crypto.base64urlEncode("Hello", &encoded);
    try testing.expectEqualStrings("SGVsbG8", encoded[0..enc_len]);

    var decoded: [128]u8 = undefined;
    const dec_len = try crypto.base64urlDecode("SGVsbG8", &decoded);
    try testing.expectEqualStrings("Hello", decoded[0..dec_len]);
}

test "crypto: base58btc known vector z" {
    // Empty input should produce empty output
    const data = [_]u8{};
    var encoded: [128]u8 = undefined;
    const enc_len = crypto.base58btcEncode(&data, &encoded);
    try testing.expectEqual(@as(usize, 0), enc_len);
}

test "crypto: did key format prefix" {
    const kp = crypto.ed25519Keygen();
    var did: [128]u8 = undefined;
    const did_len = crypto.publicKeyToDid(&kp.public_key, &did);
    // Must start with "did:key:z"
    try testing.expect(std.mem.startsWith(u8, did[0..did_len], "did:key:z"));
    // The 'z' indicates base58btc encoding
    try testing.expect(did_len > 10);
}

test "crypto: argon2 different passwords produce different keys" {
    var salt: [16]u8 = [_]u8{0x42} ** 16;
    var key1: [32]u8 = undefined;
    var key2: [32]u8 = undefined;
    var out_salt: [16]u8 = undefined;

    try crypto.deriveVaultKey(std.heap.page_allocator, "password1", &salt, &key1, &out_salt);
    try crypto.deriveVaultKey(std.heap.page_allocator, "password2", &salt, &key2, &out_salt);
    try testing.expect(!std.mem.eql(u8, &key1, &key2));
}
