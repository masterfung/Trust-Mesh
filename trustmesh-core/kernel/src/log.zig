// PodOS Timeline Kernel — Append-only transition log
// Persists every state transition for crash recovery and audit.
// Format: newline-delimited binary records (fast, compact).

const std = @import("std");
const types = @import("types.zig");

pub const TransitionRecord = struct {
    entry_id: types.EntryId,
    from_state: types.EntryState,
    to_state: types.EntryState,
    trigger_kind: types.TriggerKind,
    tick: u64,
    timestamp: types.Timestamp,
};

// Serialized record size (fixed for binary format)
const RECORD_SIZE = 16 + 1 + 1 + 1 + 8 + 8; // 35 bytes

pub const TransitionLog = struct {
    file: ?std.fs.File = null,
    record_count: u64 = 0,

    pub fn init(path: []const u8) !TransitionLog {
        if (path.len == 0) return .{}; // no log path = in-memory only

        const file = try std.fs.cwd().createFile(path, .{
            .truncate = false,
            .read = true,
        });
        // Seek to end for append
        const size = try file.getEndPos();
        try file.seekTo(size);

        return .{
            .file = file,
            .record_count = size / RECORD_SIZE,
        };
    }

    pub fn deinit(self: *TransitionLog) void {
        if (self.file) |f| f.close();
        self.file = null;
    }

    /// Append a transition record to the log.
    pub fn append(self: *TransitionLog, record: TransitionRecord) !void {
        const f = self.file orelse return; // no file = skip

        var buf: [RECORD_SIZE]u8 = undefined;
        var offset: usize = 0;

        // entry_id (16 bytes)
        @memcpy(buf[offset .. offset + 16], &record.entry_id);
        offset += 16;

        // from_state (1 byte)
        buf[offset] = @intFromEnum(record.from_state);
        offset += 1;

        // to_state (1 byte)
        buf[offset] = @intFromEnum(record.to_state);
        offset += 1;

        // trigger_kind (1 byte)
        buf[offset] = @intFromEnum(record.trigger_kind);
        offset += 1;

        // tick (8 bytes, little-endian)
        std.mem.writeInt(u64, buf[offset..][0..8], record.tick, .little);
        offset += 8;

        // timestamp (8 bytes, little-endian)
        std.mem.writeInt(i64, buf[offset..][0..8], record.timestamp, .little);
        offset += 8;

        _ = try f.write(&buf);
        self.record_count += 1;
    }

    /// Read all records for crash recovery (replay).
    pub fn replay(self: *TransitionLog, allocator: std.mem.Allocator) ![]TransitionRecord {
        const f = self.file orelse return &[_]TransitionRecord{};

        try f.seekTo(0);
        const size = try f.getEndPos();
        const count = size / RECORD_SIZE;

        var records = try allocator.alloc(TransitionRecord, count);
        var i: usize = 0;
        while (i < count) : (i += 1) {
            var buf: [RECORD_SIZE]u8 = undefined;
            const bytes_read = try f.readAll(&buf);
            if (bytes_read < RECORD_SIZE) break;

            var offset: usize = 0;
            var record: TransitionRecord = undefined;

            @memcpy(&record.entry_id, buf[offset .. offset + 16]);
            offset += 16;

            record.from_state = @enumFromInt(buf[offset]);
            offset += 1;

            record.to_state = @enumFromInt(buf[offset]);
            offset += 1;

            record.trigger_kind = @enumFromInt(buf[offset]);
            offset += 1;

            record.tick = std.mem.readInt(u64, buf[offset..][0..8], .little);
            offset += 8;

            record.timestamp = std.mem.readInt(i64, buf[offset..][0..8], .little);
            offset += 8;

            records[i] = record;
        }

        // Seek back to end for future appends
        try f.seekTo(size);
        return records[0..i];
    }

    /// Prune records before a given tick.
    /// This is expensive (rewrites file) — call infrequently.
    pub fn pruneBefore(self: *TransitionLog, tick: u64, allocator: std.mem.Allocator) !void {
        const all = try self.replay(allocator);
        defer allocator.free(all);

        // Filter to keep only records >= tick
        var keep = std.ArrayList(TransitionRecord){};
        defer keep.deinit(allocator);

        for (all) |record| {
            if (record.tick >= tick) try keep.append(allocator, record);
        }

        // Rewrite file
        const f = self.file orelse return;
        try f.seekTo(0);
        try f.setEndPos(0);
        self.record_count = 0;

        for (keep.items) |record| {
            try self.append(record);
        }
    }
};
