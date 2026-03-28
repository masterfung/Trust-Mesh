// Research cache + freshness scoring engine.
// - In-memory LRU cache for TinyFish results (URL + goal → result, TTL-checked)
// - Composite freshness scorer for vault capsule ranking
//
// Thread-safe via std.Thread.Mutex. Max 500 entries, LRU eviction.
// All allocations via module-level GPA — freed on eviction or update.

const std = @import("std");

const MAX_ENTRIES: usize = 500;
const KEY_LEN: usize = 64; // SHA-256 hex = 64 chars

const CacheEntry = struct {
    key: [KEY_LEN]u8,
    value: []u8,
    stored_at: i64,
    ttl_secs: i64,
};

var gpa = std.heap.GeneralPurposeAllocator(.{}){};
// Zig 0.15: ArrayList initialized as empty struct; allocator passed per-operation
var entries: std.ArrayList(CacheEntry) = .{};
var mutex: std.Thread.Mutex = .{};
var initialized: bool = false;

fn ensure_init() void {
    if (!initialized) {
        entries = std.ArrayList(CacheEntry){};
        initialized = true;
    }
}

fn allocator() std.mem.Allocator {
    return gpa.allocator();
}

fn make_key(url: []const u8, goal: []const u8, out: *[KEY_LEN]u8) void {
    var h = std.crypto.hash.sha2.Sha256.init(.{});
    h.update(url);
    h.update("::");
    h.update(goal);
    var digest: [32]u8 = undefined;
    h.final(&digest);
    const hex = std.fmt.bytesToHex(digest, .lower);
    @memcpy(out, &hex);
}

/// Look up a cached result. Returns the value slice (owned by the cache) or null on miss/expiry.
/// Caller must NOT free the returned slice.
pub fn cache_get(url: []const u8, goal: []const u8, max_age: i64) ?[]const u8 {
    ensure_init();
    mutex.lock();
    defer mutex.unlock();
    var key: [KEY_LEN]u8 = undefined;
    make_key(url, goal, &key);
    const now = std.time.timestamp();
    for (entries.items) |*e| {
        if (std.mem.eql(u8, &e.key, &key)) {
            const effective_ttl = @min(e.ttl_secs, max_age);
            if (now - e.stored_at < effective_ttl) {
                return e.value;
            }
            return null; // expired
        }
    }
    return null; // miss
}

/// Store a result in the cache. Duplicates are updated in-place.
/// The cache copies the value bytes.
pub fn cache_put(url: []const u8, goal: []const u8, value: []const u8, ttl: i64) !void {
    ensure_init();
    mutex.lock();
    defer mutex.unlock();
    var key: [KEY_LEN]u8 = undefined;
    make_key(url, goal, &key);
    const now = std.time.timestamp();
    const alloc = allocator();
    // Update existing entry
    for (entries.items) |*e| {
        if (std.mem.eql(u8, &e.key, &key)) {
            alloc.free(e.value);
            e.value = try alloc.dupe(u8, value);
            e.stored_at = now;
            e.ttl_secs = ttl;
            return;
        }
    }
    // LRU eviction at capacity
    if (entries.items.len >= MAX_ENTRIES) {
        var oldest: usize = 0;
        for (entries.items, 0..) |e, i| {
            if (e.stored_at < entries.items[oldest].stored_at) {
                oldest = i;
            }
        }
        alloc.free(entries.items[oldest].value);
        _ = entries.orderedRemove(oldest);
    }
    var new_entry: CacheEntry = undefined;
    new_entry.key = key;
    new_entry.value = try alloc.dupe(u8, value);
    new_entry.stored_at = now;
    new_entry.ttl_secs = ttl;
    try entries.append(alloc, new_entry);
}

/// Composite freshness score: 0.0 (stale/low-authority) to 1.0 (fresh + high authority).
/// freshness_type: 0=permanent (score=1.0), 1=temporary (decays /30d), 2=recurring (decays /7d)
/// authority_weight is clamped to [0.0, 2.0] then averaged with recency.
pub fn freshness_score(freshness_type: u8, days_since_verified: i32, authority: f32) f32 {
    const d: f32 = @floatFromInt(days_since_verified);
    const recency: f32 = switch (freshness_type) {
        0 => 1.0,
        1 => @max(0.0, 1.0 - d / 30.0),
        2 => @max(0.0, 1.0 - d / 7.0),
        else => 0.5,
    };
    const clamped_authority = @min(authority, 2.0);
    return recency * clamped_authority * 0.5;
}
