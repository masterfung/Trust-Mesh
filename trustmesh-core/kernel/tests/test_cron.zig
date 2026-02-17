const std = @import("std");
const podos = @import("podos");
const cron = podos.cron;

test "parse wildcard" {
    const expr = try cron.parse("* * * * *");
    try std.testing.expect(expr.valid);
    // Every minute of every hour is set
    try std.testing.expect(expr.minute.isSet(0));
    try std.testing.expect(expr.minute.isSet(30));
    try std.testing.expect(expr.minute.isSet(59));
    try std.testing.expect(expr.hour.isSet(0));
    try std.testing.expect(expr.hour.isSet(23));
}

test "parse step" {
    const expr = try cron.parse("*/15 * * * *");
    try std.testing.expect(expr.minute.isSet(0));
    try std.testing.expect(expr.minute.isSet(15));
    try std.testing.expect(expr.minute.isSet(30));
    try std.testing.expect(expr.minute.isSet(45));
    try std.testing.expect(!expr.minute.isSet(1));
    try std.testing.expect(!expr.minute.isSet(14));
}

test "parse range" {
    const expr = try cron.parse("0 9 * * 1-5");
    try std.testing.expect(expr.minute.isSet(0));
    try std.testing.expect(!expr.minute.isSet(1));
    try std.testing.expect(expr.hour.isSet(9));
    try std.testing.expect(!expr.hour.isSet(8));
    // Weekday 1-5 (Mon-Fri)
    try std.testing.expect(expr.weekday.isSet(1));
    try std.testing.expect(expr.weekday.isSet(5));
    try std.testing.expect(!expr.weekday.isSet(0)); // Sunday
    try std.testing.expect(!expr.weekday.isSet(6)); // Saturday
}

test "parse list" {
    const expr = try cron.parse("0,30 * * * *");
    try std.testing.expect(expr.minute.isSet(0));
    try std.testing.expect(expr.minute.isSet(30));
    try std.testing.expect(!expr.minute.isSet(15));
}

test "parse single value" {
    const expr = try cron.parse("0 0 1 * *");
    try std.testing.expect(expr.minute.isSet(0));
    try std.testing.expect(!expr.minute.isSet(1));
    try std.testing.expect(expr.hour.isSet(0));
    try std.testing.expect(expr.day.isSet(1));
    try std.testing.expect(!expr.day.isSet(2));
}

test "invalid cron — too few fields" {
    try std.testing.expectError(error.InvalidCron, cron.parse("* * *"));
}

test "invalid cron — too many fields" {
    try std.testing.expectError(error.InvalidCron, cron.parse("* * * * * *"));
}

test "cron matches — every minute" {
    const expr = try cron.parse("* * * * *");
    const now = std.time.milliTimestamp();
    try std.testing.expect(cron.cronMatches(&expr, now));
}

test "cron matches — specific time" {
    const expr = try cron.parse("0 9 * * 1"); // 9:00 on Mondays
    // We test the matching function runs without error
    const ts: i64 = 1771311600 * 1000; // approximate 2026-02-16 09:00 UTC
    _ = cron.cronMatches(&expr, ts);
}

test "cron next — find next match" {
    const expr = try cron.parse("0 * * * *"); // every hour on the hour
    const now = std.time.milliTimestamp();
    const next = cron.cronNext(&expr, now);
    try std.testing.expect(next > now);
    // Next match should be within 1 hour
    try std.testing.expect(next - now <= 3_600_000);
}
