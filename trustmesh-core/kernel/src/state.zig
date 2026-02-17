// PodOS Timeline Kernel — Central state computation
// The "process table" of PodOS. Computed each tick from all entries.
// This is what the agent sees and what GET /api/timeline/state returns.

const std = @import("std");
const types = @import("types.zig");
const Entry = @import("entry.zig").Entry;

pub const MAX_SIGNALS = 32;
pub const MAX_UPCOMING = 16;

pub const Signal = struct {
    severity: Severity,
    message: [256]u8 = .{0} ** 256,
    message_len: u16 = 0,
    related_entry_id: types.EntryId = types.ZERO_ID,

    pub const Severity = enum(u8) {
        info = 0,
        warning = 1,
        attention = 2,
        critical = 3,
    };

    pub fn getMessage(self: *const Signal) []const u8 {
        return self.message[0..self.message_len];
    }
};

pub const UpcomingEntry = struct {
    entry_id: types.EntryId,
    fires_at: types.Timestamp,
    label: [types.MAX_LABEL_LEN]u8 = .{0} ** types.MAX_LABEL_LEN,
    label_len: u8 = 0,
    entry_type: types.EntryType = .event,
};

pub const CentralState = struct {
    // Counts
    active_count: u32 = 0,
    pending_count: u32 = 0,
    dormant_count: u32 = 0,
    failed_count: u32 = 0,
    total_count: u32 = 0,

    // Active entry IDs (sorted by salience descending)
    active_ids: [1024]types.EntryId = [_]types.EntryId{types.ZERO_ID} ** 1024,

    // Signals (warnings, conflicts, attention items)
    signals: [MAX_SIGNALS]Signal = [_]Signal{.{ .severity = .info }} ** MAX_SIGNALS,
    signal_count: u16 = 0,

    // Upcoming entries (sorted by fire time)
    upcoming: [MAX_UPCOMING]UpcomingEntry = undefined,
    upcoming_count: u16 = 0,

    // Tick metadata
    tick_count: u64 = 0,
    computed_at: types.Timestamp = 0,
    conflicts_resolved: u32 = 0,

    /// Recompute the central state from all entries.
    pub fn recompute(
        self: *CentralState,
        entries: *const std.AutoHashMap(types.EntryId, *Entry),
        tick: u64,
        now: types.Timestamp,
    ) void {
        self.active_count = 0;
        self.pending_count = 0;
        self.dormant_count = 0;
        self.failed_count = 0;
        self.total_count = 0;
        self.signal_count = 0;
        self.upcoming_count = 0;
        self.tick_count = tick;
        self.computed_at = now;

        var it = entries.valueIterator();
        while (it.next()) |entry_ptr| {
            const e = entry_ptr.*;
            if (e.is_deleted or e.state == .deleted) continue;

            self.total_count += 1;

            switch (e.state) {
                .active => {
                    if (self.active_count < 1024) {
                        self.active_ids[self.active_count] = e.id;
                        self.active_count += 1;
                    }
                },
                .pending, .activating => self.pending_count += 1,
                .dormant => {
                    self.dormant_count += 1;
                    // Check if this is upcoming (has a time trigger in the future)
                    self.maybeAddUpcoming(e, now);
                },
                .failed => {
                    self.failed_count += 1;
                    self.addSignal(.warning, "Entry failed", e.id);
                },
                else => {},
            }

            // Check for shadowed entries (salience reduced by resolution)
            if (e.state == .active and e.salience < e.original_salience * 0.5) {
                self.addSignal(.info, "Entry shadowed by higher priority", e.id);
            }

            // Check for stale hooks
            if (e.state == .activating) {
                for (e.hooks[0..e.hook_count]) |hook| {
                    if (hook.status == .exhausted) {
                        self.addSignal(.attention, "Hook retries exhausted", e.id);
                    }
                }
            }
        }
    }

    fn maybeAddUpcoming(self: *CentralState, e: *const Entry, now: types.Timestamp) void {
        if (self.upcoming_count >= MAX_UPCOMING) return;

        var fires_at: types.Timestamp = 0;
        if (e.activation_trigger.kind == .time) {
            fires_at = e.activation_trigger.time.at;
            if (fires_at == 0) fires_at = e.window_start;
        }
        if (fires_at == 0 or fires_at <= now) return;

        self.upcoming[self.upcoming_count] = .{
            .entry_id = e.id,
            .fires_at = fires_at,
            .entry_type = e.entry_type,
        };
        // Copy label
        const len: u8 = e.label_len;
        @memcpy(self.upcoming[self.upcoming_count].label[0..len], e.label[0..len]);
        self.upcoming[self.upcoming_count].label_len = len;
        self.upcoming_count += 1;
    }

    fn addSignal(self: *CentralState, severity: Signal.Severity, msg: []const u8, entry_id: types.EntryId) void {
        if (self.signal_count >= MAX_SIGNALS) return;
        var signal = Signal{
            .severity = severity,
            .related_entry_id = entry_id,
        };
        const len: u16 = @intCast(@min(msg.len, 256));
        @memcpy(signal.message[0..len], msg[0..len]);
        signal.message_len = len;
        self.signals[self.signal_count] = signal;
        self.signal_count += 1;
    }
};
