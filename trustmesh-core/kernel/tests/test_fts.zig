// test_fts.zig — Tests for SQLite FTS5 full-text search.

const std = @import("std");
const testing = std.testing;
const podos = @import("podos");
const db_mod = podos.db;
const fts_mod = podos.fts;

fn openTestDb() !db_mod.Database {
    // Use in-memory DB for tests (no file cleanup needed)
    return db_mod.Database.open(":memory:");
}

test "db: open and close in-memory database" {
    var database = try openTestDb();
    defer database.close();
    // If we got here, open succeeded
    try database.exec("SELECT 1");
}

test "fts: init creates virtual table" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    // Verify table exists by querying it
    var stmt = try database.prepare("SELECT count(*) FROM capsule_fts");
    defer stmt.finalize();
    const has_row = try stmt.step();
    try testing.expect(has_row);
    const count = stmt.getInt(0);
    try testing.expectEqual(@as(c_int, 0), count);
}

test "fts: init is idempotent" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);
    try fts_mod.initFtsTable(&database); // should not fail
}

test "fts: upsert and search basic" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    // Upsert a capsule about heart medication
    try fts_mod.upsertCapsule(
        &database,
        "cap-001",
        7,
        "Heart Medication",
        16,
        "Take lisinopril 10mg daily for blood pressure management",
        55,
        "health",
        6,
    );

    // Upsert a capsule about guitar
    try fts_mod.upsertCapsule(
        &database,
        "cap-002",
        7,
        "Guitar Practice",
        15,
        "Practice Stairway to Heaven intro every evening",
        47,
        "hobby",
        5,
    );

    // Search for "medication" with both IDs accessible
    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-001\",\"cap-002\"]";
    const written = try fts_mod.searchCapsules(
        &database,
        "medication",
        10,
        ids_json,
        ids_json.len,
        5,
        &out_buf,
        4096,
    );

    const result = out_buf[0..written];
    // Should find cap-001 (medication match)
    try testing.expect(std.mem.indexOf(u8, result, "cap-001") != null);
    // Should NOT find cap-002 (no medication in guitar content)
    try testing.expect(std.mem.indexOf(u8, result, "cap-002") == null);
}

test "fts: BM25 ranking order" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    // Cap with "heart" in title AND content (should rank higher)
    try fts_mod.upsertCapsule(
        &database,
        "cap-a",
        5,
        "Heart Health",
        12,
        "Heart rate monitoring shows normal heart rhythm",
        47,
        "health",
        6,
    );

    // Cap with "heart" only in content (should rank lower)
    try fts_mod.upsertCapsule(
        &database,
        "cap-b",
        5,
        "Daily Vitals",
        12,
        "Blood pressure and heart rate checked this morning",
        50,
        "health",
        6,
    );

    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-a\",\"cap-b\"]";
    const written = try fts_mod.searchCapsules(
        &database,
        "heart",
        5,
        ids_json,
        ids_json.len,
        5,
        &out_buf,
        4096,
    );

    const result = out_buf[0..written];
    // Both should appear
    try testing.expect(std.mem.indexOf(u8, result, "cap-a") != null);
    try testing.expect(std.mem.indexOf(u8, result, "cap-b") != null);
    // cap-a should come first (better BM25 score — "heart" in title AND content)
    const pos_a = std.mem.indexOf(u8, result, "cap-a").?;
    const pos_b = std.mem.indexOf(u8, result, "cap-b").?;
    try testing.expect(pos_a < pos_b);
}

test "fts: accessible_ids filtering" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    try fts_mod.upsertCapsule(&database, "cap-1", 5, "Secret Medical", 14, "Private health data about surgery", 33, "health", 6);
    try fts_mod.upsertCapsule(&database, "cap-2", 5, "Public Health", 13, "General health tips for everyone", 32, "health", 6);

    // Only cap-2 is accessible
    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-2\"]";
    const written = try fts_mod.searchCapsules(
        &database,
        "health",
        6,
        ids_json,
        ids_json.len,
        5,
        &out_buf,
        4096,
    );

    const result = out_buf[0..written];
    try testing.expect(std.mem.indexOf(u8, result, "cap-2") != null);
    try testing.expect(std.mem.indexOf(u8, result, "cap-1") == null); // filtered out
}

test "fts: delete removes from index" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    try fts_mod.upsertCapsule(&database, "cap-x", 5, "Test", 4, "Findable content here", 21, "general", 7);

    // Verify it's findable
    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-x\"]";
    var written = try fts_mod.searchCapsules(&database, "findable", 8, ids_json, ids_json.len, 5, &out_buf, 4096);
    try testing.expect(std.mem.indexOf(u8, out_buf[0..written], "cap-x") != null);

    // Delete it
    try fts_mod.deleteCapsule(&database, "cap-x", 5);

    // Verify it's gone
    written = try fts_mod.searchCapsules(&database, "findable", 8, ids_json, ids_json.len, 5, &out_buf, 4096);
    try testing.expect(std.mem.indexOf(u8, out_buf[0..written], "cap-x") == null);
}

test "fts: upsert overwrites existing" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    try fts_mod.upsertCapsule(&database, "cap-u", 5, "V1", 2, "Old content about cats", 22, "general", 7);
    try fts_mod.upsertCapsule(&database, "cap-u", 5, "V2", 2, "New content about dogs", 22, "general", 7);

    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-u\"]";

    // Should NOT find old content
    var written = try fts_mod.searchCapsules(&database, "cats", 4, ids_json, ids_json.len, 5, &out_buf, 4096);
    try testing.expect(std.mem.indexOf(u8, out_buf[0..written], "cap-u") == null);

    // Should find new content
    written = try fts_mod.searchCapsules(&database, "dogs", 4, ids_json, ids_json.len, 5, &out_buf, 4096);
    try testing.expect(std.mem.indexOf(u8, out_buf[0..written], "cap-u") != null);
}

test "fts: reset clears all data" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    try fts_mod.upsertCapsule(&database, "cap-r", 5, "Title", 5, "Some content", 12, "general", 7);

    // Reset
    try fts_mod.resetFts(&database);

    // Table should be empty but exist
    var stmt = try database.prepare("SELECT count(*) FROM capsule_fts");
    defer stmt.finalize();
    _ = try stmt.step();
    try testing.expectEqual(@as(c_int, 0), stmt.getInt(0));
}

test "fts: UTF-8 content" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    const title = "Caf\xc3\xa9 Visit"; // "Café Visit"
    const content = "Had a wonderful caf\xc3\xa9 au lait at the corner bistro";
    try fts_mod.upsertCapsule(
        &database,
        "cap-utf",
        7,
        title,
        title.len,
        content,
        content.len,
        "diary",
        5,
    );

    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-utf\"]";
    const written = try fts_mod.searchCapsules(&database, "bistro", 6, ids_json, ids_json.len, 5, &out_buf, 4096);
    try testing.expect(std.mem.indexOf(u8, out_buf[0..written], "cap-utf") != null);
}

test "fts: empty accessible_ids returns empty" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    try fts_mod.upsertCapsule(&database, "cap-e", 5, "Title", 5, "Content", 7, "general", 7);

    var out_buf: [4096]u8 = undefined;
    const empty_ids = "[]";
    const written = try fts_mod.searchCapsules(&database, "content", 7, empty_ids, empty_ids.len, 5, &out_buf, 4096);
    // Should return "[]" (empty array)
    try testing.expectEqualStrings("[]", out_buf[0..written]);
}

test "fts: porter stemming matches word forms" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    try fts_mod.upsertCapsule(&database, "cap-s", 5, "Running", 7, "She runs every morning for exercise", 35, "fitness", 7);

    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-s\"]";
    // "running" should match "runs" via porter stemmer
    const written = try fts_mod.searchCapsules(&database, "running", 7, ids_json, ids_json.len, 5, &out_buf, 4096);
    try testing.expect(std.mem.indexOf(u8, out_buf[0..written], "cap-s") != null);
}

test "fts: top_k limits results" {
    var database = try openTestDb();
    defer database.close();
    try fts_mod.initFtsTable(&database);

    // Insert 5 capsules all matching "test"
    const ids = [_][]const u8{ "cap-t0", "cap-t1", "cap-t2", "cap-t3", "cap-t4" };
    for (ids) |id| {
        try fts_mod.upsertCapsule(&database, id.ptr, id.len, "Test Item", 9, "This is test content for searching", 34, "general", 7);
    }

    var out_buf: [4096]u8 = undefined;
    const ids_json = "[\"cap-t0\",\"cap-t1\",\"cap-t2\",\"cap-t3\",\"cap-t4\"]";
    const written = try fts_mod.searchCapsules(&database, "test", 4, ids_json, ids_json.len, 2, &out_buf, 4096);
    const result = out_buf[0..written];

    // Count occurrences of "cap-t" — should be exactly 2 (top_k=2)
    var count: usize = 0;
    var pos: usize = 0;
    while (std.mem.indexOfPos(u8, result, pos, "cap-t")) |found| {
        count += 1;
        pos = found + 1;
    }
    try testing.expectEqual(@as(usize, 2), count);
}
