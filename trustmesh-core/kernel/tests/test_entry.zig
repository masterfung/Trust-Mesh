const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const entry_mod = podos.entry;
const Entry = entry_mod.Entry;

test "entry default state is dormant" {
    const e = Entry{};
    try std.testing.expectEqual(types.EntryState.dormant, e.state);
    try std.testing.expect(!e.isActive());
    try std.testing.expect(!e.isTerminal());
    try std.testing.expect(!e.isLive());
}

test "entry transition happy path" {
    var e = Entry{};
    try e.transition(.pending);
    try std.testing.expectEqual(types.EntryState.pending, e.state);
    try std.testing.expectEqual(types.EntryState.dormant, e.previous_state);

    try e.transition(.activating);
    try e.transition(.active);
    try std.testing.expect(e.isActive());
    try std.testing.expect(e.isLive());

    try e.transition(.deactivating);
    try e.transition(.completed);
    try std.testing.expectEqual(types.EntryState.completed, e.state);
}

test "entry invalid transition fails" {
    var e = Entry{};
    try std.testing.expectError(error.InvalidTransition, e.transition(.active));
    try std.testing.expectEqual(types.EntryState.dormant, e.state); // unchanged
}

test "entry retry from failed" {
    var e = Entry{};
    try e.transition(.pending);
    try e.transition(.failed);
    try std.testing.expectEqual(types.EntryState.failed, e.state);
    try e.transition(.pending); // retry
    try std.testing.expectEqual(types.EntryState.pending, e.state);
}

test "entry tags" {
    var e = Entry{};
    try e.setTag("health");
    try e.setTag("vaccination");
    try std.testing.expectEqual(@as(u8, 2), e.tag_count);
    try std.testing.expect(e.hasTag("health"));
    try std.testing.expect(e.hasTag("vaccination"));
    try std.testing.expect(!e.hasTag("finance"));
}

test "entry label and category" {
    var e = Entry{};
    e.setLabel("Flu Season Advisory");
    e.setCategory("health");
    try std.testing.expectEqualStrings("Flu Season Advisory", e.getLabel());
    try std.testing.expectEqualStrings("health", e.getCategory());
}

test "shouldActivateByTime" {
    const now = types.nowMs();
    var e = Entry{};
    e.activation_trigger.kind = .time;
    e.activation_trigger.time.at = now - 1000; // 1 second ago
    try std.testing.expect(e.shouldActivateByTime(now));

    // Future trigger shouldn't activate
    var e2 = Entry{};
    e2.activation_trigger.kind = .time;
    e2.activation_trigger.time.at = now + 60_000; // 1 minute from now
    try std.testing.expect(!e2.shouldActivateByTime(now));
}

test "window expiry" {
    const now = types.nowMs();
    var e = Entry{};
    e.window_end = now - 1000; // ended 1 second ago
    try std.testing.expect(e.isWindowExpired(now));

    var e2 = Entry{};
    e2.window_end = now + 60_000; // ends in 1 minute
    try std.testing.expect(!e2.isWindowExpired(now));

    // No window end = never expires
    const e3 = Entry{};
    try std.testing.expect(!e3.isWindowExpired(now));
}

test "isWithinWindow" {
    const now = types.nowMs();

    // Within window
    var e = Entry{};
    e.window_start = now - 60_000;
    e.window_end = now + 60_000;
    try std.testing.expect(e.isWithinWindow(now));

    // Before window
    var e2 = Entry{};
    e2.window_start = now + 60_000;
    e2.window_end = now + 120_000;
    try std.testing.expect(!e2.isWithinWindow(now));

    // No window = always in window
    const e3 = Entry{};
    try std.testing.expect(e3.isWithinWindow(now));
}

test "hook retry tracking" {
    var hook = entry_mod.Hook{};
    hook.max_retries = 3;
    hook.retry_backoff_ms = 1000;

    try std.testing.expectEqual(@as(u8, 0), hook.attempts);
    try std.testing.expect(!hook.isExhausted());

    hook.attempts = 4;
    try std.testing.expect(hook.isExhausted());
}

test "hook exponential backoff" {
    var hook = entry_mod.Hook{};
    hook.retry_backoff_ms = 1000;

    hook.attempts = 0;
    try std.testing.expectEqual(@as(u32, 1000), hook.backoffMs()); // 1000 * 2^0

    hook.attempts = 1;
    try std.testing.expectEqual(@as(u32, 2000), hook.backoffMs()); // 1000 * 2^1

    hook.attempts = 2;
    try std.testing.expectEqual(@as(u32, 4000), hook.backoffMs()); // 1000 * 2^2

    // Should cap at 5 minutes
    hook.attempts = 20;
    try std.testing.expectEqual(@as(u32, 300_000), hook.backoffMs());
}

test "absence trigger" {
    const now = types.nowMs();
    var e = Entry{};
    e.activation_trigger.kind = .absence;
    e.activation_trigger.absence.expected_by = now - 1000; // deadline passed

    try std.testing.expect(e.shouldFireAbsence(now));

    // Already fired
    e.activation_trigger.absence.fired = true;
    try std.testing.expect(!e.shouldFireAbsence(now));
}

test "salience reset" {
    var e = Entry{};
    e.salience = 0.5;
    e.original_salience = 0.8;
    e.resetSalience();
    try std.testing.expectApproxEqAbs(@as(f32, 0.8), e.salience, 0.001);
}
