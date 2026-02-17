const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const event_mod = podos.event;
const entry_mod = podos.entry;

test "event queue push and pop" {
    var q = try event_mod.EventQueue.init(std.testing.allocator, 4);
    defer q.deinit(std.testing.allocator);

    var evt = event_mod.Event{};
    evt.setEventType("timeline.entry_created");
    evt.source = .federation;
    evt.timestamp = types.nowMs();

    try q.push(evt);
    try std.testing.expectEqual(@as(u32, 1), q.len());

    const popped = q.pop().?;
    try std.testing.expectEqualStrings("timeline.entry_created", popped.getEventType());
    try std.testing.expect(q.isEmpty());
}

test "event queue overflow" {
    var q = try event_mod.EventQueue.init(std.testing.allocator, 3);
    defer q.deinit(std.testing.allocator);

    const evt = event_mod.Event{};
    try q.push(evt);
    try q.push(evt);
    // Queue of capacity 3 holds 2 items (ring buffer: 1 slot reserved)
    try std.testing.expectError(error.QueueFull, q.push(evt));
}

test "event queue empty pop returns null" {
    var q = try event_mod.EventQueue.init(std.testing.allocator, 4);
    defer q.deinit(std.testing.allocator);

    try std.testing.expect(q.pop() == null);
}

test "event matching — exact type" {
    var pattern = entry_mod.EventTriggerMatch{};
    const type_str = "timeline.entry_created";
    @memcpy(pattern.type_pattern[0..type_str.len], type_str);
    pattern.type_pattern_len = type_str.len;
    pattern.source_filter = .system; // wildcard

    var evt = event_mod.Event{};
    evt.setEventType("timeline.entry_created");
    evt.source = .federation;

    try std.testing.expect(event_mod.matches(&pattern, &evt));
}

test "event matching — wildcard prefix" {
    var pattern = entry_mod.EventTriggerMatch{};
    const type_str = "timeline.*";
    @memcpy(pattern.type_pattern[0..type_str.len], type_str);
    pattern.type_pattern_len = type_str.len;
    pattern.source_filter = .system;

    var evt = event_mod.Event{};
    evt.setEventType("timeline.entry_created");
    try std.testing.expect(event_mod.matches(&pattern, &evt));

    var evt2 = event_mod.Event{};
    evt2.setEventType("capsule.updated");
    try std.testing.expect(!event_mod.matches(&pattern, &evt2));
}

test "event matching — star matches all" {
    var pattern = entry_mod.EventTriggerMatch{};
    const type_str = "*";
    @memcpy(pattern.type_pattern[0..type_str.len], type_str);
    pattern.type_pattern_len = type_str.len;
    pattern.source_filter = .system;

    var evt = event_mod.Event{};
    evt.setEventType("anything.goes.here");
    try std.testing.expect(event_mod.matches(&pattern, &evt));
}
