// test_credential_audit.zig — Unit tests for credential_audit.zig

const std = @import("std");
const podos = @import("podos");
const db_mod = podos.db;
const cred = podos.credential;
const audit = podos.credential_audit;

fn openTestDb() !db_mod.Database {
    var database = try db_mod.Database.open(":memory:");
    try database.initCredentialTables();
    return database;
}

const CRED_ID = "cred_audit_001";
const OWNER = "actor_owner_01";

test "append and query audit entry" {
    var database = try openTestDb();
    defer database.close();

    try audit.append(
        &database,
        CRED_ID, "created", OWNER,
        null, null, null,
        "allowed", null,
    );

    var buf: [4096]u8 = undefined;
    const n = try audit.query(&database, CRED_ID, 50, &buf);
    try std.testing.expect(n > 0);
    const json_str = buf[0..n];
    try std.testing.expect(std.mem.indexOf(u8, json_str, "created") != null);
    try std.testing.expect(std.mem.indexOf(u8, json_str, OWNER) != null);
}

test "query returns empty for unknown credential" {
    var database = try openTestDb();
    defer database.close();

    var buf: [1024]u8 = undefined;
    const n = try audit.query(&database, "no_such_cred", 10, &buf);
    try std.testing.expectEqualStrings("[]", buf[0..n]);
}

test "append with tool_name and decision" {
    var database = try openTestDb();
    defer database.close();

    try audit.append(
        &database,
        CRED_ID, "used", OWNER,
        "stripe_checkout",
        null, "abc123fp",
        "allowed",
        "{\"note\":\"payment processed\"}",
    );

    var buf: [4096]u8 = undefined;
    const n = try audit.query(&database, CRED_ID, 10, &buf);
    const json_str = buf[0..n];
    try std.testing.expect(std.mem.indexOf(u8, json_str, "stripe_checkout") != null);
    try std.testing.expect(std.mem.indexOf(u8, json_str, "abc123fp") != null);
    try std.testing.expect(std.mem.indexOf(u8, json_str, "payment processed") != null);
}

test "multiple ops ordered newest-first" {
    var database = try openTestDb();
    defer database.close();

    try audit.append(&database, CRED_ID, "created", OWNER, null, null, null, "allowed", null);
    try audit.append(&database, CRED_ID, "used", OWNER, "tool_a", null, null, "allowed", null);
    try audit.append(&database, CRED_ID, "rotated", OWNER, null, null, null, "allowed", null);

    var buf: [8192]u8 = undefined;
    const n = try audit.query(&database, CRED_ID, 10, &buf);
    const json_str = buf[0..n];

    // "rotated" should appear before "created" in the JSON
    const rotated_pos = std.mem.indexOf(u8, json_str, "rotated") orelse unreachable;
    const created_pos = std.mem.indexOf(u8, json_str, "created") orelse unreachable;
    try std.testing.expect(rotated_pos < created_pos);
}

test "limit is respected" {
    var database = try openTestDb();
    defer database.close();

    // Insert 5 entries
    var i: usize = 0;
    while (i < 5) : (i += 1) {
        try audit.append(&database, CRED_ID, "used", OWNER, null, null, null, "allowed", null);
    }

    var buf: [4096]u8 = undefined;
    const n = try audit.query(&database, CRED_ID, 2, &buf);
    const json_str = buf[0..n];
    // Count commas between objects — should be 1 (for 2 objects)
    var comma_count: usize = 0;
    for (json_str) |ch| {
        if (ch == '{') comma_count += 1;
    }
    try std.testing.expectEqual(@as(usize, 2), comma_count);
}

test "sweep expired shares creates audit entries" {
    var database = try openTestDb();
    defer database.close();

    // Create a credential
    try cred.create(
        &database,
        CRED_ID, OWNER,
        "Key", "svc.io", "api", "enc_bytes", "[]", null,
    );

    // Create a share that's already expired
    try cred.shareCreate(
        &database,
        "share_expired_01",
        CRED_ID,
        OWNER,
        "grantee_user",
        "user",
        "2000-01-01T00:00:00Z", // expired
        null, null,
    );

    try audit.sweepExpiredShares(&database);

    // Verify share is revoked
    var stmt = try database.prepare("SELECT revoked_at FROM credential_shares WHERE id = ?");
    defer stmt.finalize();
    try stmt.bindText(1, "share_expired_01", 16);
    _ = try stmt.step();
    const revoked = stmt.getText(0);
    try std.testing.expect(revoked != null);

    // Verify audit entry was created
    var buf: [4096]u8 = undefined;
    const n = try audit.query(&database, CRED_ID, 10, &buf);
    const json_str = buf[0..n];
    try std.testing.expect(std.mem.indexOf(u8, json_str, "share_expired") != null);
}

test "denied decision is recorded" {
    var database = try openTestDb();
    defer database.close();

    try audit.append(
        &database,
        CRED_ID, "used", "attacker_id",
        "evil_tool", null, null,
        "denied", null,
    );

    var buf: [4096]u8 = undefined;
    const n = try audit.query(&database, CRED_ID, 10, &buf);
    try std.testing.expect(std.mem.indexOf(u8, buf[0..n], "denied") != null);
}
