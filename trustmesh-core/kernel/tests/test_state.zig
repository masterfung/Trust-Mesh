const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const entry_mod = podos.entry;
const state_mod = podos.state;

test "central state — empty entries" {
    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();

    var cs = state_mod.CentralState{};
    cs.recompute(&entries, 1, types.nowMs());

    try std.testing.expectEqual(@as(u32, 0), cs.active_count);
    try std.testing.expectEqual(@as(u32, 0), cs.total_count);
    try std.testing.expectEqual(@as(u64, 1), cs.tick_count);
}

test "central state — counts active and dormant" {
    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();

    var active_entry = entry_mod.Entry{};
    active_entry.id = .{ 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
    active_entry.state = .active;
    active_entry.salience = 0.8;
    active_entry.original_salience = 0.8;
    try entries.put(active_entry.id, &active_entry);

    var dormant_entry = entry_mod.Entry{};
    dormant_entry.id = .{ 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
    dormant_entry.state = .dormant;
    try entries.put(dormant_entry.id, &dormant_entry);

    var cs = state_mod.CentralState{};
    cs.recompute(&entries, 5, types.nowMs());

    try std.testing.expectEqual(@as(u32, 1), cs.active_count);
    try std.testing.expectEqual(@as(u32, 1), cs.dormant_count);
    try std.testing.expectEqual(@as(u32, 2), cs.total_count);
}

test "central state — signals on failed entries" {
    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();

    var failed_entry = entry_mod.Entry{};
    failed_entry.id = .{ 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
    failed_entry.state = .failed;
    try entries.put(failed_entry.id, &failed_entry);

    var cs = state_mod.CentralState{};
    cs.recompute(&entries, 1, types.nowMs());

    try std.testing.expectEqual(@as(u32, 1), cs.failed_count);
    try std.testing.expect(cs.signal_count > 0);
    try std.testing.expectEqual(state_mod.Signal.Severity.warning, cs.signals[0].severity);
}
