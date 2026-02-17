const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const entry_mod = podos.entry;
const event_mod = podos.event;
const timeline = podos.timeline;

fn makeId(val: u8) types.EntryId {
    var id: types.EntryId = .{0} ** 16;
    id[0] = val;
    return id;
}

test "engine init and deinit" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{});
    engine.deinit();
}

test "engine add entry" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{});
    defer engine.deinit();

    var e = entry_mod.Entry{};
    e.id = makeId(1);
    e.setLabel("Test entry");
    e.setCategory("health");

    const id = try engine.addEntry(e);
    try std.testing.expect(types.ids_equal(id, makeId(1)));

    const retrieved = engine.getEntry(makeId(1));
    try std.testing.expect(retrieved != null);
    try std.testing.expectEqualStrings("Test entry", retrieved.?.getLabel());
}

test "engine tick — time trigger activates entry" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{ .heartbeat_ms = 100 });
    defer engine.deinit();
    engine.is_running = true;

    const now = types.nowMs();
    var e = entry_mod.Entry{};
    e.id = makeId(1);
    e.activation_trigger.kind = .time;
    e.activation_trigger.time.at = now - 1000; // 1 second ago
    e.setCategory("health");
    e.setLabel("Overdue checkup");

    _ = try engine.addEntry(e);

    // Tick should transition: dormant -> pending -> activating -> active
    try engine.tick(); // dormant -> pending
    const after_tick = engine.getEntry(makeId(1)).?;
    // After one tick: should be at least pending (may advance further depending on deps)
    try std.testing.expect(@intFromEnum(after_tick.state) >= @intFromEnum(types.EntryState.pending));
}

test "engine tick — event trigger activates entry" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{ .heartbeat_ms = 100 });
    defer engine.deinit();
    engine.is_running = true;

    var e = entry_mod.Entry{};
    e.id = makeId(1);
    e.activation_trigger.kind = .event;
    const event_type = "timeline.entry_created";
    @memcpy(e.activation_trigger.event_match.type_pattern[0..event_type.len], event_type);
    e.activation_trigger.event_match.type_pattern_len = event_type.len;
    e.activation_trigger.event_match.source_filter = .system; // wildcard

    e.setCategory("health");

    _ = try engine.addEntry(e);

    // Push matching event
    var evt = event_mod.Event{};
    evt.setEventType("timeline.entry_created");
    evt.source = .federation;
    evt.timestamp = types.nowMs();
    try engine.pushEvent(evt);

    // Tick should match event and start transition
    try engine.tick();
    const after = engine.getEntry(makeId(1)).?;
    try std.testing.expect(@intFromEnum(after.state) >= @intFromEnum(types.EntryState.pending));
}

test "engine tick — window expiry deactivates entry" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{ .heartbeat_ms = 100 });
    defer engine.deinit();
    engine.is_running = true;

    const now = types.nowMs();
    var e = entry_mod.Entry{};
    e.id = makeId(1);
    e.state = .active; // already active
    e.window_end = now - 1000; // expired 1 second ago
    e.setCategory("health");

    _ = try engine.addEntry(e);

    try engine.tick();
    const after = engine.getEntry(makeId(1)).?;
    // Should be deactivating or completed
    try std.testing.expect(@intFromEnum(after.state) >= @intFromEnum(types.EntryState.deactivating));
}

test "engine central state recomputed each tick" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{ .heartbeat_ms = 100 });
    defer engine.deinit();
    engine.is_running = true;

    var e = entry_mod.Entry{};
    e.id = makeId(1);
    e.state = .active;
    e.salience = 0.8;
    e.original_salience = 0.8;
    e.setCategory("health");

    _ = try engine.addEntry(e);

    try engine.tick();
    try std.testing.expectEqual(@as(u32, 1), engine.central_state.active_count);
    try std.testing.expect(engine.central_state.computed_at > 0);
}

test "engine tick count increments" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{});
    defer engine.deinit();
    engine.is_running = true;

    try engine.tick();
    try std.testing.expectEqual(@as(u64, 1), engine.tick_count);
    try engine.tick();
    try std.testing.expectEqual(@as(u64, 2), engine.tick_count);
}

test "engine not running — tick is no-op" {
    const engine = try timeline.Engine.init(std.testing.allocator, .{});
    defer engine.deinit();
    // is_running defaults to false

    try engine.tick();
    try std.testing.expectEqual(@as(u64, 0), engine.tick_count);
}
