const std = @import("std");
const podos = @import("podos");
const types = podos.types;
const entry_mod = podos.entry;
const dag_mod = podos.dag;

fn makeId(val: u8) types.EntryId {
    var id: types.EntryId = .{0} ** 16;
    id[0] = val;
    return id;
}

test "dag init and deinit" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();
}

test "dag add entry with no deps" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();

    var e = entry_mod.Entry{};
    e.id = makeId(1);
    // No deps — should be a no-op
    try dag.addEntry(&e);
}

test "dag add entry with deps" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();

    var e = entry_mod.Entry{};
    e.id = makeId(2);
    e.deps[0] = .{ .entry_id = makeId(1), .required_state = .active, .is_hard = true };
    e.dep_count = 1;
    try dag.addEntry(&e);
}

test "dag deps satisfied — no deps" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();

    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();

    var e = entry_mod.Entry{};
    e.id = makeId(1);
    const result = dag.depsSatisfied(&e, &entries);
    try std.testing.expect(result.satisfied);
}

test "dag deps satisfied — hard dep met" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();

    var dep_entry = entry_mod.Entry{};
    dep_entry.id = makeId(1);
    dep_entry.state = .active;

    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();
    try entries.put(dep_entry.id, &dep_entry);

    var e = entry_mod.Entry{};
    e.id = makeId(2);
    e.deps[0] = .{ .entry_id = makeId(1), .required_state = .active, .is_hard = true };
    e.dep_count = 1;

    const result = dag.depsSatisfied(&e, &entries);
    try std.testing.expect(result.satisfied);
}

test "dag deps satisfied — hard dep not met" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();

    var dep_entry = entry_mod.Entry{};
    dep_entry.id = makeId(1);
    dep_entry.state = .dormant; // not active

    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();
    try entries.put(dep_entry.id, &dep_entry);

    var e = entry_mod.Entry{};
    e.id = makeId(2);
    e.deps[0] = .{ .entry_id = makeId(1), .required_state = .active, .is_hard = true };
    e.dep_count = 1;

    const result = dag.depsSatisfied(&e, &entries);
    try std.testing.expect(!result.satisfied);
}

test "dag soft dep — warns but doesn't block" {
    var dag = dag_mod.DependencyGraph.init(std.testing.allocator);
    defer dag.deinit();

    var dep_entry = entry_mod.Entry{};
    dep_entry.id = makeId(1);
    dep_entry.state = .dormant; // not met

    var entries = std.AutoHashMap(types.EntryId, *entry_mod.Entry).init(std.testing.allocator);
    defer entries.deinit();
    try entries.put(dep_entry.id, &dep_entry);

    var e = entry_mod.Entry{};
    e.id = makeId(2);
    e.deps[0] = .{ .entry_id = makeId(1), .required_state = .active, .is_hard = false }; // soft
    e.dep_count = 1;

    const result = dag.depsSatisfied(&e, &entries);
    try std.testing.expect(result.satisfied); // soft deps don't block
    try std.testing.expectEqual(@as(u8, 1), result.soft_warnings);
}
