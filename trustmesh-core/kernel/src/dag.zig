// PodOS Timeline Kernel — Dependency graph with cycle detection
// Adjacency list DAG. Entries depend on other entries being in a required state.
// Topo sort gives evaluation order. Cycle detection prevents infinite loops.

const std = @import("std");
const types = @import("types.zig");
const Entry = @import("entry.zig").Entry;

const IdList = std.ArrayList(types.EntryId);
const AdjList = std.AutoHashMap(types.EntryId, IdList);

pub const DependencyGraph = struct {
    allocator: std.mem.Allocator,
    // Forward edges: entry -> list of entries it depends on
    forward: AdjList,
    // Reverse edges: entry -> list of entries that depend on it
    reverse: AdjList,

    pub fn init(allocator: std.mem.Allocator) DependencyGraph {
        return .{
            .allocator = allocator,
            .forward = AdjList.init(allocator),
            .reverse = AdjList.init(allocator),
        };
    }

    pub fn deinit(self: *DependencyGraph) void {
        var fit = self.forward.valueIterator();
        while (fit.next()) |list| {
            list.deinit(self.allocator);
        }
        self.forward.deinit();

        var rit = self.reverse.valueIterator();
        while (rit.next()) |list| {
            list.deinit(self.allocator);
        }
        self.reverse.deinit();
    }

    /// Register an entry's dependencies in the graph.
    /// Returns error if adding would create a cycle.
    pub fn addEntry(self: *DependencyGraph, entry: *const Entry) !void {
        if (entry.dep_count == 0) return;

        var dep_list = IdList{};
        for (entry.deps[0..entry.dep_count]) |dep| {
            if (types.is_zero_id(dep.entry_id)) continue;
            try dep_list.append(self.allocator, dep.entry_id);

            // Add reverse edge
            const rev = try self.reverse.getOrPut(dep.entry_id);
            if (!rev.found_existing) {
                rev.value_ptr.* = IdList{};
            }
            try rev.value_ptr.append(self.allocator, entry.id);
        }

        try self.forward.put(entry.id, dep_list);

        // Check for cycles after adding
        if (self.hasCycle()) {
            // Rollback: remove the entry we just added
            self.removeEntry(entry.id);
            return error.CycleDetected;
        }
    }

    /// Remove an entry and all its edges from the graph.
    pub fn removeEntry(self: *DependencyGraph, id: types.EntryId) void {
        // Remove forward edges
        if (self.forward.fetchRemove(id)) |kv| {
            var list = kv.value;
            // Clean up reverse edges pointing to this entry
            for (list.items) |dep_id| {
                if (self.reverse.getPtr(dep_id)) |rev_list| {
                    var i: usize = 0;
                    while (i < rev_list.items.len) {
                        if (types.ids_equal(rev_list.items[i], id)) {
                            _ = rev_list.swapRemove(i);
                        } else {
                            i += 1;
                        }
                    }
                }
            }
            list.deinit(self.allocator);
        }

        // Remove reverse edges where this entry is the dependency
        if (self.reverse.fetchRemove(id)) |kv| {
            var list = kv.value;
            // Clean up forward edges pointing to this entry
            for (list.items) |dep_id| {
                if (self.forward.getPtr(dep_id)) |fwd_list| {
                    var i: usize = 0;
                    while (i < fwd_list.items.len) {
                        if (types.ids_equal(fwd_list.items[i], id)) {
                            _ = fwd_list.swapRemove(i);
                        } else {
                            i += 1;
                        }
                    }
                }
            }
            list.deinit(self.allocator);
        }
    }

    /// Check if the graph contains a cycle using DFS coloring.
    /// White=unvisited, Gray=in-progress, Black=done.
    pub fn hasCycle(self: *DependencyGraph) bool {
        var colors = std.AutoHashMap(types.EntryId, Color).init(self.allocator);
        defer colors.deinit();

        var it = self.forward.keyIterator();
        while (it.next()) |key| {
            colors.put(key.*, .white) catch continue;
        }

        var kit = self.forward.keyIterator();
        while (kit.next()) |key| {
            const color = colors.get(key.*) orelse .white;
            if (color == .white) {
                if (self.dfsCycleCheck(key.*, &colors)) return true;
            }
        }
        return false;
    }

    const Color = enum { white, gray, black };

    fn dfsCycleCheck(self: *DependencyGraph, node: types.EntryId, colors: *std.AutoHashMap(types.EntryId, Color)) bool {
        colors.put(node, .gray) catch return false;

        if (self.forward.get(node)) |deps| {
            for (deps.items) |dep_id| {
                const dep_color = colors.get(dep_id) orelse .white;
                if (dep_color == .gray) return true; // back edge = cycle
                if (dep_color == .white) {
                    if (self.dfsCycleCheck(dep_id, colors)) return true;
                }
            }
        }

        colors.put(node, .black) catch {};
        return false;
    }

    /// Check if all hard dependencies for an entry are satisfied.
    pub fn depsSatisfied(
        self: *DependencyGraph,
        entry: *const Entry,
        entries: *const std.AutoHashMap(types.EntryId, *Entry),
    ) struct { satisfied: bool, soft_warnings: u8 } {
        _ = self;
        var satisfied = true;
        var soft_warnings: u8 = 0;

        for (entry.deps[0..entry.dep_count]) |dep| {
            if (types.is_zero_id(dep.entry_id)) continue;

            if (entries.get(dep.entry_id)) |dep_entry| {
                const dep_met = @intFromEnum(dep_entry.state) >= @intFromEnum(dep.required_state);
                if (!dep_met) {
                    if (dep.is_hard) {
                        satisfied = false;
                        break;
                    } else {
                        soft_warnings += 1;
                    }
                }
            } else {
                // Dep entry not found
                if (dep.is_hard) {
                    satisfied = false;
                    break;
                } else {
                    soft_warnings += 1;
                }
            }
        }

        return .{ .satisfied = satisfied, .soft_warnings = soft_warnings };
    }
};
