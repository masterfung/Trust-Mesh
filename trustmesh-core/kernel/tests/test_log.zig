const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const log_mod = podos.log;

test "transition log — no file (in-memory mode)" {
    var tlog = try log_mod.TransitionLog.init("");
    defer tlog.deinit();

    // Should not error even without a file
    try tlog.append(.{
        .entry_id = .{ 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
        .from_state = .dormant,
        .to_state = .pending,
        .trigger_kind = .time,
        .tick = 1,
        .timestamp = types.nowMs(),
    });
}

test "transition log — write and replay" {
    const path = "/tmp/podos_test_log.bin";

    // Clean up from previous test runs
    std.fs.cwd().deleteFile(path) catch {};

    {
        var tlog = try log_mod.TransitionLog.init(path);
        defer tlog.deinit();

        try tlog.append(.{
            .entry_id = .{ 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
            .from_state = .dormant,
            .to_state = .pending,
            .trigger_kind = .time,
            .tick = 1,
            .timestamp = 1000,
        });

        try tlog.append(.{
            .entry_id = .{ 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
            .from_state = .pending,
            .to_state = .activating,
            .trigger_kind = .dependency,
            .tick = 2,
            .timestamp = 2000,
        });

        try std.testing.expectEqual(@as(u64, 2), tlog.record_count);
    }

    // Reopen and replay
    {
        var tlog = try log_mod.TransitionLog.init(path);
        defer tlog.deinit();

        const records = try tlog.replay(std.testing.allocator);
        defer std.testing.allocator.free(records);

        try std.testing.expectEqual(@as(usize, 2), records.len);
        try std.testing.expectEqual(types.EntryState.dormant, records[0].from_state);
        try std.testing.expectEqual(types.EntryState.pending, records[0].to_state);
        try std.testing.expectEqual(@as(u64, 1), records[0].tick);
        try std.testing.expectEqual(types.EntryState.pending, records[1].from_state);
        try std.testing.expectEqual(types.EntryState.activating, records[1].to_state);
    }

    // Clean up
    std.fs.cwd().deleteFile(path) catch {};
}
