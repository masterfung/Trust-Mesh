// PodOS Timeline Kernel — Event queue (ring buffer)

const std = @import("std");
const types = @import("types.zig");

pub const Event = struct {
    source: types.EventSource = .system,
    event_type: [types.MAX_EVENT_TYPE_LEN]u8 = .{0} ** types.MAX_EVENT_TYPE_LEN,
    event_type_len: u8 = 0,
    timestamp: types.Timestamp = 0,
    // Payload is opaque — host interprets it
    payload_ptr: ?[*]const u8 = null,
    payload_len: u32 = 0,

    pub fn getEventType(self: *const Event) []const u8 {
        return self.event_type[0..self.event_type_len];
    }

    pub fn setEventType(self: *Event, t: []const u8) void {
        const len: u8 = @intCast(@min(t.len, types.MAX_EVENT_TYPE_LEN));
        @memcpy(self.event_type[0..len], t[0..len]);
        self.event_type_len = len;
    }
};

pub const EventQueue = struct {
    buffer: []Event,
    head: u32 = 0, // read position
    tail: u32 = 0, // write position
    capacity: u32,

    pub fn init(allocator: std.mem.Allocator, capacity: u32) !EventQueue {
        const buf = try allocator.alloc(Event, capacity);
        return .{
            .buffer = buf,
            .head = 0,
            .tail = 0,
            .capacity = capacity,
        };
    }

    pub fn deinit(self: *EventQueue, allocator: std.mem.Allocator) void {
        allocator.free(self.buffer);
    }

    pub fn push(self: *EventQueue, evt: Event) !void {
        const next = (self.tail + 1) % self.capacity;
        if (next == self.head) return error.QueueFull;
        self.buffer[self.tail] = evt;
        self.tail = next;
    }

    pub fn pop(self: *EventQueue) ?Event {
        if (self.head == self.tail) return null;
        const evt = self.buffer[self.head];
        self.head = (self.head + 1) % self.capacity;
        return evt;
    }

    pub fn len(self: *const EventQueue) u32 {
        if (self.tail >= self.head) return self.tail - self.head;
        return self.capacity - self.head + self.tail;
    }

    pub fn isEmpty(self: *const EventQueue) bool {
        return self.head == self.tail;
    }
};

/// Match an event against an EventTriggerMatch pattern.
pub fn matches(pattern: *const @import("entry.zig").EventTriggerMatch, evt: *const Event) bool {
    // Source filter: if pattern specifies a source, it must match
    if (@intFromEnum(pattern.source_filter) != @intFromEnum(evt.source)) {
        // Allow system source as wildcard (matches everything)
        if (pattern.source_filter != .system) return false;
    }

    // Type pattern: simple prefix match for now (glob * not implemented yet)
    const pat = pattern.getTypePattern();
    const evt_type = evt.getEventType();

    if (pat.len == 0) return true; // empty pattern matches all

    // Exact match or prefix with wildcard
    if (std.mem.eql(u8, pat, "*")) return true;
    if (std.mem.eql(u8, pat, evt_type)) return true;

    // Prefix match: "timeline.*" matches "timeline.entry_created"
    if (pat.len > 0 and pat[pat.len - 1] == '*') {
        const prefix = pat[0 .. pat.len - 1];
        if (std.mem.startsWith(u8, evt_type, prefix)) return true;
    }

    return false;
}
