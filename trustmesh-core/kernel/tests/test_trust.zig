// test_trust.zig — Tests for trust resolution via SQLite queries.

const std = @import("std");
const testing = std.testing;
const podos = @import("podos");
const db_mod = podos.db;
const trust_mod = podos.trust;

/// Create an in-memory DB with the schema needed for trust queries.
fn setupTestDb() !db_mod.Database {
    var database = try db_mod.Database.open(":memory:");

    // Create minimal schema matching trustmesh models
    try database.exec(
        "CREATE TABLE users (" ++
            "id TEXT PRIMARY KEY, " ++
            "is_remote INTEGER DEFAULT 0, " ++
            "remote_pod_url TEXT" ++
            ")",
    );
    try database.exec(
        "CREATE TABLE connections (" ++
            "id TEXT PRIMARY KEY, " ++
            "from_user_id TEXT, " ++
            "to_user_id TEXT, " ++
            "status TEXT" ++
            ")",
    );
    try database.exec(
        "CREATE TABLE networks (" ++
            "id TEXT PRIMARY KEY, " ++
            "expires_at TEXT" ++
            ")",
    );
    try database.exec(
        "CREATE TABLE network_memberships (" ++
            "id TEXT PRIMARY KEY, " ++
            "network_id TEXT, " ++
            "user_id TEXT" ++
            ")",
    );
    try database.exec(
        "CREATE TABLE peer_pods (" ++
            "id TEXT PRIMARY KEY, " ++
            "url TEXT, " ++
            "status TEXT, " ++
            "last_seen_at TEXT" ++
            ")",
    );

    return database;
}

test "trust: same user → private" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('user-1')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "user-1", 6, "user-1", 6, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"private\"") != null);
}

test "trust: shared network → network" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    try database.exec("INSERT INTO networks (id) VALUES ('net-1')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-1', 'alice')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-1', 'bob')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"network\"") != null);
    try testing.expect(std.mem.indexOf(u8, result, "net-1") != null);
}

test "trust: connection only → connected" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    try database.exec("INSERT INTO connections (id, from_user_id, to_user_id, status) VALUES ('c1', 'alice', 'bob', 'accepted')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"connected\"") != null);
}

test "trust: no relationship → public" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('charlie')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "charlie", 7, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}

test "trust: expired network not counted" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    // Expired network
    try database.exec("INSERT INTO networks (id, expires_at) VALUES ('net-exp', '2020-01-01 00:00:00')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-exp', 'alice')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-exp', 'bob')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    // Should be public since network is expired
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}

test "trust: ghost stale → downgrade to public" {
    var database = try setupTestDb();
    defer database.close();

    // Ghost user with unreachable pod
    try database.exec("INSERT INTO users (id, is_remote, remote_pod_url) VALUES ('ghost-1', 1, 'http://dead-pod.local')");
    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO networks (id) VALUES ('net-1')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-1', 'ghost-1')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-1', 'alice')");
    // No peer_pods entry → stale

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "ghost-1", 7, "alice", 5, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}

test "trust: bidirectional connection" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    try database.exec("INSERT INTO connections (id, from_user_id, to_user_id, status) VALUES ('c1', 'bob', 'alice', 'accepted')");

    // Query from alice→bob should find the bob→alice connection
    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"connected\"") != null);
}

test "trust: multiple shared networks" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    try database.exec("INSERT INTO networks (id) VALUES ('net-a')");
    try database.exec("INSERT INTO networks (id) VALUES ('net-b')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-a', 'alice')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-a', 'bob')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m3', 'net-b', 'alice')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m4', 'net-b', 'bob')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"network\"") != null);
    try testing.expect(std.mem.indexOf(u8, result, "net-a") != null);
    try testing.expect(std.mem.indexOf(u8, result, "net-b") != null);
}

test "trust: pending connection not counted" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    // Connection exists but status is "pending", not "accepted"
    try database.exec("INSERT INTO connections (id, from_user_id, to_user_id, status) VALUES ('c1', 'alice', 'bob', 'pending')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}

test "trust: network takes priority over connection" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    // Both connected AND in the same network
    try database.exec("INSERT INTO connections (id, from_user_id, to_user_id, status) VALUES ('c1', 'alice', 'bob', 'accepted')");
    try database.exec("INSERT INTO networks (id) VALUES ('net-1')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-1', 'alice')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-1', 'bob')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    // Network should take priority (higher trust)
    try testing.expect(std.mem.indexOf(u8, result, "\"network\"") != null);
}

test "trust: ghost with active peer is not stale" {
    var database = try setupTestDb();
    defer database.close();

    // Ghost user with an active, recently-seen peer
    try database.exec("INSERT INTO users (id, is_remote, remote_pod_url) VALUES ('ghost-ok', 1, 'http://live-pod.local')");
    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO peer_pods (id, url, status, last_seen_at) VALUES ('p1', 'http://live-pod.local', 'active', datetime('now'))");
    try database.exec("INSERT INTO networks (id) VALUES ('net-1')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-1', 'ghost-ok')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-1', 'alice')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "ghost-ok", 8, "alice", 5, &buf, 512);
    const result = buf[0..len];
    // Should be network (not downgraded to public)
    try testing.expect(std.mem.indexOf(u8, result, "\"network\"") != null);
}

test "trust: ghost with inactive peer is stale" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id, is_remote, remote_pod_url) VALUES ('ghost-bad', 1, 'http://down-pod.local')");
    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    // Peer exists but status is "inactive"
    try database.exec("INSERT INTO peer_pods (id, url, status, last_seen_at) VALUES ('p1', 'http://down-pod.local', 'inactive', datetime('now'))");
    try database.exec("INSERT INTO networks (id) VALUES ('net-1')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-1', 'ghost-bad')");
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m2', 'net-1', 'alice')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "ghost-bad", 9, "alice", 5, &buf, 512);
    const result = buf[0..len];
    // Should be downgraded to public
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}

test "trust: only one user in network → no shared" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    try database.exec("INSERT INTO networks (id) VALUES ('net-solo')");
    // Only alice is in the network, bob is not
    try database.exec("INSERT INTO network_memberships (id, network_id, user_id) VALUES ('m1', 'net-solo', 'alice')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}

test "trust: rejected connection not counted" {
    var database = try setupTestDb();
    defer database.close();

    try database.exec("INSERT INTO users (id) VALUES ('alice')");
    try database.exec("INSERT INTO users (id) VALUES ('bob')");
    try database.exec("INSERT INTO connections (id, from_user_id, to_user_id, status) VALUES ('c1', 'alice', 'bob', 'rejected')");

    var buf: [512]u8 = undefined;
    const len = try trust_mod.resolveTrustLevel(&database, "alice", 5, "bob", 3, &buf, 512);
    const result = buf[0..len];
    try testing.expect(std.mem.indexOf(u8, result, "\"public\"") != null);
}
