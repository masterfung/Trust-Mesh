// test_timeline_persist.zig — Tests for timeline entry persistence + sync inbox/outbox.

const std = @import("std");
const testing = std.testing;
const podos = @import("podos");
const db_mod = podos.db;
const tp = podos.timeline_persist;

fn openTestDb() !db_mod.Database {
    var database = try db_mod.Database.open(":memory:");
    try tp.initTables(&database);
    return database;
}

test "persist: initTables creates tables" {
    var database = try db_mod.Database.open(":memory:");
    defer database.close();
    try tp.initTables(&database);

    // Verify tables exist by querying them
    var s1 = try database.prepare("SELECT count(*) FROM timeline_entries");
    defer s1.finalize();
    _ = try s1.step();
    try testing.expectEqual(@as(c_int, 0), s1.getInt(0));

    var s2 = try database.prepare("SELECT count(*) FROM timeline_outbox");
    defer s2.finalize();
    _ = try s2.step();
    try testing.expectEqual(@as(c_int, 0), s2.getInt(0));

    var s3 = try database.prepare("SELECT count(*) FROM timeline_inbox");
    defer s3.finalize();
    _ = try s3.step();
    try testing.expectEqual(@as(c_int, 0), s3.getInt(0));
}

test "persist: initTables is idempotent" {
    var database = try db_mod.Database.open(":memory:");
    defer database.close();
    try tp.initTables(&database);
    try tp.initTables(&database); // second call should not fail
}

test "persist: upsert and load entry" {
    var database = try openTestDb();
    defer database.close();

    const spec = "{\"label\":\"Morning check\",\"category\":\"health\"}";
    try tp.upsertEntry(
        &database,
        "entry-001",
        9,
        "user-abc",
        8,
        1, // pending state
        spec,
        spec.len,
    );

    // Load all entries
    var out_buf: [4096]u8 = undefined;
    const written = try tp.loadEntrySpecsJson(&database, null, 0, &out_buf, 4096);
    const result = out_buf[0..written];

    // Should be a JSON array containing the spec
    try testing.expect(result[0] == '[');
    try testing.expect(result[result.len - 1] == ']');
    try testing.expect(std.mem.indexOf(u8, result, "Morning check") != null);
}

test "persist: upsert overwrites on conflict" {
    var database = try openTestDb();
    defer database.close();

    const spec_v1 = "{\"label\":\"V1\"}";
    try tp.upsertEntry(&database, "entry-ow", 8, "user-1", 6, 1, spec_v1, spec_v1.len);

    const spec_v2 = "{\"label\":\"V2\"}";
    try tp.upsertEntry(&database, "entry-ow", 8, "user-1", 6, 2, spec_v2, spec_v2.len);

    var out_buf: [4096]u8 = undefined;
    const written = try tp.loadEntrySpecsJson(&database, null, 0, &out_buf, 4096);
    const result = out_buf[0..written];

    // Should contain V2, not V1
    try testing.expect(std.mem.indexOf(u8, result, "\"V2\"") != null);
    try testing.expect(std.mem.indexOf(u8, result, "\"V1\"") == null);
}

test "persist: load filtered by owner_id" {
    var database = try openTestDb();
    defer database.close();

    try tp.upsertEntry(&database, "e-a", 3, "alice", 5, 1, "{\"owner\":\"alice\"}", 17);
    try tp.upsertEntry(&database, "e-b", 3, "bob", 3, 1, "{\"owner\":\"bob\"}", 15);

    // Load only alice's entries
    var out_buf: [4096]u8 = undefined;
    const written = try tp.loadEntrySpecsJson(&database, "alice", 5, &out_buf, 4096);
    const result = out_buf[0..written];

    try testing.expect(std.mem.indexOf(u8, result, "alice") != null);
    try testing.expect(std.mem.indexOf(u8, result, "bob") == null);
}

test "persist: load all when no owner filter" {
    var database = try openTestDb();
    defer database.close();

    try tp.upsertEntry(&database, "e-1", 3, "u1", 2, 1, "{\"n\":1}", 7);
    try tp.upsertEntry(&database, "e-2", 3, "u2", 2, 1, "{\"n\":2}", 7);

    var out_buf: [4096]u8 = undefined;
    const written = try tp.loadEntrySpecsJson(&database, null, 0, &out_buf, 4096);
    const result = out_buf[0..written];

    // Both entries should be present
    try testing.expect(std.mem.indexOf(u8, result, "\"n\":1") != null);
    try testing.expect(std.mem.indexOf(u8, result, "\"n\":2") != null);
}

test "persist: updateEntryState changes state" {
    var database = try openTestDb();
    defer database.close();

    try tp.upsertEntry(&database, "e-st", 4, "owner", 5, 1, "{}", 2);
    try tp.updateEntryState(&database, "e-st", 4, 5); // change to state 5

    // Verify by querying raw
    var stmt = try database.prepare("SELECT state FROM timeline_entries WHERE entry_id = ?");
    defer stmt.finalize();
    stmt.bindText(1, "e-st", 4) catch unreachable;
    const has_row = try stmt.step();
    try testing.expect(has_row);
    try testing.expectEqual(@as(c_int, 5), stmt.getInt(0));
}

test "persist: deleteEntry removes row" {
    var database = try openTestDb();
    defer database.close();

    try tp.upsertEntry(&database, "e-del", 5, "own", 3, 1, "{}", 2);
    try tp.deleteEntry(&database, "e-del", 5);

    var stmt = try database.prepare("SELECT count(*) FROM timeline_entries WHERE entry_id = ?");
    defer stmt.finalize();
    stmt.bindText(1, "e-del", 5) catch unreachable;
    _ = try stmt.step();
    try testing.expectEqual(@as(c_int, 0), stmt.getInt(0));
}

test "persist: getEntryOwner returns owner_id" {
    var database = try openTestDb();
    defer database.close();

    try tp.upsertEntry(&database, "e-own", 5, "peter-johnson", 13, 1, "{}", 2);

    var out_buf: [256]u8 = undefined;
    const len = try tp.getEntryOwner(&database, "e-own", 5, &out_buf, 256);
    try testing.expectEqualStrings("peter-johnson", out_buf[0..len]);
}

test "persist: getEntryOwner returns 0 for missing entry" {
    var database = try openTestDb();
    defer database.close();

    var out_buf: [256]u8 = undefined;
    const len = try tp.getEntryOwner(&database, "nonexistent", 11, &out_buf, 256);
    try testing.expectEqual(@as(usize, 0), len);
}

test "persist: outbox append and pull" {
    var database = try openTestDb();
    defer database.close();

    const ev1 = "{\"type\":\"entry_created\",\"entry_id\":\"e1\"}";
    const ev2 = "{\"type\":\"state_changed\",\"entry_id\":\"e2\"}";
    try tp.appendOutboxEvent(&database, 10, ev1, ev1.len);
    try tp.appendOutboxEvent(&database, 11, ev2, ev2.len);

    // Pull all events since tick 0
    var out_buf: [4096]u8 = undefined;
    const written = try tp.pullOutboxEventsJson(&database, 0, &out_buf, 4096);
    const result = out_buf[0..written];

    try testing.expect(result[0] == '[');
    try testing.expect(std.mem.indexOf(u8, result, "entry_created") != null);
    try testing.expect(std.mem.indexOf(u8, result, "state_changed") != null);
}

test "persist: outbox pull filters by since_tick" {
    var database = try openTestDb();
    defer database.close();

    try tp.appendOutboxEvent(&database, 5, "{\"tick\":5}", 10);
    try tp.appendOutboxEvent(&database, 10, "{\"tick\":10}", 11);
    try tp.appendOutboxEvent(&database, 15, "{\"tick\":15}", 11);

    // Pull events since tick 10 (should only get tick 15)
    var out_buf: [4096]u8 = undefined;
    const written = try tp.pullOutboxEventsJson(&database, 10, &out_buf, 4096);
    const result = out_buf[0..written];

    try testing.expect(std.mem.indexOf(u8, result, "\"tick\":15") != null);
    try testing.expect(std.mem.indexOf(u8, result, "\"tick\":5") == null);
    try testing.expect(std.mem.indexOf(u8, result, "\"tick\":10") == null);
}

test "persist: outbox empty returns empty array" {
    var database = try openTestDb();
    defer database.close();

    var out_buf: [4096]u8 = undefined;
    const written = try tp.pullOutboxEventsJson(&database, 0, &out_buf, 4096);
    try testing.expectEqualStrings("[]", out_buf[0..written]);
}

test "persist: inbox mark is idempotent (INSERT OR IGNORE)" {
    var database = try openTestDb();
    defer database.close();

    const ev = "{\"data\":\"hello\"}";
    try tp.markInboxEvent(&database, "evt-001", 7, ev, ev.len);
    try tp.markInboxEvent(&database, "evt-001", 7, ev, ev.len); // duplicate — should not fail

    // Should only have one row
    var stmt = try database.prepare("SELECT count(*) FROM timeline_inbox WHERE event_id = ?");
    defer stmt.finalize();
    stmt.bindText(1, "evt-001", 7) catch unreachable;
    _ = try stmt.step();
    try testing.expectEqual(@as(c_int, 1), stmt.getInt(0));
}

test "persist: inbox stores event data" {
    var database = try openTestDb();
    defer database.close();

    const ev = "{\"type\":\"sync\",\"payload\":42}";
    try tp.markInboxEvent(&database, "evt-x", 5, ev, ev.len);

    var stmt = try database.prepare("SELECT event_json FROM timeline_inbox WHERE event_id = ?");
    defer stmt.finalize();
    stmt.bindText(1, "evt-x", 5) catch unreachable;
    const has_row = try stmt.step();
    try testing.expect(has_row);

    const json_ptr = stmt.getText(0) orelse unreachable;
    var json_len: usize = 0;
    while (json_ptr[json_len] != 0) : (json_len += 1) {}
    try testing.expectEqualStrings(ev, json_ptr[0..json_len]);
}

test "persist: load empty returns empty array" {
    var database = try openTestDb();
    defer database.close();

    var out_buf: [4096]u8 = undefined;
    const written = try tp.loadEntrySpecsJson(&database, null, 0, &out_buf, 4096);
    try testing.expectEqualStrings("[]", out_buf[0..written]);
}
