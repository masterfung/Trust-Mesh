const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const entry_mod = podos.entry;
const resolution = podos.resolution;

fn makeEntry(vis: types.Visibility, category: []const u8, salience: f32, w_start: types.Timestamp, w_end: types.Timestamp) entry_mod.Entry {
    var e = entry_mod.Entry{};
    e.state = .active;
    e.visibility = vis;
    e.salience = salience;
    e.original_salience = salience;
    e.window_start = w_start;
    e.window_end = w_end;
    e.setCategory(category);
    return e;
}

test "entries conflict — same category and overlapping window" {
    var a = makeEntry(.private, "health", 0.8, 100, 200);
    var b = makeEntry(.internal, "health", 0.7, 150, 250);
    try std.testing.expect(resolution.entriesConflict(&a, &b));
}

test "entries dont conflict — different category" {
    var a = makeEntry(.private, "health", 0.8, 100, 200);
    var b = makeEntry(.internal, "finance", 0.7, 100, 200);
    try std.testing.expect(!resolution.entriesConflict(&a, &b));
}

test "entries dont conflict — non-overlapping window" {
    var a = makeEntry(.private, "health", 0.8, 100, 200);
    var b = makeEntry(.internal, "health", 0.7, 300, 400);
    try std.testing.expect(!resolution.entriesConflict(&a, &b));
}

test "resolve — private beats internal" {
    var a = makeEntry(.private, "health", 0.9, 100, 300);
    var b = makeEntry(.internal, "health", 0.7, 100, 300);
    var entries = [_]*entry_mod.Entry{ &a, &b };

    const resolved = resolution.resolveConflicts(&entries);
    try std.testing.expectEqual(@as(u32, 1), resolved);
    try std.testing.expectApproxEqAbs(@as(f32, 0.9), a.salience, 0.01); // winner unchanged
    try std.testing.expectApproxEqAbs(@as(f32, 0.21), b.salience, 0.01); // loser shadowed
}

test "resolve — internal beats open" {
    var a = makeEntry(.internal, "health", 0.7, 100, 300);
    var b = makeEntry(.open, "health", 0.5, 100, 300);
    var entries = [_]*entry_mod.Entry{ &a, &b };

    const resolved = resolution.resolveConflicts(&entries);
    try std.testing.expectEqual(@as(u32, 1), resolved);
    try std.testing.expectApproxEqAbs(@as(f32, 0.7), a.salience, 0.01);
    try std.testing.expectApproxEqAbs(@as(f32, 0.15), b.salience, 0.01);
}

test "resolve — same visibility no change" {
    var a = makeEntry(.internal, "health", 0.7, 100, 300);
    var b = makeEntry(.internal, "health", 0.5, 100, 300);
    var entries = [_]*entry_mod.Entry{ &a, &b };

    const resolved = resolution.resolveConflicts(&entries);
    try std.testing.expectEqual(@as(u32, 0), resolved); // no resolution — agent decides
    try std.testing.expectApproxEqAbs(@as(f32, 0.7), a.salience, 0.01);
    try std.testing.expectApproxEqAbs(@as(f32, 0.5), b.salience, 0.01);
}

test "resolve — salience reset each tick" {
    var a = makeEntry(.private, "health", 0.9, 100, 300);
    var b = makeEntry(.internal, "health", 0.7, 100, 300);
    b.salience = 0.21; // previously shadowed
    var entries = [_]*entry_mod.Entry{ &a, &b };

    // resolveConflicts resets salience first, then re-applies
    _ = resolution.resolveConflicts(&entries);
    try std.testing.expectApproxEqAbs(@as(f32, 0.21), b.salience, 0.01);
}

test "shares tag" {
    var a = entry_mod.Entry{};
    try a.setTag("health");
    try a.setTag("vaccination");

    var b = entry_mod.Entry{};
    try b.setTag("finance");
    try b.setTag("vaccination");

    try std.testing.expect(resolution.sharesTag(&a, &b)); // "vaccination" shared

    var c = entry_mod.Entry{};
    try c.setTag("legal");
    try std.testing.expect(!resolution.sharesTag(&a, &c)); // no overlap
}
