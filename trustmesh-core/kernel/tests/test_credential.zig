// test_credential.zig — Unit tests for credential.zig and db.initCredentialTables()

const std = @import("std");
const podos = @import("podos");
const db_mod = podos.db;
const cred = podos.credential;

// ── Helpers ──────────────────────────────────────────────────────────────────

fn openTestDb() !db_mod.Database {
    var database = try db_mod.Database.open(":memory:");
    try database.initCredentialTables();
    return database;
}

const OWNER = "user_owner_01";
const OTHER = "user_other_02";
const CRED_ID = "cred_test_0001";
const ENC_SECRET = "encryptedblob12345";
const TOOLS_JSON = "[\"stripe_checkout\",\"billing_lookup\"]";

// ── Tests ─────────────────────────────────────────────────────────────────────

test "initCredentialTables creates tables" {
    var database = try openTestDb();
    defer database.close();

    // Check vault_secrets exists
    var stmt = try database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='vault_secrets'");
    defer stmt.finalize();
    const found = try stmt.step();
    try std.testing.expect(found);
}

test "credential_fts virtual table exists" {
    var database = try openTestDb();
    defer database.close();

    var stmt = try database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='credential_fts'");
    defer stmt.finalize();
    const found = try stmt.step();
    try std.testing.expect(found);
}

test "create and list credential" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database,
        CRED_ID, OWNER,
        "Stripe Production Key", "stripe.com", "payments",
        ENC_SECRET, TOOLS_JSON, null,
    );

    var buf: [4096]u8 = undefined;
    const n = try cred.list(&database, OWNER, &buf);
    try std.testing.expect(n > 0);
    const json_str = buf[0..n];
    try std.testing.expect(std.mem.indexOf(u8, json_str, "Stripe Production Key") != null);
    try std.testing.expect(std.mem.indexOf(u8, json_str, "stripe.com") != null);
    // Secret must NOT appear
    try std.testing.expect(std.mem.indexOf(u8, json_str, "encryptedblob") == null);
}

test "list returns empty for other owner" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Stripe Key", "stripe.com", "payments",
        ENC_SECRET, TOOLS_JSON, null,
    );

    var buf: [4096]u8 = undefined;
    const n = try cred.list(&database, OTHER, &buf);
    const json_str = buf[0..n];
    try std.testing.expectEqualStrings("[]", json_str);
}

test "forTool returns matching credential with encrypted blob" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Stripe Key", "stripe.com", "payments",
        ENC_SECRET, TOOLS_JSON, null,
    );

    var buf: [8192]u8 = undefined;
    const n = try cred.forTool(&database, OWNER, "stripe_checkout", &buf);
    const json_str = buf[0..n];
    try std.testing.expect(n > 2); // more than just []
    try std.testing.expect(std.mem.indexOf(u8, json_str, "secret_encrypted_b64") != null);
}

test "forTool returns empty for wrong tool" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Stripe Key", "stripe.com", "payments",
        ENC_SECRET, TOOLS_JSON, null,
    );

    var buf: [4096]u8 = undefined;
    const n = try cred.forTool(&database, OWNER, "unrelated_tool", &buf);
    try std.testing.expectEqualStrings("[]", buf[0..n]);
}

test "deactivate removes from list" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Old Key", "service.io", "api",
        ENC_SECRET, "[]", null,
    );

    try cred.deactivate(&database, CRED_ID, OWNER);

    var buf: [4096]u8 = undefined;
    const n = try cred.list(&database, OWNER, &buf);
    try std.testing.expectEqualStrings("[]", buf[0..n]);
}

test "deactivate denied for wrong owner" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Key", "svc.io", "api",
        ENC_SECRET, "[]", null,
    );

    const err = cred.deactivate(&database, CRED_ID, OTHER);
    try std.testing.expectError(cred.CredentialError.PermissionDenied, err);
}

test "updateUse increments use_count" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Key", "svc.io", "api",
        ENC_SECRET, "[]", null,
    );

    try cred.updateUse(&database, CRED_ID, OWNER);
    try cred.updateUse(&database, CRED_ID, OWNER);

    var stmt = try database.prepare("SELECT use_count FROM vault_secrets WHERE id = ?");
    defer stmt.finalize();
    try stmt.bindText(1, CRED_ID.ptr, CRED_ID.len);
    _ = try stmt.step();
    try std.testing.expectEqual(@as(c_int, 2), stmt.getInt(0));
}

test "share create and check" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Shared Key", "svc.io", "api",
        ENC_SECRET, "[]", null,
    );

    try cred.shareCreate(
        &database,
        "share_001", CRED_ID, OWNER, OTHER, "user",
        "2099-12-31T00:00:00Z", 10, null,
    );

    var buf: [2048]u8 = undefined;
    const n = try cred.shareCheck(&database, CRED_ID, OTHER, &buf);
    try std.testing.expect(n > 0);
    try std.testing.expect(std.mem.indexOf(u8, buf[0..n], "share_001") != null);
}

test "share check returns 0 for expired share" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Shared Key", "svc.io", "api",
        ENC_SECRET, "[]", null,
    );

    // Expires in the past
    try cred.shareCreate(
        &database,
        "share_expired", CRED_ID, OWNER, OTHER, "user",
        "2000-01-01T00:00:00Z", null, null,
    );

    var buf: [2048]u8 = undefined;
    const n = try cred.shareCheck(&database, CRED_ID, OTHER, &buf);
    try std.testing.expectEqual(@as(usize, 0), n);
}

test "share revoke" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Key", "svc.io", "api",
        ENC_SECRET, "[]", null,
    );

    try cred.shareCreate(
        &database,
        "share_rev", CRED_ID, OWNER, OTHER, "user",
        "2099-12-31T00:00:00Z", null, null,
    );

    try cred.shareRevoke(&database, "share_rev", OWNER);

    var buf: [2048]u8 = undefined;
    const n = try cred.shareCheck(&database, CRED_ID, OTHER, &buf);
    try std.testing.expectEqual(@as(usize, 0), n);
}

test "share create denied for non-owner" {
    var database = try openTestDb();
    defer database.close();

    try cred.create(
        &database, CRED_ID, OWNER,
        "Key", "svc.io", "api",
        ENC_SECRET, "[]", null,
    );

    const err = cred.shareCreate(
        &database,
        "share_bad", CRED_ID,
        OTHER, // NOT the owner
        "third_user", "user",
        "2099-12-31T00:00:00Z", null, null,
    );
    try std.testing.expectError(cred.CredentialError.PermissionDenied, err);
}

test "FTS does not contain secret value" {
    var database = try openTestDb();
    defer database.close();

    const secret_plaintext = "sk_test_VERY_SECRET_KEY_12345";

    try cred.create(
        &database, CRED_ID, OWNER,
        "API Key", "stripe.com", "payments",
        secret_plaintext, // not actually encrypted here — verifying FTS isolation
        "[]", null,
    );

    var stmt = try database.prepare("SELECT * FROM credential_fts WHERE credential_fts MATCH 'VERY_SECRET'");
    defer stmt.finalize();
    const found = try stmt.step();
    try std.testing.expect(!found); // FTS should NOT index secret content
}
