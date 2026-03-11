// session.zig — In-memory session store replacing Python's sessions dict.
// Uses StringHashMap for O(1) token lookup and lazy TTL cleanup.
// Phase 2 hardening: fingerprint binding, inactivity timeout, per-user session cap.

const std = @import("std");
const crypto_mod = @import("crypto.zig");
const Sha256 = std.crypto.hash.sha2.Sha256;
const Allocator = std.mem.Allocator;

pub const SESSION_TTL: i64 = 86400; // 24 hours in seconds
pub const MAX_LOGIN_ATTEMPTS: usize = 10; // per window
pub const LOGIN_WINDOW: i64 = 300; // 5 minutes in seconds
pub const TOKEN_BYTES = 32; // random bytes for token generation
pub const MAX_SESSIONS_PER_USER: usize = 10;
pub const INACTIVITY_TIMEOUT: i64 = 3600; // 1 hour

pub const SessionError = error{
    OutOfMemory,
    BufferTooSmall,
    TokenGenerationFailed,
};

const ZERO_HASH: [32]u8 = [_]u8{0} ** 32;

const Session = struct {
    user_id_buf: [128]u8,
    user_id_len: usize,
    created_at: i64, // unix epoch seconds
    last_activity_at: i64, // sliding window (inactivity timeout)
    fingerprint_hash: [32]u8, // SHA-256(user_agent + "|" + client_ip)

    fn getUserId(self: *const Session) []const u8 {
        return self.user_id_buf[0..self.user_id_len];
    }

    fn isLegacyFingerprint(self: *const Session) bool {
        return std.mem.eql(u8, &self.fingerprint_hash, &ZERO_HASH);
    }
};

pub const SessionStore = struct {
    // token (heap-duped) → Session
    sessions: std.StringHashMapUnmanaged(Session),
    // ip (heap-duped) → list of attempt timestamps
    login_attempts: std.StringHashMapUnmanaged(std.ArrayListUnmanaged(i64)),
    allocator: Allocator,
    /// Protects sessions + login_attempts from concurrent access (thread-per-connection model).
    mutex: std.Thread.Mutex = .{},

    pub fn init(allocator: Allocator) SessionStore {
        return .{
            .sessions = .{},
            .login_attempts = .{},
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *SessionStore) void {
        // Free all session keys
        var s_it = self.sessions.iterator();
        while (s_it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
        }
        self.sessions.deinit(self.allocator);

        // Free all login attempt keys and lists
        var l_it = self.login_attempts.iterator();
        while (l_it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
            entry.value_ptr.deinit(self.allocator);
        }
        self.login_attempts.deinit(self.allocator);
    }

    /// Create a new session with fingerprint binding.
    /// Token is base64url-encoded 32 random bytes (~43 chars).
    /// Enforces MAX_SESSIONS_PER_USER — evicts oldest (by last_activity_at) if at cap.
    pub fn createSession(self: *SessionStore, user_id: []const u8, fingerprint: []const u8, out_token: []u8) SessionError!usize {
        self.mutex.lock();
        defer self.mutex.unlock();
        return self.createSessionLocked(user_id, fingerprint, out_token);
    }

    fn createSessionLocked(self: *SessionStore, user_id: []const u8, fingerprint: []const u8, out_token: []u8) SessionError!usize {
        if (user_id.len > 128) return SessionError.BufferTooSmall;

        // Enforce per-user session cap — evict oldest if at limit
        self.evictOldestIfNeeded(user_id);

        // Generate random token
        var raw: [TOKEN_BYTES]u8 = undefined;
        std.crypto.random.bytes(&raw);

        // Base64url encode
        const token_len = crypto_mod.base64urlEncode(&raw, out_token);
        if (token_len == 0) return SessionError.BufferTooSmall;
        const token_slice = out_token[0..token_len];

        // Heap-dup the token for map key
        const owned_token = self.allocator.dupe(u8, token_slice) catch
            return SessionError.OutOfMemory;

        const now = std.time.timestamp();
        var sess = Session{
            .user_id_buf = undefined,
            .user_id_len = user_id.len,
            .created_at = now,
            .last_activity_at = now,
            .fingerprint_hash = computeFingerprintHash(fingerprint),
        };
        @memcpy(sess.user_id_buf[0..user_id.len], user_id);

        self.sessions.put(self.allocator, owned_token, sess) catch {
            self.allocator.free(owned_token);
            return SessionError.OutOfMemory;
        };

        return token_len;
    }

    /// Validate a session token with fingerprint verification.
    /// Checks TTL, inactivity timeout, and fingerprint binding.
    /// On success, updates last_activity_at (sliding window).
    /// If stored fingerprint_hash is all-zeros (legacy/test), skips fingerprint check.
    pub fn validateSession(self: *SessionStore, token: []const u8, fingerprint: []const u8) ?[]const u8 {
        self.mutex.lock();
        defer self.mutex.unlock();
        const entry_ptr = self.sessions.getPtr(token) orelse return null;
        const now = std.time.timestamp();

        // Check absolute TTL
        if (now - entry_ptr.created_at > SESSION_TTL) {
            if (self.sessions.fetchRemove(token)) |removed| {
                self.allocator.free(removed.key);
            }
            return null;
        }

        // Check inactivity timeout
        if (now - entry_ptr.last_activity_at > INACTIVITY_TIMEOUT) {
            if (self.sessions.fetchRemove(token)) |removed| {
                self.allocator.free(removed.key);
            }
            return null;
        }

        // Verify fingerprint (skip for legacy/test sessions with all-zero hash)
        if (!entry_ptr.isLegacyFingerprint()) {
            const provided_hash = computeFingerprintHash(fingerprint);
            if (!std.crypto.timing_safe.eql([32]u8, provided_hash, entry_ptr.fingerprint_hash)) {
                return null;
            }
        }

        // Sliding window — update last activity
        entry_ptr.last_activity_at = now;

        return entry_ptr.getUserId();
    }

    /// Remove a session by token.
    pub fn invalidateSession(self: *SessionStore, token: []const u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.sessions.fetchRemove(token)) |removed| {
            self.allocator.free(removed.key);
        }
    }

    /// Remove all sessions for a user.
    pub fn invalidateUserSessions(self: *SessionStore, user_id: []const u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        // Collect tokens to remove (can't modify during iteration)
        var to_remove: [256][]const u8 = undefined;
        var remove_count: usize = 0;

        var it = self.sessions.iterator();
        while (it.next()) |entry| {
            if (std.mem.eql(u8, entry.value_ptr.getUserId(), user_id)) {
                if (remove_count < 256) {
                    to_remove[remove_count] = entry.key_ptr.*;
                    remove_count += 1;
                }
            }
        }

        for (to_remove[0..remove_count]) |token| {
            if (self.sessions.fetchRemove(token)) |removed| {
                self.allocator.free(removed.key);
            }
        }
    }

    /// Check login rate limit. Returns true if allowed, false if rate limited.
    pub fn checkLoginRateLimit(self: *SessionStore, ip: []const u8) SessionError!bool {
        self.mutex.lock();
        defer self.mutex.unlock();
        const now = std.time.timestamp();
        const window_start = now - LOGIN_WINDOW;

        if (self.login_attempts.getPtr(ip)) |list| {
            // Prune old attempts
            var write: usize = 0;
            for (list.items) |ts| {
                if (ts > window_start) {
                    list.items[write] = ts;
                    write += 1;
                }
            }
            list.shrinkRetainingCapacity(write);

            if (list.items.len >= MAX_LOGIN_ATTEMPTS) {
                return false;
            }

            list.append(self.allocator, now) catch return SessionError.OutOfMemory;
        } else {
            // First attempt from this IP
            const owned_ip = self.allocator.dupe(u8, ip) catch return SessionError.OutOfMemory;
            var list = std.ArrayListUnmanaged(i64){};
            list.append(self.allocator, now) catch {
                self.allocator.free(owned_ip);
                return SessionError.OutOfMemory;
            };
            self.login_attempts.put(self.allocator, owned_ip, list) catch {
                list.deinit(self.allocator);
                self.allocator.free(owned_ip);
                return SessionError.OutOfMemory;
            };
        }
        return true;
    }

    /// Reset all state (test helper).
    pub fn reset(self: *SessionStore) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        var s_it = self.sessions.iterator();
        while (s_it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
        }
        self.sessions.clearRetainingCapacity();

        var l_it = self.login_attempts.iterator();
        while (l_it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
            entry.value_ptr.deinit(self.allocator);
        }
        self.login_attempts.clearRetainingCapacity();
    }

    /// Inject a session (test helper for fixture compat).
    /// Pass empty fingerprint ("") for legacy/test sessions (stores all-zeros hash, skips verification).
    pub fn injectSession(self: *SessionStore, token: []const u8, user_id: []const u8, fingerprint: []const u8) SessionError!void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (user_id.len > 128) return SessionError.BufferTooSmall;

        const now = std.time.timestamp();
        var sess = Session{
            .user_id_buf = undefined,
            .user_id_len = user_id.len,
            .created_at = now,
            .last_activity_at = now,
            .fingerprint_hash = computeFingerprintHash(fingerprint),
        };
        @memcpy(sess.user_id_buf[0..user_id.len], user_id);

        // If token already exists, just update the value (key is already owned)
        if (self.sessions.getPtr(token)) |existing| {
            existing.* = sess;
            return;
        }

        const owned_token = self.allocator.dupe(u8, token) catch return SessionError.OutOfMemory;
        self.sessions.put(self.allocator, owned_token, sess) catch {
            self.allocator.free(owned_token);
            return SessionError.OutOfMemory;
        };
    }

    /// Count active (non-expired) sessions for a user.
    pub fn countUserSessions(self: *SessionStore, user_id: []const u8) usize {
        self.mutex.lock();
        defer self.mutex.unlock();
        var count: usize = 0;
        const now = std.time.timestamp();
        var it = self.sessions.iterator();
        while (it.next()) |kv| {
            if (std.mem.eql(u8, kv.value_ptr.getUserId(), user_id)) {
                // Only count non-expired sessions
                if (now - kv.value_ptr.created_at <= SESSION_TTL) {
                    count += 1;
                }
            }
        }
        return count;
    }

    // ── Private helpers ──

    /// Compute SHA-256 of fingerprint string. Returns all-zeros for empty input (legacy/test).
    fn computeFingerprintHash(fingerprint: []const u8) [32]u8 {
        if (fingerprint.len == 0) return ZERO_HASH;
        var hash: [32]u8 = undefined;
        Sha256.hash(fingerprint, &hash, .{});
        return hash;
    }

    /// If user has >= MAX_SESSIONS_PER_USER sessions, evict the one with lowest last_activity_at.
    fn evictOldestIfNeeded(self: *SessionStore, user_id: []const u8) void {
        var count: usize = 0;
        var oldest_token: ?[]const u8 = null;
        var oldest_activity: i64 = std.math.maxInt(i64);

        var it = self.sessions.iterator();
        while (it.next()) |kv| {
            if (std.mem.eql(u8, kv.value_ptr.getUserId(), user_id)) {
                count += 1;
                if (kv.value_ptr.last_activity_at < oldest_activity) {
                    oldest_activity = kv.value_ptr.last_activity_at;
                    oldest_token = kv.key_ptr.*;
                }
            }
        }

        if (count >= MAX_SESSIONS_PER_USER) {
            if (oldest_token) |token| {
                if (self.sessions.fetchRemove(token)) |removed| {
                    self.allocator.free(removed.key);
                }
            }
        }
    }
};
