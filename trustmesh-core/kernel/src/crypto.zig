// crypto.zig — Cryptographic primitives for PodOS kernel.
// AES-256-GCM, Ed25519, Argon2id, SHA-256, Base58btc, Base64url.
// Replaces Python's `cryptography` and `argon2-cffi` packages.

const std = @import("std");

// ═══════════════════════════════════════════
//  TYPE ALIASES
// ═══════════════════════════════════════════

const Aes256Gcm = std.crypto.aead.aes_gcm.Aes256Gcm;
const Ed25519 = std.crypto.sign.Ed25519;
const Sha256 = std.crypto.hash.sha2.Sha256;
const Allocator = std.mem.Allocator;

// ═══════════════════════════════════════════
//  CONSTANTS
// ═══════════════════════════════════════════

pub const KEY_SIZE = 32;
pub const NONCE_SIZE = Aes256Gcm.nonce_length; // 12
pub const TAG_SIZE = Aes256Gcm.tag_length; // 16
pub const ARGON2_SALT_SIZE = 16;

// Ed25519 multicodec prefix for did:key (0xed = ed25519-pub, 0x01 varint)
pub const ED25519_MC_PREFIX = [_]u8{ 0xed, 0x01 };

// Base58btc alphabet
pub const B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

pub const CryptoError = error{
    EncryptFailed,
    DecryptFailed,
    InvalidData,
    BufferTooSmall,
    ArgonFailed,
    Ed25519Failed,
    InvalidDid,
    Base58DecodeFailed,
    Base64DecodeFailed,
};

// ═══════════════════════════════════════════
//  AES-256-GCM
// ═══════════════════════════════════════════

/// Generate a random 32-byte AES-256 key.
pub fn generateKey() [KEY_SIZE]u8 {
    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);
    return key;
}

/// Encrypt plaintext with AES-256-GCM.
/// Output format: nonce(12) || ciphertext(pt_len) || tag(16)
/// Returns total bytes written = NONCE_SIZE + plaintext.len + TAG_SIZE.
pub fn encrypt(plaintext: []const u8, key: *const [KEY_SIZE]u8, out: []u8) CryptoError!usize {
    const total = NONCE_SIZE + plaintext.len + TAG_SIZE;
    if (out.len < total) return CryptoError.BufferTooSmall;

    // Random nonce
    var nonce: [NONCE_SIZE]u8 = undefined;
    std.crypto.random.bytes(&nonce);

    @memcpy(out[0..NONCE_SIZE], &nonce);

    // Encrypt
    var tag: [TAG_SIZE]u8 = undefined;
    Aes256Gcm.encrypt(
        out[NONCE_SIZE..][0..plaintext.len],
        &tag,
        plaintext,
        "",
        nonce,
        key.*,
    );

    @memcpy(out[NONCE_SIZE + plaintext.len ..][0..TAG_SIZE], &tag);
    return total;
}

/// Encrypt with a caller-supplied nonce (for deterministic tests).
pub fn encryptWithNonce(plaintext: []const u8, key: *const [KEY_SIZE]u8, nonce: [NONCE_SIZE]u8, out: []u8) CryptoError!usize {
    const total = NONCE_SIZE + plaintext.len + TAG_SIZE;
    if (out.len < total) return CryptoError.BufferTooSmall;

    @memcpy(out[0..NONCE_SIZE], &nonce);

    var tag: [TAG_SIZE]u8 = undefined;
    Aes256Gcm.encrypt(
        out[NONCE_SIZE..][0..plaintext.len],
        &tag,
        plaintext,
        "",
        nonce,
        key.*,
    );
    @memcpy(out[NONCE_SIZE + plaintext.len ..][0..TAG_SIZE], &tag);
    return total;
}

/// Decrypt AES-256-GCM data.
/// Input format: nonce(12) || ciphertext || tag(16)
/// Returns plaintext length written.
pub fn decrypt(data: []const u8, key: *const [KEY_SIZE]u8, out: []u8) CryptoError!usize {
    if (data.len < NONCE_SIZE + TAG_SIZE) return CryptoError.InvalidData;

    const ct_len = data.len - NONCE_SIZE - TAG_SIZE;
    if (out.len < ct_len) return CryptoError.BufferTooSmall;

    const nonce: [NONCE_SIZE]u8 = data[0..NONCE_SIZE].*;
    const ciphertext = data[NONCE_SIZE..][0..ct_len];
    const tag: [TAG_SIZE]u8 = data[NONCE_SIZE + ct_len ..][0..TAG_SIZE].*;

    Aes256Gcm.decrypt(
        out[0..ct_len],
        ciphertext,
        tag,
        "",
        nonce,
        key.*,
    ) catch return CryptoError.DecryptFailed;

    return ct_len;
}

// ═══════════════════════════════════════════
//  ARGON2ID KEY DERIVATION
// ═══════════════════════════════════════════

/// Derive a vault key from password using Argon2id.
/// Params: t=3, m=65536 KiB (64 MiB), p=4. Must match Python exactly.
/// If salt_in is null, generates a random 16-byte salt.
/// Returns derived 32-byte key; salt is written to salt_out.
pub fn deriveVaultKey(
    allocator: Allocator,
    password: []const u8,
    salt_in: ?*const [ARGON2_SALT_SIZE]u8,
    out_key: *[KEY_SIZE]u8,
    out_salt: *[ARGON2_SALT_SIZE]u8,
) CryptoError!void {
    if (salt_in) |s| {
        out_salt.* = s.*;
    } else {
        std.crypto.random.bytes(out_salt);
    }
    const argon2 = std.crypto.pwhash.argon2;
    argon2.kdf(
        allocator,
        out_key,
        password,
        &out_salt.*,
        .{ .t = 3, .m = 65536, .p = 4 },
        .argon2id,
    ) catch return CryptoError.ArgonFailed;
}

/// Hash a PIN with Argon2id (lighter params for interactive use).
/// Params: t=2, m=19456 KiB (~19 MiB), p=1. Must match Python exactly.
/// Output format: hex(salt) + "$" + hex(hash) written to out_buf.
/// Returns bytes written.
pub fn hashPin(
    allocator: Allocator,
    pin: []const u8,
    out_buf: []u8,
) CryptoError!usize {
    var salt: [16]u8 = undefined;
    std.crypto.random.bytes(&salt);

    const argon2 = std.crypto.pwhash.argon2;
    var raw_hash: [32]u8 = undefined;
    argon2.kdf(
        allocator,
        &raw_hash,
        pin,
        &salt,
        .{ .t = 2, .m = 19456, .p = 1 },
        .argon2id,
    ) catch return CryptoError.ArgonFailed;

    // Format: hex(salt) + "$" + hex(hash) = 32 + 1 + 64 = 97 chars
    if (out_buf.len < 97) return CryptoError.BufferTooSmall;
    bytesToHex(&salt, out_buf[0..32]);
    out_buf[32] = '$';
    bytesToHex(&raw_hash, out_buf[33..97]);
    return 97;
}

/// Verify a PIN against its Argon2id hash (salt$hash hex format).
/// Returns true if match.
pub fn verifyPin(
    allocator: Allocator,
    pin: []const u8,
    pin_hash: []const u8,
) bool {
    // Find the '$' separator
    const sep = std.mem.indexOfScalar(u8, pin_hash, '$') orelse return false;
    if (sep != 32) return false; // salt hex is 32 chars (16 bytes)
    if (pin_hash.len != 97) return false; // 32 + 1 + 64

    var salt: [16]u8 = undefined;
    hexToBytes(pin_hash[0..32], &salt) catch return false;

    var expected: [32]u8 = undefined;
    hexToBytes(pin_hash[33..97], &expected) catch return false;

    const argon2 = std.crypto.pwhash.argon2;
    var raw_hash: [32]u8 = undefined;
    argon2.kdf(
        allocator,
        &raw_hash,
        pin,
        &salt,
        .{ .t = 2, .m = 19456, .p = 1 },
        .argon2id,
    ) catch return false;

    defer std.crypto.secureZero(u8, &raw_hash);
    return std.crypto.timing_safe.eql([32]u8, raw_hash, expected);
}

// ═══════════════════════════════════════════
//  ED25519
// ═══════════════════════════════════════════

/// Generate an Ed25519 keypair. Returns (seed, public_key) as 32-byte arrays.
pub fn ed25519Keygen() struct { seed: [32]u8, public_key: [32]u8 } {
    const kp = Ed25519.KeyPair.generate();
    return .{ .seed = kp.secret_key.seed(), .public_key = kp.public_key.bytes };
}

/// Reconstruct a KeyPair from a 32-byte seed by rebuilding the 64-byte SecretKey.
/// The SecretKey format is seed(32) || public_key(32).
fn keypairFromSeed(seed: *const [32]u8) CryptoError!Ed25519.KeyPair {
    // Derive public key from seed: SHA-512(seed) → clamp → basepoint mul
    const Sha512 = std.crypto.hash.sha2.Sha512;
    var expanded: [Sha512.digest_length]u8 = undefined;
    defer std.crypto.secureZero(u8, &expanded);
    Sha512.hash(seed, &expanded, .{});

    // Clamp the scalar (standard Ed25519 clamping)
    expanded[0] &= 248;
    expanded[31] &= 127;
    expanded[31] |= 64;

    // Scalar multiply with base point to get public key
    const Curve = std.crypto.ecc.Edwards25519;
    const pk_point = Curve.basePoint.mul(expanded[0..32].*) catch return CryptoError.Ed25519Failed;
    const pk_bytes = pk_point.toBytes();

    // Build 64-byte secret key: seed || pubkey
    var sk_bytes: [64]u8 = undefined;
    defer std.crypto.secureZero(u8, &sk_bytes);
    @memcpy(sk_bytes[0..32], seed);
    @memcpy(sk_bytes[32..64], &pk_bytes);

    const sk = Ed25519.SecretKey.fromBytes(sk_bytes) catch return CryptoError.Ed25519Failed;
    return Ed25519.KeyPair.fromSecretKey(sk) catch return CryptoError.Ed25519Failed;
}

/// Sign a message with an Ed25519 private key (32-byte seed).
/// Returns 64-byte signature.
pub fn ed25519Sign(msg: []const u8, seed: *const [32]u8) CryptoError![64]u8 {
    const kp = try keypairFromSeed(seed);
    const sig = kp.sign(msg, null) catch return CryptoError.Ed25519Failed;
    return sig.toBytes();
}

/// Verify an Ed25519 signature. Returns true if valid.
pub fn ed25519Verify(
    msg: []const u8,
    sig_bytes: *const [64]u8,
    pub_bytes: *const [32]u8,
) bool {
    const sig = Ed25519.Signature.fromBytes(sig_bytes.*);
    const pk = Ed25519.PublicKey.fromBytes(pub_bytes.*) catch return false;
    sig.verify(msg, pk) catch return false;
    return true;
}

// ═══════════════════════════════════════════
//  SHA-256
// ═══════════════════════════════════════════

/// SHA-256 hash → 64-char hex string.
pub fn sha256Hex(data: []const u8, out: *[64]u8) void {
    var hash: [Sha256.digest_length]u8 = undefined;
    Sha256.hash(data, &hash, .{});
    bytesToHex(&hash, out);
}

// ═══════════════════════════════════════════
//  BASE58BTC
// ═══════════════════════════════════════════

/// Encode bytes to base58btc. Returns characters written.
pub fn base58btcEncode(data: []const u8, out: []u8) usize {
    if (data.len == 0) return 0;

    // Count leading zero bytes → '1' characters
    var leading_zeros: usize = 0;
    for (data) |b| {
        if (b != 0) break;
        leading_zeros += 1;
    }

    // Working copy for repeated divmod
    var working: [128]u8 = undefined;
    if (data.len > working.len) return 0;
    @memcpy(working[0..data.len], data);
    const work = working[0..data.len];

    // Repeated divmod by 58
    var temp: [128]u8 = undefined;
    var temp_len: usize = 0;
    while (!allZero(work)) {
        temp[temp_len] = B58_ALPHABET[divmod58(work)];
        temp_len += 1;
    }

    // Write leading '1's + reversed digits
    var pos: usize = 0;
    for (0..leading_zeros) |_| {
        if (pos >= out.len) return pos;
        out[pos] = '1';
        pos += 1;
    }
    var i: usize = temp_len;
    while (i > 0) {
        i -= 1;
        if (pos >= out.len) return pos;
        out[pos] = temp[i];
        pos += 1;
    }
    return pos;
}

/// Decode base58btc string to bytes. Returns bytes written.
pub fn base58btcDecode(s: []const u8, out: []u8) CryptoError!usize {
    if (s.len == 0) return 0;

    // Count leading '1' → zero bytes
    var leading_zeros: usize = 0;
    for (s) |ch| {
        if (ch != '1') break;
        leading_zeros += 1;
    }

    // Multiply-and-add in little-endian working buffer
    var working: [128]u8 = [_]u8{0} ** 128;
    var work_len: usize = 1;

    for (s) |ch| {
        const idx = std.mem.indexOfScalar(u8, B58_ALPHABET, ch) orelse
            return CryptoError.Base58DecodeFailed;

        var carry: u16 = @intCast(idx);
        var j: usize = 0;
        while (j < work_len or carry > 0) : (j += 1) {
            if (j >= working.len) return CryptoError.BufferTooSmall;
            const val: u16 = @as(u16, working[j]) * 58 + carry;
            working[j] = @intCast(val & 0xFF);
            carry = val >> 8;
            if (j >= work_len) work_len = j + 1;
        }
    }

    // Trim trailing LE zeros (= leading BE zeros in the number)
    while (work_len > 0 and working[work_len - 1] == 0) {
        work_len -= 1;
    }

    const total = leading_zeros + work_len;
    if (out.len < total) return CryptoError.BufferTooSmall;

    // Leading zero bytes
    @memset(out[0..leading_zeros], 0);

    // Reverse LE → BE
    for (0..work_len) |i| {
        out[leading_zeros + i] = working[work_len - 1 - i];
    }

    return total;
}

// ═══════════════════════════════════════════
//  DID:KEY OPERATIONS
// ═══════════════════════════════════════════

/// Convert ed25519 public key to did:key string.
/// Format: did:key:z<base58btc(0xed01 + pubkey)>
/// Returns total chars written.
pub fn publicKeyToDid(pub_key: *const [32]u8, out: []u8) usize {
    // Build multicodec bytes: prefix(2) + key(32) = 34 bytes
    var mc: [34]u8 = undefined;
    mc[0] = ED25519_MC_PREFIX[0];
    mc[1] = ED25519_MC_PREFIX[1];
    @memcpy(mc[2..], pub_key);

    const prefix = "did:key:z";
    if (out.len < prefix.len) return 0;
    @memcpy(out[0..prefix.len], prefix);

    const b58_len = base58btcEncode(&mc, out[prefix.len..]);
    return prefix.len + b58_len;
}

/// Extract raw ed25519 public key bytes from did:key:z... string.
/// Returns 0 on success, writes 32 bytes to out_key.
pub fn didKeyToPublicKey(did: []const u8, out_key: *[32]u8) CryptoError!void {
    const prefix = "did:key:z";
    if (did.len <= prefix.len) return CryptoError.InvalidDid;
    if (!std.mem.startsWith(u8, did, prefix)) return CryptoError.InvalidDid;

    var mc_buf: [128]u8 = undefined;
    const mc_len = try base58btcDecode(did[prefix.len..], &mc_buf);

    // Expect 34 bytes: 2-byte multicodec prefix + 32-byte key
    if (mc_len != 34) return CryptoError.InvalidDid;
    if (mc_buf[0] != ED25519_MC_PREFIX[0] or mc_buf[1] != ED25519_MC_PREFIX[1])
        return CryptoError.InvalidDid;

    @memcpy(out_key, mc_buf[2..34]);
}

// ═══════════════════════════════════════════
//  BASE64URL (no padding)
// ═══════════════════════════════════════════

const base64url = std.base64.url_safe_no_pad;

/// Encode bytes to base64url (no padding). Returns chars written.
pub fn base64urlEncode(data: []const u8, out: []u8) usize {
    const needed = base64url.Encoder.calcSize(data.len);
    if (out.len < needed) return 0;
    _ = base64url.Encoder.encode(out, data);
    return needed;
}

/// Decode base64url (no padding) to bytes. Returns bytes written.
pub fn base64urlDecode(encoded: []const u8, out: []u8) CryptoError!usize {
    const needed = base64url.Decoder.calcSizeForSlice(encoded) catch
        return CryptoError.Base64DecodeFailed;
    if (out.len < needed) return CryptoError.BufferTooSmall;
    base64url.Decoder.decode(out, encoded) catch
        return CryptoError.Base64DecodeFailed;
    return needed;
}

// ═══════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════

fn bytesToHex(bytes: []const u8, out: []u8) void {
    const hex_chars = "0123456789abcdef";
    for (bytes, 0..) |b, i| {
        out[i * 2] = hex_chars[b >> 4];
        out[i * 2 + 1] = hex_chars[b & 0x0f];
    }
}

fn hexToBytes(hex: []const u8, out: []u8) !void {
    if (hex.len % 2 != 0) return error.InvalidHex;
    for (0..hex.len / 2) |i| {
        out[i] = (try hexVal(hex[i * 2])) << 4 | try hexVal(hex[i * 2 + 1]);
    }
}

fn hexVal(c: u8) !u8 {
    if (c >= '0' and c <= '9') return c - '0';
    if (c >= 'a' and c <= 'f') return c - 'a' + 10;
    if (c >= 'A' and c <= 'F') return c - 'A' + 10;
    return error.InvalidHex;
}

/// Divide big-endian byte array by 58 in-place. Returns remainder.
fn divmod58(data: []u8) u8 {
    var remainder: u16 = 0;
    for (data) |*b| {
        const acc: u16 = (remainder << 8) | @as(u16, b.*);
        b.* = @intCast(acc / 58);
        remainder = acc % 58;
    }
    return @intCast(remainder);
}

fn allZero(data: []const u8) bool {
    for (data) |b| {
        if (b != 0) return false;
    }
    return true;
}
