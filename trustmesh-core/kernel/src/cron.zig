// PodOS Timeline Kernel — Cron expression parser and matcher
// Standard 5-field cron: minute hour day month weekday
// Supports: values, wildcards (*), ranges (1-5), lists (1,3,5), steps (*/5)

const std = @import("std");
const types = @import("types.zig");

pub const CronField = struct {
    // Bitset: bit N means "value N is included"
    // minute: 0-59 (60 bits), hour: 0-23, day: 1-31, month: 1-12, weekday: 0-6
    bits: u64 = 0,

    pub fn isSet(self: CronField, val: u6) bool {
        return (self.bits & (@as(u64, 1) << val)) != 0;
    }

    pub fn set(self: *CronField, val: u6) void {
        self.bits |= (@as(u64, 1) << val);
    }

    pub fn setRange(self: *CronField, from: u6, to: u6) void {
        var i = from;
        while (i <= to) : (i += 1) {
            self.set(i);
        }
    }

    pub fn setAll(self: *CronField, min: u6, max: u6) void {
        self.setRange(min, max);
    }
};

pub const CronExpr = struct {
    minute: CronField = .{},
    hour: CronField = .{},
    day: CronField = .{},
    month: CronField = .{},
    weekday: CronField = .{},
    valid: bool = false,
};

/// Parse a single cron field (e.g., "*/5", "1-5", "1,3,5", "*", "3")
fn parseField(field: []const u8, min: u6, max: u6) !CronField {
    var result = CronField{};

    if (field.len == 0) return error.InvalidCron;

    // Wildcard: *
    if (std.mem.eql(u8, field, "*")) {
        result.setAll(min, max);
        return result;
    }

    // Step: */N or M-N/S
    if (std.mem.indexOfScalar(u8, field, '/')) |slash_pos| {
        const base_str = field[0..slash_pos];
        const step_str = field[slash_pos + 1 ..];
        const step = std.fmt.parseInt(u6, step_str, 10) catch return error.InvalidCron;
        if (step == 0) return error.InvalidCron;

        var range_min = min;
        var range_max = max;

        if (!std.mem.eql(u8, base_str, "*")) {
            // M-N/S form
            if (std.mem.indexOfScalar(u8, base_str, '-')) |dash| {
                range_min = std.fmt.parseInt(u6, base_str[0..dash], 10) catch return error.InvalidCron;
                range_max = std.fmt.parseInt(u6, base_str[dash + 1 ..], 10) catch return error.InvalidCron;
            } else {
                range_min = std.fmt.parseInt(u6, base_str, 10) catch return error.InvalidCron;
            }
        }

        var i = range_min;
        while (i <= range_max) {
            result.set(i);
            const next = @as(u7, i) + step;
            if (next > max) break;
            i = @intCast(next);
        }
        return result;
    }

    // List: 1,3,5
    if (std.mem.indexOfScalar(u8, field, ',') != null) {
        var it = std.mem.splitScalar(u8, field, ',');
        while (it.next()) |part| {
            const val = std.fmt.parseInt(u6, part, 10) catch return error.InvalidCron;
            if (val < min or val > max) return error.InvalidCron;
            result.set(val);
        }
        return result;
    }

    // Range: 1-5
    if (std.mem.indexOfScalar(u8, field, '-')) |dash| {
        const from = std.fmt.parseInt(u6, field[0..dash], 10) catch return error.InvalidCron;
        const to = std.fmt.parseInt(u6, field[dash + 1 ..], 10) catch return error.InvalidCron;
        if (from < min or to > max or from > to) return error.InvalidCron;
        result.setRange(from, to);
        return result;
    }

    // Single value
    const val = std.fmt.parseInt(u6, field, 10) catch return error.InvalidCron;
    if (val < min or val > max) return error.InvalidCron;
    result.set(val);
    return result;
}

/// Parse a 5-field cron expression: "min hour day month weekday"
pub fn parse(pattern: []const u8) !CronExpr {
    var expr = CronExpr{};
    var fields: [5][]const u8 = undefined;
    var count: usize = 0;

    var it = std.mem.splitScalar(u8, pattern, ' ');
    while (it.next()) |field| {
        if (field.len == 0) continue; // skip extra spaces
        if (count >= 5) return error.InvalidCron;
        fields[count] = field;
        count += 1;
    }
    if (count != 5) return error.InvalidCron;

    expr.minute = try parseField(fields[0], 0, 59);
    expr.hour = try parseField(fields[1], 0, 23);
    expr.day = try parseField(fields[2], 1, 31);
    expr.month = try parseField(fields[3], 1, 12);
    expr.weekday = try parseField(fields[4], 0, 6);
    expr.valid = true;

    return expr;
}

/// Decompose a timestamp into UTC components.
const TimeComponents = struct {
    minute: u6,
    hour: u6,
    day: u6, // 1-31
    month: u6, // 1-12
    weekday: u6, // 0=Sun, 1=Mon, ..., 6=Sat
};

fn decompose(ts: types.Timestamp) TimeComponents {
    const epoch_secs: i64 = @divTrunc(ts, 1000);
    const es = std.time.epoch.EpochSeconds{ .secs = @intCast(@max(0, epoch_secs)) };
    const day_seconds = es.getDaySeconds();
    const epoch_day = es.getEpochDay();
    const year_day = epoch_day.calculateYearDay();
    const month_day = year_day.calculateMonthDay();

    // Weekday: epoch (1970-01-01) was Thursday (4)
    const weekday_raw: u6 = @intCast((@as(u64, @intCast(epoch_day.day)) + 4) % 7);

    return .{
        .minute = @intCast(day_seconds.getMinutesIntoHour()),
        .hour = @intCast(day_seconds.getHoursIntoDay()),
        .day = @intCast(month_day.day_index + 1), // 1-based
        .month = @intCast(month_day.month.numeric()), // 1-based via numeric()
        .weekday = weekday_raw,
    };
}

/// Check if a timestamp matches a cron expression.
pub fn cronMatches(expr: *const CronExpr, ts: types.Timestamp) bool {
    if (!expr.valid) return false;
    const tc = decompose(ts);

    return expr.minute.isSet(tc.minute) and
        expr.hour.isSet(tc.hour) and
        expr.day.isSet(tc.day) and
        expr.month.isSet(tc.month) and
        expr.weekday.isSet(tc.weekday);
}

/// Find the next timestamp after `after` that matches the cron expression.
/// Scans forward minute-by-minute up to max_scan_minutes (default 525960 = 1 year).
/// Returns 0 if not found within scan range.
pub fn cronNext(expr: *const CronExpr, after: types.Timestamp) types.Timestamp {
    const max_scan: i64 = 525960; // minutes in a year
    var candidate = after + 60_000; // start from next minute
    // Align to minute boundary
    candidate = @divTrunc(candidate, 60_000) * 60_000;

    var scanned: i64 = 0;
    while (scanned < max_scan) : (scanned += 1) {
        if (cronMatches(expr, candidate)) return candidate;
        candidate += 60_000;
    }
    return 0; // not found
}
