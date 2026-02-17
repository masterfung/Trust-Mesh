// PodOS Timeline Kernel — 3-stream conflict resolution
// Private > Internal > Open. Same category + overlapping window = conflict.
// Losers get salience reduced (shadowed), not deleted.

const std = @import("std");
const types = @import("types.zig");
const Entry = @import("entry.zig").Entry;

/// Two entries conflict if they share a category AND overlap in time.
pub fn entriesConflict(a: *const Entry, b: *const Entry) bool {
    // Must share a category
    if (a.category_len == 0 or b.category_len == 0) return false;
    const cat_a = a.category[0..a.category_len];
    const cat_b = b.category[0..b.category_len];
    if (!std.mem.eql(u8, cat_a, cat_b)) return false;

    // Must overlap in time
    const a_start = effectiveWindowStart(a);
    const a_end = effectiveWindowEnd(a);
    const b_start = effectiveWindowStart(b);
    const b_end = effectiveWindowEnd(b);

    // Overlap: a_start < b_end AND b_start < a_end
    return a_start < b_end and b_start < a_end;
}

/// Effective window start: use window_start if set, else anchor - 1h, else 0.
fn effectiveWindowStart(e: *const Entry) types.Timestamp {
    if (e.window_start > 0) return e.window_start;
    if (e.anchor > 0) return e.anchor - 3_600_000; // 1 hour before anchor
    return 0; // unbounded start
}

/// Effective window end: use window_end if set, else anchor + 1h, else max.
fn effectiveWindowEnd(e: *const Entry) types.Timestamp {
    if (e.window_end > 0) return e.window_end;
    if (e.anchor > 0) return e.anchor + 3_600_000; // 1 hour after anchor
    return std.math.maxInt(types.Timestamp); // unbounded end
}

/// Shadow factor: how much to reduce salience of the losing entry.
const SHADOW_FACTOR: f32 = 0.3;

/// Resolve conflicts among a list of entries.
/// Higher visibility wins. Loser's salience is reduced.
/// Returns the number of conflicts resolved.
pub fn resolveConflicts(entries: []*Entry) u32 {
    var resolved: u32 = 0;

    // First, reset all saliences to original (un-shadow from previous ticks)
    for (entries) |e| {
        if (e.isActive() or e.state == .activating) {
            e.salience = e.original_salience;
        }
    }

    // Pairwise conflict check (O(n^2) but n is small)
    for (entries, 0..) |a, i| {
        if (!a.isActive() and a.state != .activating) continue;

        for (entries[i + 1 ..]) |b| {
            if (!b.isActive() and b.state != .activating) continue;

            if (entriesConflict(a, b)) {
                if (a.visibility.overrides(b.visibility)) {
                    // a wins, shadow b
                    b.salience = b.original_salience * SHADOW_FACTOR;
                    resolved += 1;
                } else if (b.visibility.overrides(a.visibility)) {
                    // b wins, shadow a
                    a.salience = a.original_salience * SHADOW_FACTOR;
                    resolved += 1;
                }
                // Same visibility: both remain, agent decides
            }
        }
    }

    return resolved;
}

/// Check if entries share any tags (for public stream filtering).
pub fn sharesTag(a: *const Entry, b: *const Entry) bool {
    for (0..a.tag_count) |i| {
        const a_tag = a.tags[i][0..a.tag_lengths[i]];
        for (0..b.tag_count) |j| {
            const b_tag = b.tags[j][0..b.tag_lengths[j]];
            if (std.mem.eql(u8, a_tag, b_tag)) return true;
        }
    }
    return false;
}
