// rate_limit.zig — Sliding window rate limiters replacing Python's SlidingWindowCounter.
// Application-level protection against mass-befriending, query spam, and scraping.

const std = @import("std");
const Allocator = std.mem.Allocator;

pub const RateLimitError = error{
    OutOfMemory,
};

/// Result of a rate limit check.
pub const CheckResult = struct {
    allowed: bool,
    message: [128]u8,
    message_len: usize,

    pub fn getMessage(self: *const CheckResult) []const u8 {
        return self.message[0..self.message_len];
    }
};

fn okResult() CheckResult {
    var r = CheckResult{ .allowed = true, .message = undefined, .message_len = 2 };
    r.message[0] = 'o';
    r.message[1] = 'k';
    return r;
}

fn deniedResult(msg: []const u8) CheckResult {
    var r = CheckResult{ .allowed = false, .message = undefined, .message_len = @min(msg.len, 128) };
    @memcpy(r.message[0..r.message_len], msg[0..r.message_len]);
    return r;
}

/// Simple sliding window counter using in-memory storage.
pub const SlidingWindowCounter = struct {
    /// key (heap-duped) → list of event timestamps (unix seconds)
    events: std.StringHashMapUnmanaged(std.ArrayListUnmanaged(i64)),
    allocator: Allocator,

    pub fn init(allocator: Allocator) SlidingWindowCounter {
        return .{
            .events = .{},
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *SlidingWindowCounter) void {
        var it = self.events.iterator();
        while (it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
            entry.value_ptr.deinit(self.allocator);
        }
        self.events.deinit(self.allocator);
    }

    /// Record an event for a key.
    pub fn record(self: *SlidingWindowCounter, key: []const u8) RateLimitError!void {
        const now = std.time.timestamp();
        if (self.events.getPtr(key)) |list| {
            list.append(self.allocator, now) catch return RateLimitError.OutOfMemory;
        } else {
            const owned_key = self.allocator.dupe(u8, key) catch return RateLimitError.OutOfMemory;
            var list = std.ArrayListUnmanaged(i64){};
            list.append(self.allocator, now) catch {
                self.allocator.free(owned_key);
                return RateLimitError.OutOfMemory;
            };
            self.events.put(self.allocator, owned_key, list) catch {
                list.deinit(self.allocator);
                self.allocator.free(owned_key);
                return RateLimitError.OutOfMemory;
            };
        }
    }

    /// Count events in the last window_seconds. Also prunes old events.
    pub fn count(self: *SlidingWindowCounter, key: []const u8, window_seconds: i64) usize {
        const list = self.events.getPtr(key) orelse return 0;
        const cutoff = std.time.timestamp() - window_seconds;

        // Prune old events
        var write: usize = 0;
        for (list.items) |ts| {
            if (ts > cutoff) {
                list.items[write] = ts;
                write += 1;
            }
        }
        list.shrinkRetainingCapacity(write);
        return list.items.len;
    }

    /// Clear all tracked events.
    pub fn reset(self: *SlidingWindowCounter) void {
        var it = self.events.iterator();
        while (it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
            entry.value_ptr.deinit(self.allocator);
        }
        self.events.clearRetainingCapacity();
    }
};

/// Combined rate limiter with connection + query + pin + emergency counters.
pub const RateLimiter = struct {
    connection: SlidingWindowCounter,
    query: SlidingWindowCounter,
    pin: SlidingWindowCounter, // 5 per 15 min per user
    emergency_issue: SlidingWindowCounter, // 3 per hour per key
    emergency_present: SlidingWindowCounter, // 5 per hour per key
    allocator: Allocator,

    pub fn init(allocator: Allocator) RateLimiter {
        return .{
            .connection = SlidingWindowCounter.init(allocator),
            .query = SlidingWindowCounter.init(allocator),
            .pin = SlidingWindowCounter.init(allocator),
            .emergency_issue = SlidingWindowCounter.init(allocator),
            .emergency_present = SlidingWindowCounter.init(allocator),
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *RateLimiter) void {
        self.connection.deinit();
        self.query.deinit();
        self.pin.deinit();
        self.emergency_issue.deinit();
        self.emergency_present.deinit();
    }

    // ── Connection Rate Limiting ──

    /// Check if user can send a connection request.
    /// Limits: 10/day, 30/week.
    pub fn checkConnection(self: *RateLimiter, user_id: []const u8) CheckResult {
        // Build keys in stack buffers
        var day_key_buf: [256]u8 = undefined;
        var week_key_buf: [256]u8 = undefined;

        const day_key = fmtKey(&day_key_buf, "conn:", user_id, ":day");
        const week_key = fmtKey(&week_key_buf, "conn:", user_id, ":week");

        const daily = self.connection.count(day_key, 86400);
        if (daily >= 10) {
            return deniedResult("Daily connection request limit reached (10/day). Try again tomorrow.");
        }

        const weekly = self.connection.count(week_key, 604800);
        if (weekly >= 30) {
            return deniedResult("Weekly connection request limit reached (30/week).");
        }

        return okResult();
    }

    /// Record a connection request for rate limiting.
    pub fn recordConnection(self: *RateLimiter, user_id: []const u8) RateLimitError!void {
        var day_key_buf: [256]u8 = undefined;
        var week_key_buf: [256]u8 = undefined;

        const day_key = fmtKey(&day_key_buf, "conn:", user_id, ":day");
        const week_key = fmtKey(&week_key_buf, "conn:", user_id, ":week");

        try self.connection.record(day_key);
        try self.connection.record(week_key);
    }

    // ── Query Rate Limiting ──

    /// Build a per-target rate limit key: "query:{user_id}:{target_id}:hour"
    fn fmtTargetKey(buf: []u8, user_id: []const u8, target_id: []const u8) []const u8 {
        const prefix = "query:";
        const sep = ":";
        const suffix = ":hour";
        const total = prefix.len + user_id.len + sep.len + target_id.len + suffix.len;
        if (total > buf.len) return buf[0..0]; // safe truncation
        var pos: usize = 0;
        @memcpy(buf[pos..][0..prefix.len], prefix);
        pos += prefix.len;
        @memcpy(buf[pos..][0..user_id.len], user_id);
        pos += user_id.len;
        @memcpy(buf[pos..][0..sep.len], sep);
        pos += sep.len;
        @memcpy(buf[pos..][0..target_id.len], target_id);
        pos += target_id.len;
        @memcpy(buf[pos..][0..suffix.len], suffix);
        pos += suffix.len;
        return buf[0..pos];
    }

    /// Check if user can send a query.
    /// Limits: 5/min burst, 5-20/hr per-target, 20-100/day total (trust-dependent).
    pub fn checkQuery(
        self: *RateLimiter,
        user_id: []const u8,
        target_id: []const u8,
        is_public: bool,
    ) CheckResult {
        var burst_buf: [256]u8 = undefined;
        var target_buf: [512]u8 = undefined;
        var daily_buf: [256]u8 = undefined;

        const burst_key = fmtKey(&burst_buf, "query:", user_id, ":burst");
        const daily_key = fmtKey(&daily_buf, "query:", user_id, ":day");
        const target_key = fmtTargetKey(&target_buf, user_id, target_id);

        // Burst limit: 5/min (all trust levels)
        const burst = self.query.count(burst_key, 60);
        if (burst >= 5) {
            return deniedResult("Too many queries. Please wait a minute.");
        }

        // Per-target hourly
        const per_target = self.query.count(target_key, 3600);
        if (is_public) {
            if (per_target >= 5) {
                return deniedResult("Query limit reached for this user (5/hour for public access).");
            }
        } else {
            if (per_target >= 20) {
                return deniedResult("Query limit reached for this user (20/hour).");
            }
        }

        // Daily total
        const daily = self.query.count(daily_key, 86400);
        if (is_public) {
            if (daily >= 20) {
                return deniedResult("Daily query limit reached (20/day for public access).");
            }
        } else {
            if (daily >= 100) {
                return deniedResult("Daily query limit reached (100/day).");
            }
        }

        return okResult();
    }

    /// Record a query for rate limiting.
    pub fn recordQuery(
        self: *RateLimiter,
        user_id: []const u8,
        target_id: []const u8,
    ) RateLimitError!void {
        var burst_buf: [256]u8 = undefined;
        var daily_buf: [256]u8 = undefined;
        var target_buf: [512]u8 = undefined;

        const burst_key = fmtKey(&burst_buf, "query:", user_id, ":burst");
        const daily_key = fmtKey(&daily_buf, "query:", user_id, ":day");
        const target_key = fmtTargetKey(&target_buf, user_id, target_id);

        try self.query.record(burst_key);
        try self.query.record(target_key);
        try self.query.record(daily_key);
    }

    // ── PIN Rate Limiting ──

    /// Check PIN attempt rate (5 per 15 min per user_id).
    pub fn checkPin(self: *RateLimiter, user_id: []const u8) CheckResult {
        const count = self.pin.count(user_id, 900); // 15 min window
        if (count >= 5) {
            return deniedResult("Too many PIN attempts. Try again in 15 minutes.");
        }
        return okResult();
    }

    /// Record a PIN attempt.
    pub fn recordPin(self: *RateLimiter, user_id: []const u8) RateLimitError!void {
        try self.pin.record(user_id);
    }

    // ── Emergency Rate Limiting ──

    /// Check emergency token issuance rate (3 per hour per key).
    /// Key should be "{issuer_id}:{patient_id}".
    pub fn checkEmergencyIssue(self: *RateLimiter, key: []const u8) CheckResult {
        const count = self.emergency_issue.count(key, 3600);
        if (count >= 3) {
            return deniedResult("Emergency token issuance limit reached (3/hour per patient).");
        }
        return okResult();
    }

    /// Record an emergency token issuance.
    pub fn recordEmergencyIssue(self: *RateLimiter, key: []const u8) RateLimitError!void {
        try self.emergency_issue.record(key);
    }

    /// Check emergency access rate (5 per hour per token hash).
    pub fn checkEmergencyPresent(self: *RateLimiter, key: []const u8) CheckResult {
        const count = self.emergency_present.count(key, 3600);
        if (count >= 5) {
            return deniedResult("Emergency access limit reached. Token has been used too many times.");
        }
        return okResult();
    }

    /// Record an emergency access attempt.
    pub fn recordEmergencyPresent(self: *RateLimiter, key: []const u8) RateLimitError!void {
        try self.emergency_present.record(key);
    }

    /// Reset all rate limit state (test helper).
    pub fn reset(self: *RateLimiter) void {
        self.connection.reset();
        self.query.reset();
        self.pin.reset();
        self.emergency_issue.reset();
        self.emergency_present.reset();
    }
};

/// Format a key: prefix + middle + suffix into a stack buffer. Returns slice.
fn fmtKey(buf: []u8, prefix: []const u8, middle: []const u8, suffix: []const u8) []const u8 {
    var pos: usize = 0;
    @memcpy(buf[pos..][0..prefix.len], prefix);
    pos += prefix.len;
    @memcpy(buf[pos..][0..middle.len], middle);
    pos += middle.len;
    @memcpy(buf[pos..][0..suffix.len], suffix);
    pos += suffix.len;
    return buf[0..pos];
}
