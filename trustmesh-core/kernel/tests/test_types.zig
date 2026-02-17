const std = @import("std");
const podos = @import("podos");
const types = podos.types;

test "visibility overrides" {
    try std.testing.expect(types.Visibility.private.overrides(.internal));
    try std.testing.expect(types.Visibility.private.overrides(.open));
    try std.testing.expect(types.Visibility.internal.overrides(.open));
    try std.testing.expect(!types.Visibility.open.overrides(.internal));
    try std.testing.expect(!types.Visibility.open.overrides(.private));
    try std.testing.expect(!types.Visibility.internal.overrides(.private));
    try std.testing.expect(!types.Visibility.private.overrides(.private)); // same level
}

test "valid state transitions" {
    // Forward path: dormant -> pending -> activating -> active -> deactivating -> completed
    try std.testing.expect(types.validTransition(.dormant, .pending));
    try std.testing.expect(types.validTransition(.pending, .activating));
    try std.testing.expect(types.validTransition(.activating, .active));
    try std.testing.expect(types.validTransition(.active, .deactivating));
    try std.testing.expect(types.validTransition(.deactivating, .completed));
    try std.testing.expect(types.validTransition(.completed, .archived));
    try std.testing.expect(types.validTransition(.archived, .deleted));

    // Retry path
    try std.testing.expect(types.validTransition(.failed, .pending));

    // Fail from any live state
    try std.testing.expect(types.validTransition(.pending, .failed));
    try std.testing.expect(types.validTransition(.activating, .failed));
    try std.testing.expect(types.validTransition(.active, .failed));
    try std.testing.expect(types.validTransition(.deactivating, .failed));
}

test "invalid state transitions" {
    // Can't skip states
    try std.testing.expect(!types.validTransition(.dormant, .active));
    try std.testing.expect(!types.validTransition(.dormant, .completed));
    try std.testing.expect(!types.validTransition(.pending, .active));

    // Terminal state has no outgoing edges
    try std.testing.expect(!types.validTransition(.deleted, .dormant));
    try std.testing.expect(!types.validTransition(.deleted, .pending));
    try std.testing.expect(!types.validTransition(.deleted, .deleted));

    // Can't go backwards
    try std.testing.expect(!types.validTransition(.active, .pending));
    try std.testing.expect(!types.validTransition(.completed, .active));
}

test "zero id detection" {
    try std.testing.expect(types.is_zero_id(types.ZERO_ID));
    var id: types.EntryId = .{0} ** 16;
    id[0] = 1;
    try std.testing.expect(!types.is_zero_id(id));
}

test "ids equal" {
    const a: types.EntryId = .{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
    const b: types.EntryId = .{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
    const c: types.EntryId = .{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 99 };
    try std.testing.expect(types.ids_equal(a, b));
    try std.testing.expect(!types.ids_equal(a, c));
}

test "isTerminal and isLive" {
    try std.testing.expect(types.isTerminal(.deleted));
    try std.testing.expect(!types.isTerminal(.active));
    try std.testing.expect(!types.isTerminal(.dormant));

    try std.testing.expect(types.isLive(.active));
    try std.testing.expect(types.isLive(.activating));
    try std.testing.expect(types.isLive(.pending));
    try std.testing.expect(!types.isLive(.dormant));
    try std.testing.expect(!types.isLive(.completed));
}
