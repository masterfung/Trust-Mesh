// test_session.zig — Tests for in-memory session store.
// Phase 2: fingerprint binding, inactivity timeout, per-user session cap.

const std = @import("std");
const testing = std.testing;
const podos = @import("podos");
const session_mod = podos.session;

// ── Basic session CRUD (updated signatures with empty fingerprint for backward compat) ──

test "session: create and validate" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    var token_buf: [64]u8 = undefined;
    const token_len = try store.createSession("user-42", "", &token_buf);
    const token = token_buf[0..token_len];
    try testing.expect(token_len > 0);

    // Validate returns user_id (empty fingerprint = legacy, skips check)
    const uid = store.validateSession(token, "");
    try testing.expect(uid != null);
    try testing.expectEqualStrings("user-42", uid.?);
}

test "session: invalid token returns null" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    const uid = store.validateSession("nonexistent-token", "");
    try testing.expect(uid == null);
}

test "session: invalidate removes session" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    var token_buf: [64]u8 = undefined;
    const token_len = try store.createSession("user-1", "", &token_buf);
    const token = token_buf[0..token_len];

    // Valid before invalidation
    try testing.expect(store.validateSession(token, "") != null);

    // Invalidate
    store.invalidateSession(token);

    // Gone after invalidation
    try testing.expect(store.validateSession(token, "") == null);
}

test "session: invalidate user removes all sessions" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    var t1: [64]u8 = undefined;
    var t2: [64]u8 = undefined;
    var t3: [64]u8 = undefined;
    const len1 = try store.createSession("user-x", "", &t1);
    const len2 = try store.createSession("user-x", "", &t2);
    const len3 = try store.createSession("user-y", "", &t3);

    // All valid
    try testing.expect(store.validateSession(t1[0..len1], "") != null);
    try testing.expect(store.validateSession(t2[0..len2], "") != null);
    try testing.expect(store.validateSession(t3[0..len3], "") != null);

    // Invalidate user-x
    store.invalidateUserSessions("user-x");

    // user-x sessions gone, user-y still valid
    try testing.expect(store.validateSession(t1[0..len1], "") == null);
    try testing.expect(store.validateSession(t2[0..len2], "") == null);
    try testing.expect(store.validateSession(t3[0..len3], "") != null);
}

test "session: inject and validate (legacy, empty fingerprint)" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    try store.injectSession("test-token-abc", "injected-user", "");
    const uid = store.validateSession("test-token-abc", "");
    try testing.expect(uid != null);
    try testing.expectEqualStrings("injected-user", uid.?);
}

test "session: reset clears all" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    var t1: [64]u8 = undefined;
    const len1 = try store.createSession("user-1", "", &t1);

    store.reset();
    try testing.expect(store.validateSession(t1[0..len1], "") == null);
}

test "session: login rate limit allows under threshold" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // First attempt should be allowed
    const allowed = try store.checkLoginRateLimit("192.168.1.1");
    try testing.expect(allowed);
}

test "session: login rate limit blocks after max" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Fill up to max
    for (0..session_mod.MAX_LOGIN_ATTEMPTS) |_| {
        _ = try store.checkLoginRateLimit("10.0.0.1");
    }

    // Next should be blocked
    const allowed = try store.checkLoginRateLimit("10.0.0.1");
    try testing.expect(!allowed);
}

test "session: login rate limit separate IPs" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Fill up IP-A
    for (0..session_mod.MAX_LOGIN_ATTEMPTS) |_| {
        _ = try store.checkLoginRateLimit("ip-a");
    }

    // IP-B should still be allowed
    const allowed = try store.checkLoginRateLimit("ip-b");
    try testing.expect(allowed);
}

test "session: multiple sessions for same user" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    var t1: [64]u8 = undefined;
    var t2: [64]u8 = undefined;
    const len1 = try store.createSession("user-1", "", &t1);
    const len2 = try store.createSession("user-1", "", &t2);

    // Both should be valid and return same user
    const uid1 = store.validateSession(t1[0..len1], "").?;
    const uid2 = store.validateSession(t2[0..len2], "").?;
    try testing.expectEqualStrings("user-1", uid1);
    try testing.expectEqualStrings("user-1", uid2);

    // Tokens should be different
    try testing.expect(!std.mem.eql(u8, t1[0..len1], t2[0..len2]));
}

test "session: invalidate nonexistent token is noop" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Should not crash or leak
    store.invalidateSession("does-not-exist");
    store.invalidateSession("");
}

test "session: invalidate user with no sessions is noop" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // No sessions created yet — should not crash
    store.invalidateUserSessions("ghost-user");
}

test "session: inject overwrite existing token" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    try store.injectSession("fixed-token", "user-a", "");
    try testing.expectEqualStrings("user-a", store.validateSession("fixed-token", "").?);

    // Inject same token with different user
    try store.injectSession("fixed-token", "user-b", "");
    try testing.expectEqualStrings("user-b", store.validateSession("fixed-token", "").?);
}

test "session: create many sessions" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Create sessions for multiple users (stay under per-user cap)
    var tokens: [50][64]u8 = undefined;
    var lengths: [50]usize = undefined;

    for (0..50) |i| {
        // Use 5 different users to stay under MAX_SESSIONS_PER_USER
        var user_buf: [16]u8 = undefined;
        const user_len = std.fmt.bufPrint(&user_buf, "user-{d}", .{i % 5}) catch unreachable;
        lengths[i] = try store.createSession(user_len, "", &tokens[i]);
    }

    // Validate the last MAX_SESSIONS_PER_USER per user should be valid
    // (earlier ones may have been evicted)
    var valid_count: usize = 0;
    for (0..50) |i| {
        const uid = store.validateSession(tokens[i][0..lengths[i]], "");
        if (uid != null) valid_count += 1;
    }
    // At most 5 users * 10 sessions = 50, but eviction means <= 50
    try testing.expect(valid_count > 0);
    try testing.expect(valid_count <= 50);

    // Invalidate all users
    for (0..5) |i| {
        var user_buf: [16]u8 = undefined;
        const user_len = std.fmt.bufPrint(&user_buf, "user-{d}", .{i}) catch unreachable;
        store.invalidateUserSessions(user_len);
    }

    // All should be gone
    for (0..50) |i| {
        try testing.expect(store.validateSession(tokens[i][0..lengths[i]], "") == null);
    }
}

test "session: reset also clears login attempts" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Fill up rate limit
    for (0..session_mod.MAX_LOGIN_ATTEMPTS) |_| {
        _ = try store.checkLoginRateLimit("10.0.0.1");
    }
    try testing.expect(!(try store.checkLoginRateLimit("10.0.0.1")));

    // Reset clears everything
    store.reset();
    try testing.expect(try store.checkLoginRateLimit("10.0.0.1"));
}

test "session: token length is consistent" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // base64url of 32 bytes = 43 chars
    var t: [64]u8 = undefined;
    const len = try store.createSession("user-1", "", &t);
    try testing.expectEqual(@as(usize, 43), len);
}

// ══════════════════════════════════════════════
//  Phase 2: Fingerprint binding tests
// ══════════════════════════════════════════════

test "session: fingerprint — create and validate with matching fingerprint" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    const fp = "Mozilla/5.0|192.168.1.100";
    var token_buf: [64]u8 = undefined;
    const token_len = try store.createSession("user-fp", fp, &token_buf);
    const token = token_buf[0..token_len];

    // Matching fingerprint should succeed
    const uid = store.validateSession(token, fp);
    try testing.expect(uid != null);
    try testing.expectEqualStrings("user-fp", uid.?);
}

test "session: fingerprint — reject mismatched fingerprint" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    const fp_create = "Mozilla/5.0|192.168.1.100";
    const fp_wrong = "curl/7.0|10.0.0.1";
    var token_buf: [64]u8 = undefined;
    const token_len = try store.createSession("user-fp2", fp_create, &token_buf);
    const token = token_buf[0..token_len];

    // Wrong fingerprint should fail
    const uid = store.validateSession(token, fp_wrong);
    try testing.expect(uid == null);

    // Correct fingerprint should still work
    const uid_ok = store.validateSession(token, fp_create);
    try testing.expect(uid_ok != null);
}

test "session: fingerprint — empty fingerprint on create allows any on validate (legacy)" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Create with empty fingerprint (legacy mode)
    var token_buf: [64]u8 = undefined;
    const token_len = try store.createSession("legacy-user", "", &token_buf);
    const token = token_buf[0..token_len];

    // Any fingerprint should work for legacy sessions
    try testing.expect(store.validateSession(token, "") != null);
    try testing.expect(store.validateSession(token, "some-fingerprint") != null);
    try testing.expect(store.validateSession(token, "different-fp") != null);
}

test "session: fingerprint — inject with fingerprint then validate" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    const fp = "test-agent|127.0.0.1";
    try store.injectSession("inject-fp-token", "user-injfp", fp);

    // Matching fingerprint
    const uid = store.validateSession("inject-fp-token", fp);
    try testing.expect(uid != null);
    try testing.expectEqualStrings("user-injfp", uid.?);

    // Mismatched fingerprint
    try testing.expect(store.validateSession("inject-fp-token", "wrong-fp") == null);
}

test "session: fingerprint — inject with empty fingerprint allows any (legacy)" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    try store.injectSession("inject-legacy", "legacy-inj", "");

    // Legacy inject: any fingerprint passes
    try testing.expect(store.validateSession("inject-legacy", "") != null);
    try testing.expect(store.validateSession("inject-legacy", "any-fp") != null);
}

// ══════════════════════════════════════════════
//  Phase 2: Per-user session cap tests
// ══════════════════════════════════════════════

test "session: per-user cap — evicts one when at limit" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Create exactly MAX_SESSIONS_PER_USER sessions
    var tokens: [session_mod.MAX_SESSIONS_PER_USER + 1][64]u8 = undefined;
    var lengths: [session_mod.MAX_SESSIONS_PER_USER + 1]usize = undefined;

    for (0..session_mod.MAX_SESSIONS_PER_USER) |i| {
        lengths[i] = try store.createSession("cap-user", "", &tokens[i]);
    }

    // All should be valid — exactly at cap
    try testing.expectEqual(@as(usize, session_mod.MAX_SESSIONS_PER_USER), store.countUserSessions("cap-user"));

    // Create one more — should evict one to make room
    lengths[session_mod.MAX_SESSIONS_PER_USER] = try store.createSession("cap-user", "", &tokens[session_mod.MAX_SESSIONS_PER_USER]);

    // Still at cap (one was evicted)
    try testing.expectEqual(@as(usize, session_mod.MAX_SESSIONS_PER_USER), store.countUserSessions("cap-user"));

    // The newest should definitely be valid
    const newest_idx = session_mod.MAX_SESSIONS_PER_USER;
    try testing.expect(store.validateSession(tokens[newest_idx][0..lengths[newest_idx]], "") != null);

    // Exactly one of the original tokens should have been evicted
    var evicted_count: usize = 0;
    for (0..session_mod.MAX_SESSIONS_PER_USER) |i| {
        if (store.validateSession(tokens[i][0..lengths[i]], "") == null) {
            evicted_count += 1;
        }
    }
    try testing.expectEqual(@as(usize, 1), evicted_count);
}

test "session: per-user cap — different users are independent" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    // Fill user-A to cap
    for (0..session_mod.MAX_SESSIONS_PER_USER) |_| {
        var t: [64]u8 = undefined;
        _ = try store.createSession("user-A", "", &t);
    }

    // user-B should still be able to create sessions independently
    var t_b: [64]u8 = undefined;
    const len_b = try store.createSession("user-B", "", &t_b);

    try testing.expectEqual(@as(usize, session_mod.MAX_SESSIONS_PER_USER), store.countUserSessions("user-A"));
    try testing.expectEqual(@as(usize, 1), store.countUserSessions("user-B"));
    try testing.expect(store.validateSession(t_b[0..len_b], "") != null);
}

test "session: countUserSessions — zero for unknown user" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    try testing.expectEqual(@as(usize, 0), store.countUserSessions("nobody"));
}

test "session: countUserSessions — tracks correctly" {
    var store = session_mod.SessionStore.init(testing.allocator);
    defer store.deinit();

    try testing.expectEqual(@as(usize, 0), store.countUserSessions("user-count"));

    var t1: [64]u8 = undefined;
    _ = try store.createSession("user-count", "", &t1);
    try testing.expectEqual(@as(usize, 1), store.countUserSessions("user-count"));

    var t2: [64]u8 = undefined;
    _ = try store.createSession("user-count", "", &t2);
    try testing.expectEqual(@as(usize, 2), store.countUserSessions("user-count"));
}
