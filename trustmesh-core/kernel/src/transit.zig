// transit.zig — In-memory keyring where keys never leave Zig.
// Python stores keys by user_id, then calls encrypt/decrypt by handle.
// Keys never cross the FFI boundary after initial store.

const std = @import("std");
const crypto_mod = @import("crypto.zig");
const Allocator = std.mem.Allocator;

const Aes256Gcm = std.crypto.aead.aes_gcm.Aes256Gcm;
const KEY_SIZE = crypto_mod.KEY_SIZE;
const NONCE_SIZE = crypto_mod.NONCE_SIZE;
const TAG_SIZE = crypto_mod.TAG_SIZE;

pub const MAX_USERS: usize = 256;
pub const MAX_VERSIONS: usize = 8;
pub const VERSION_PREFIX_MAX: usize = 8; // "v255." = max 5 chars

pub const TransitError = error{
    NotInitialized,
    UserNotFound,
    KeyNotFound,
    StoreFull,
    VersionsFull,
    BufferTooSmall,
    EncryptFailed,
    DecryptFailed,
    InvalidVersionPrefix,
    InvalidData,
};

const KeySlot = struct {
    version: u32,
    key: [KEY_SIZE]u8,
    created_at: i64,
    is_active: bool,

    fn secureZero(self: *KeySlot) void {
        std.crypto.secureZero(u8, &self.key);
        self.version = 0;
        self.created_at = 0;
        self.is_active = false;
    }
};

const UserKeyRing = struct {
    user_id_buf: [128]u8,
    user_id_len: usize,
    slots: [MAX_VERSIONS]KeySlot,
    slot_count: u32,
    next_version: u32,

    fn init() UserKeyRing {
        return .{
            .user_id_buf = undefined,
            .user_id_len = 0,
            .slots = [_]KeySlot{.{
                .version = 0,
                .key = [_]u8{0} ** KEY_SIZE,
                .created_at = 0,
                .is_active = false,
            }} ** MAX_VERSIONS,
            .slot_count = 0,
            .next_version = 0,
        };
    }

    fn getUserId(self: *const UserKeyRing) []const u8 {
        return self.user_id_buf[0..self.user_id_len];
    }

    fn activeSlot(self: *const UserKeyRing) ?*const KeySlot {
        for (&self.slots) |*slot| {
            if (slot.is_active) return slot;
        }
        return null;
    }

    fn findVersion(self: *const UserKeyRing, version: u32) ?*const KeySlot {
        for (&self.slots) |*slot| {
            if (slot.version == version and slot.created_at != 0) return slot;
        }
        return null;
    }

    fn secureZeroAll(self: *UserKeyRing) void {
        for (&self.slots) |*slot| {
            slot.secureZero();
        }
        std.crypto.secureZero(u8, self.user_id_buf[0..self.user_id_len]);
        self.user_id_len = 0;
        self.slot_count = 0;
        self.next_version = 0;
    }
};

pub const TransitEngine = struct {
    rings: [MAX_USERS]UserKeyRing,
    ring_count: usize,
    allocator: Allocator,
    /// Protects rings from concurrent access (thread-per-connection model).
    mutex: std.Thread.Mutex = .{},

    pub fn init(allocator: Allocator) TransitEngine {
        return .{
            .rings = [_]UserKeyRing{UserKeyRing.init()} ** MAX_USERS,
            .ring_count = 0,
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *TransitEngine) void {
        for (self.rings[0..self.ring_count]) |*ring| {
            ring.secureZeroAll();
        }
        self.ring_count = 0;
    }

    fn findRing(self: *TransitEngine, user_id: []const u8) ?*UserKeyRing {
        for (self.rings[0..self.ring_count]) |*ring| {
            if (ring.user_id_len == user_id.len and
                std.mem.eql(u8, ring.getUserId(), user_id))
            {
                return ring;
            }
        }
        return null;
    }

    /// Store a key for a user. Returns version number.
    /// If user doesn't exist, creates a new ring. If exists, adds a new version.
    pub fn storeKey(self: *TransitEngine, user_id: []const u8, key: *const [KEY_SIZE]u8) TransitError!u32 {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (user_id.len > 128 or user_id.len == 0) return TransitError.BufferTooSmall;

        if (self.findRing(user_id)) |ring| {
            return self.addKeyToRing(ring, key);
        }

        // New user
        if (self.ring_count >= MAX_USERS) return TransitError.StoreFull;
        const ring = &self.rings[self.ring_count];
        ring.* = UserKeyRing.init();
        @memcpy(ring.user_id_buf[0..user_id.len], user_id);
        ring.user_id_len = user_id.len;
        self.ring_count += 1;
        return self.addKeyToRing(ring, key);
    }

    fn addKeyToRing(self: *TransitEngine, ring: *UserKeyRing, key: *const [KEY_SIZE]u8) TransitError!u32 {
        _ = self;
        if (ring.slot_count >= MAX_VERSIONS) return TransitError.VersionsFull;

        // Deactivate previous active key
        for (&ring.slots) |*slot| {
            if (slot.is_active) slot.is_active = false;
        }

        const version = ring.next_version;
        const slot = &ring.slots[ring.slot_count];
        slot.version = version;
        @memcpy(&slot.key, key);
        slot.created_at = std.time.timestamp();
        slot.is_active = true;
        ring.slot_count += 1;
        ring.next_version += 1;
        return version;
    }

    /// Encrypt plaintext for a user with AAD. Output: "v{N}.{nonce}{ciphertext}{tag}"
    /// Returns total bytes written.
    pub fn encryptForUser(
        self: *TransitEngine,
        user_id: []const u8,
        plaintext: []const u8,
        aad: []const u8,
        out: []u8,
    ) TransitError!usize {
        self.mutex.lock();
        defer self.mutex.unlock();
        const ring = self.findRing(user_id) orelse return TransitError.UserNotFound;
        const slot = ring.activeSlot() orelse return TransitError.KeyNotFound;

        // Write version prefix: "v{N}."
        const prefix_len = writeVersionPrefix(slot.version, out) catch return TransitError.BufferTooSmall;

        const crypto_len = NONCE_SIZE + plaintext.len + TAG_SIZE;
        const total = prefix_len + crypto_len;
        if (out.len < total) return TransitError.BufferTooSmall;

        // Random nonce
        var nonce: [NONCE_SIZE]u8 = undefined;
        std.crypto.random.bytes(&nonce);

        const dest = out[prefix_len..];
        @memcpy(dest[0..NONCE_SIZE], &nonce);

        // Encrypt with AAD
        var tag: [TAG_SIZE]u8 = undefined;
        Aes256Gcm.encrypt(
            dest[NONCE_SIZE..][0..plaintext.len],
            &tag,
            plaintext,
            aad,
            nonce,
            slot.key,
        );
        @memcpy(dest[NONCE_SIZE + plaintext.len ..][0..TAG_SIZE], &tag);

        return total;
    }

    /// Decrypt ciphertext for a user with AAD.
    /// Handles versioned ("v{N}.{data}") and legacy (raw data, version 0, empty AAD) formats.
    pub fn decryptForUser(
        self: *TransitEngine,
        user_id: []const u8,
        ciphertext: []const u8,
        aad: []const u8,
        out: []u8,
    ) TransitError!usize {
        self.mutex.lock();
        defer self.mutex.unlock();
        const ring = self.findRing(user_id) orelse return TransitError.UserNotFound;

        // Check for version prefix "v{N}."
        if (ciphertext.len > 2 and ciphertext[0] == 'v') {
            if (parseVersionPrefix(ciphertext)) |parsed| {
                const version = parsed.version;
                const data = ciphertext[parsed.prefix_len..];
                const slot = ring.findVersion(version) orelse return TransitError.KeyNotFound;
                return decryptWithKey(data, &slot.key, aad, out);
            }
        }

        // Legacy format: no version prefix, use version 0, empty AAD
        const slot = ring.findVersion(0) orelse {
            // Try active key as last resort
            const active = ring.activeSlot() orelse return TransitError.KeyNotFound;
            return decryptWithKey(ciphertext, &active.key, "", out);
        };
        return decryptWithKey(ciphertext, &slot.key, "", out);
    }

    /// Rotate key for a user. Returns new version number.
    pub fn rotateKey(self: *TransitEngine, user_id: []const u8) TransitError!u32 {
        self.mutex.lock();
        defer self.mutex.unlock();
        const ring = self.findRing(user_id) orelse return TransitError.UserNotFound;
        if (ring.slot_count >= MAX_VERSIONS) return TransitError.VersionsFull;

        // Generate new key
        var new_key: [KEY_SIZE]u8 = undefined;
        std.crypto.random.bytes(&new_key);
        defer std.crypto.secureZero(u8, &new_key);

        return self.addKeyToRing(ring, &new_key);
    }

    /// Remove all keys for a user. secureZero all material.
    pub fn removeUser(self: *TransitEngine, user_id: []const u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        var idx: usize = 0;
        while (idx < self.ring_count) {
            if (self.rings[idx].user_id_len == user_id.len and
                std.mem.eql(u8, self.rings[idx].getUserId(), user_id))
            {
                self.rings[idx].secureZeroAll();
                // Swap with last
                if (idx < self.ring_count - 1) {
                    self.rings[idx] = self.rings[self.ring_count - 1];
                    self.rings[self.ring_count - 1].secureZeroAll();
                }
                self.ring_count -= 1;
                return;
            }
            idx += 1;
        }
    }

    /// Check if a user has a key loaded.
    pub fn hasKey(self: *TransitEngine, user_id: []const u8) bool {
        self.mutex.lock();
        defer self.mutex.unlock();
        return self.findRing(user_id) != null;
    }
};

// ═══════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════

const VersionParsed = struct {
    version: u32,
    prefix_len: usize,
};

fn parseVersionPrefix(data: []const u8) ?VersionParsed {
    if (data.len < 3 or data[0] != 'v') return null;

    // Find the '.'
    var dot_idx: usize = 1;
    while (dot_idx < data.len and dot_idx < 8) : (dot_idx += 1) {
        if (data[dot_idx] == '.') break;
    }
    if (dot_idx >= data.len or data[dot_idx] != '.') return null;

    // Parse version number
    const version_str = data[1..dot_idx];
    if (version_str.len == 0) return null;
    var version: u32 = 0;
    for (version_str) |ch| {
        if (ch < '0' or ch > '9') return null;
        version = version * 10 + @as(u32, ch - '0');
    }

    return .{
        .version = version,
        .prefix_len = dot_idx + 1,
    };
}

fn writeVersionPrefix(version: u32, out: []u8) !usize {
    // Format: "v{N}."
    var buf: [16]u8 = undefined;
    const s = std.fmt.bufPrint(&buf, "v{d}.", .{version}) catch return error.BufferTooSmall;
    if (out.len < s.len) return error.BufferTooSmall;
    @memcpy(out[0..s.len], s);
    return s.len;
}

fn decryptWithKey(data: []const u8, key: *const [KEY_SIZE]u8, aad: []const u8, out: []u8) TransitError!usize {
    if (data.len < NONCE_SIZE + TAG_SIZE) return TransitError.InvalidData;

    const ct_len = data.len - NONCE_SIZE - TAG_SIZE;
    if (out.len < ct_len) return TransitError.BufferTooSmall;

    const nonce: [NONCE_SIZE]u8 = data[0..NONCE_SIZE].*;
    const ciphertext = data[NONCE_SIZE..][0..ct_len];
    const tag: [TAG_SIZE]u8 = data[NONCE_SIZE + ct_len ..][0..TAG_SIZE].*;

    Aes256Gcm.decrypt(
        out[0..ct_len],
        ciphertext,
        tag,
        aad,
        nonce,
        key.*,
    ) catch return TransitError.DecryptFailed;

    return ct_len;
}

// ═══════════════════════════════════════════
//  UNIT TESTS
// ═══════════════════════════════════════════

test "TransitEngine: store and encrypt/decrypt roundtrip" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    const user_id = "user-001";
    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);

    const version = try engine.storeKey(user_id, &key);
    try std.testing.expectEqual(@as(u32, 0), version);
    try std.testing.expect(engine.hasKey(user_id));

    const plaintext = "Hello, Transit Engine!";
    const aad = "capsule-123|user-001";

    var ct_buf: [256]u8 = undefined;
    const ct_len = try engine.encryptForUser(user_id, plaintext, aad, &ct_buf);

    var pt_buf: [256]u8 = undefined;
    const pt_len = try engine.decryptForUser(user_id, ct_buf[0..ct_len], aad, &pt_buf);
    try std.testing.expectEqualStrings(plaintext, pt_buf[0..pt_len]);
}

test "TransitEngine: version prefix parsing" {
    const parsed = parseVersionPrefix("v0.data");
    try std.testing.expect(parsed != null);
    try std.testing.expectEqual(@as(u32, 0), parsed.?.version);
    try std.testing.expectEqual(@as(usize, 3), parsed.?.prefix_len);

    const p2 = parseVersionPrefix("v123.data");
    try std.testing.expect(p2 != null);
    try std.testing.expectEqual(@as(u32, 123), p2.?.version);

    try std.testing.expect(parseVersionPrefix("not-versioned") == null);
    try std.testing.expect(parseVersionPrefix("v.data") == null);
    try std.testing.expect(parseVersionPrefix("") == null);
}

test "TransitEngine: rotate key and decrypt with old version" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    const user_id = "user-rotate";
    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);

    _ = try engine.storeKey(user_id, &key);

    // Encrypt with v0
    const plaintext = "secret data v0";
    var ct_buf: [256]u8 = undefined;
    const ct_len = try engine.encryptForUser(user_id, plaintext, "", &ct_buf);

    // Rotate to v1
    const new_version = try engine.rotateKey(user_id);
    try std.testing.expectEqual(@as(u32, 1), new_version);

    // Old ciphertext still decryptable (v0 key still in ring)
    var pt_buf: [256]u8 = undefined;
    const pt_len = try engine.decryptForUser(user_id, ct_buf[0..ct_len], "", &pt_buf);
    try std.testing.expectEqualStrings(plaintext, pt_buf[0..pt_len]);
}

test "TransitEngine: remove user securely zeros" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);
    _ = try engine.storeKey("user-to-remove", &key);
    try std.testing.expect(engine.hasKey("user-to-remove"));

    engine.removeUser("user-to-remove");
    try std.testing.expect(!engine.hasKey("user-to-remove"));
}

test "TransitEngine: legacy ciphertext (no version prefix)" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    const user_id = "user-legacy";
    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);
    _ = try engine.storeKey(user_id, &key);

    // Encrypt raw without version prefix (simulating legacy)
    const plaintext = "legacy data";
    var raw_ct: [256]u8 = undefined;
    const raw_len = try crypto_mod.encrypt(plaintext, &key, &raw_ct);

    // Decrypt should succeed with legacy path (version 0, empty AAD)
    var pt_buf: [256]u8 = undefined;
    const pt_len = try engine.decryptForUser(user_id, raw_ct[0..raw_len], "", &pt_buf);
    try std.testing.expectEqualStrings(plaintext, pt_buf[0..pt_len]);
}

test "TransitEngine: AAD mismatch fails" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);
    _ = try engine.storeKey("user-aad", &key);

    var ct_buf: [256]u8 = undefined;
    const ct_len = try engine.encryptForUser("user-aad", "secret", "correct-aad", &ct_buf);

    // Decrypt with wrong AAD should fail
    var pt_buf: [256]u8 = undefined;
    const result = engine.decryptForUser("user-aad", ct_buf[0..ct_len], "wrong-aad", &pt_buf);
    try std.testing.expectError(TransitError.DecryptFailed, result);
}

test "TransitEngine: unknown user returns error" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var ct_buf: [256]u8 = undefined;
    const result = engine.encryptForUser("nonexistent", "data", "", &ct_buf);
    try std.testing.expectError(TransitError.UserNotFound, result);
}

test "TransitEngine: store full returns error" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key);

    // Fill all slots
    for (0..MAX_USERS) |i| {
        var uid_buf: [32]u8 = undefined;
        const uid_len = std.fmt.bufPrint(&uid_buf, "user-{d}", .{i}) catch unreachable;
        _ = try engine.storeKey(uid_len, &key);
    }

    // One more should fail
    const result = engine.storeKey("overflow-user", &key);
    try std.testing.expectError(TransitError.StoreFull, result);
}

test "TransitEngine: multiple users independent" {
    var engine = TransitEngine.init(std.testing.allocator);
    defer engine.deinit();

    var key1: [KEY_SIZE]u8 = undefined;
    var key2: [KEY_SIZE]u8 = undefined;
    std.crypto.random.bytes(&key1);
    std.crypto.random.bytes(&key2);

    _ = try engine.storeKey("alice", &key1);
    _ = try engine.storeKey("bob", &key2);

    // Encrypt for alice
    var ct: [256]u8 = undefined;
    const ct_len = try engine.encryptForUser("alice", "alice-secret", "aad", &ct);

    // Bob can't decrypt alice's data (wrong key)
    var pt: [256]u8 = undefined;
    const result = engine.decryptForUser("bob", ct[0..ct_len], "aad", &pt);
    try std.testing.expectError(TransitError.DecryptFailed, result);
}
